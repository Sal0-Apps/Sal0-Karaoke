import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
import libretranslate_client as lt
import subtitle_translator as subtitles

CONFIG = {'url': 'http://translator:5000', 'api_key': 'private-key', 'timeout': 10}
ORIGINAL = b'1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n2\n00:00:02,000 --> 00:00:05,000\nGoodbye\n'
TRANSLATED = ORIGINAL.replace(b'Hello world', 'Olá mundo'.encode()).replace(b'Goodbye', b'Adeus')


def response(data=None, status=200, content=b''):
    result = Mock(status_code=status, headers={}, content=content)
    result.json.return_value = data
    return result


class LibreTranslateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / 'original.srt'
        self.destination = Path(directory.name) / 'translated.srt'
        self.source.write_bytes(ORIGINAL)

    def client(self, results):
        client = lt.LibreTranslateClient(CONFIG)
        self.addCleanup(client.close)
        client.session.request = Mock(side_effect=results)
        client.cancel_event = Mock()
        client.cancel_event.is_set.return_value = False
        client.cancel_event.wait.return_value = False
        return client

    def results(self, content=TRANSLATED, url='/download_file/result.srt'):
        return [response([{'code': 'en'}, {'code': 'pt-BR'}]),
                response({'translatedFileUrl': url}), response(content=content)]

    def test_full_file_auto_pt_br_and_original_preserved(self):
        client = self.client(self.results())
        updates = []
        result = client.translate_srt_file(self.source, self.destination, progress_callback=lambda *x: updates.append(x))
        upload = client.session.request.call_args_list[1]
        self.assertTrue(upload.args[1].endswith('/translate_file'))
        self.assertEqual(upload.kwargs['data']['source'], 'auto')
        self.assertEqual(upload.kwargs['data']['target'], 'pt-BR')
        self.assertEqual(upload.kwargs['files']['file'][1], ORIGINAL)
        self.assertEqual(self.source.read_bytes(), ORIGINAL)
        self.assertEqual(self.destination.read_bytes(), TRANSLATED)
        self.assertEqual(result[1]['end'], 5)
        self.assertEqual(updates, [(0, 1), (1, 1)])

    def test_wrapper_closes_client_and_normalizes_language(self):
        with patch.object(lt, 'LibreTranslateClient') as factory:
            subtitles.translate_subtitle_file(self.source, self.destination, 'PT_br')
            self.assertEqual(factory.return_value.translate_srt_file.call_args.args[2], 'pt-BR')
            factory.return_value.close.assert_called_once()

    def test_invalid_or_retimed_result_never_published(self):
        for content in (b'', b'<html>Error</html>', TRANSLATED.replace(b'05,000', b'06,000')):
            client = self.client(self.results(content))
            with self.assertRaises(lt.TranslationServiceError):
                client.translate_srt_file(self.source, self.destination)
            self.assertFalse(self.destination.exists())
            self.assertEqual(self.source.read_bytes(), ORIGINAL)

    def test_foreign_download_url_rejected(self):
        client = self.client(self.results(url='http://other-server/result.srt'))
        with self.assertRaises(lt.TranslationServiceError):
            client.translate_srt_file(self.source, self.destination)
        self.assertEqual(client.session.request.call_count, 2)

    def test_retry_repeats_complete_file(self):
        results = self.results()
        results.insert(1, response({}, 503))
        client = self.client(results)
        client.translate_srt_file(self.source, self.destination)
        calls = client.session.request.call_args_list
        self.assertEqual(calls[1].kwargs['files'], calls[2].kwargs['files'])
        self.assertFalse(calls[2].kwargs['allow_redirects'])

    def test_auth_error_does_not_leak_payload(self):
        client = self.client([response({'error': 'private-key'}, 403)])
        with self.assertRaises(lt.TranslationServiceError) as caught:
            client.translate_srt_file(self.source, self.destination)
        self.assertNotIn('private', str(caught.exception))
        self.assertEqual(client.session.request.call_count, 1)

    def test_file_translation_unavailable(self):
        client = self.client(self.results()[:1] + [response({}, 404)])
        with self.assertRaisesRegex(lt.TranslationServiceError, 'arquivos'):
            client.translate_srt_file(self.source, self.destination)
        self.assertEqual(self.source.read_bytes(), ORIGINAL)

    def test_missing_pt_br_does_not_substitute_pt(self):
        client = self.client([response([{'code': 'pt'}, {'code': 'en'}])])
        with self.assertRaises(lt.TranslationServiceError):
            client.translate_srt_file(self.source, self.destination)
        self.assertEqual(client.session.request.call_count, 1)

    def test_cancellation_stops_requests(self):
        client = self.client([])
        client.cancel_event.is_set.return_value = True
        with self.assertRaises(InterruptedError):
            client.translate_srt_file(self.source, self.destination)
        client.session.request.assert_not_called()

    def test_config_is_atomic_and_key_not_returned(self):
        with patch.object(lt, 'CONFIG_FILE', self.source.parent / 'config.json'):
            public = lt.save_config('http://translator:5000/', 'private-key')
            self.assertEqual(public['timeout'], 1800)
            self.assertNotIn('private-key', str(public))
            lt.save_config('http://translator:5000', None)
            self.assertEqual(lt.load_config()['api_key'], 'private-key')
            lt.save_config('http://translator:5000', '')
            self.assertFalse(lt.public_config()['has_api_key'])

    def test_url_rejects_embedded_secrets(self):
        for url in ('file:///etc/passwd', 'http://user:secret@server', 'http://server?key=secret'):
            with self.assertRaises(ValueError):
                lt.normalize_url(url)


if __name__ == '__main__':
    unittest.main()
