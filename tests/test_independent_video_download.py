"""A Library import cannot disturb a running song or another browser tab."""
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_automatic_lyrics_and_search import load_function


class IndependentDownloadTests(unittest.TestCase):
    def test_processing_does_not_block_import_and_each_request_gets_an_id(self):
        statuses, thread = {}, Mock()
        start = load_function('download_youtube_preset', YouTubePresetModel=object,
            processing_lock=Mock(locked=lambda: True), uuid=uuid, yt_preset_statuses=statuses,
            youtube_status_key=lambda user, kind: user['username'] + ':' + kind,
            threading=SimpleNamespace(Thread=thread), run_youtube_download_bg=Mock())
        for _ in range(2):
            result = start(SimpleNamespace(youtube_url='https://youtu.be/abcdefghijk'), {'username': 'owner'})
            self.assertEqual(result['status'], 'started')
            self.assertEqual(len(result['download_id']), 32)
            self.assertEqual(thread.call_args.kwargs['args'][2], result['download_id'])
        self.assertEqual(len(statuses), 3)
        self.assertEqual(thread.return_value.start.call_count, 2)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = {key: str(self.root/key) for key in ('cache', 'output', 'library')}
        for path in self.paths.values():
            Path(path).mkdir()
        self.cache = self.root/'cache'
        for filename in ('original_input.mp4', 'vocals.wav', 'transcribed_segments.json', 'cache_meta.json'):
            (self.cache/filename).write_bytes(b'active job unchanged')
        self.statuses = {'owner:audio': {'download_id': 'second'}}

    def worker(self, download):
        return load_function('run_youtube_download_bg', os=os, shutil=shutil, tempfile=tempfile, uuid=uuid,
            get_user_paths=lambda _: self.paths, yt_preset_statuses=self.statuses,
            youtube_status_key=lambda user, kind: user['username'] + ':' + kind, download_youtube=download)

    def download(self, url, staging, progress_callback=None, cancel_callback=None):
        self.assertNotEqual(staging, self.paths['cache'])
        self.assertIsNone(cancel_callback)
        progress_callback(37, 'Transferindo mídia do YouTube…')
        path = Path(staging)/'original_input.mp4'
        path.write_bytes(url.encode())
        return str(path), 'Same title'

    def test_imports_preserve_job_cache_existing_media_and_individual_status(self):
        videos = self.root/'library/videos'
        videos.mkdir()
        (videos/'Same title.mp4').write_bytes(b'existing queue source')
        worker = self.worker(self.download)
        worker('first video', {'username': 'owner'}, 'first')
        self.assertEqual(self.statuses['owner:audio']['download_id'], 'second')
        worker('second video', {'username': 'owner'}, 'second')
        first, second = (self.statuses['owner:audio:' + key] for key in ('first', 'second'))
        self.assertEqual((first['status'], second['status']), ('done', 'done'))
        self.assertNotEqual(first['filename'], second['filename'])
        self.assertEqual((videos/first['filename']).read_bytes(), b'first video')
        self.assertEqual((videos/second['filename']).read_bytes(), b'second video')
        self.assertEqual((videos/'Same title.mp4').read_bytes(), b'existing queue source')
        self.assertTrue(all(path.read_bytes() == b'active job unchanged' for path in self.cache.iterdir()))
        self.assertEqual(list((self.root/'output').iterdir()), [])
        self.assertEqual(list(videos.glob('.downloading-*')), [])

    def test_copy_failure_is_an_error_and_partial_file_is_never_published(self):
        def fail_copy(source, destination):
            Path(destination).write_bytes(b'partial')
            raise OSError('disk full')
        with patch.object(shutil, 'copy2', side_effect=fail_copy):
            self.worker(self.download)('url', {'username': 'owner'}, 'second')
        status = self.statuses['owner:audio:second']
        self.assertEqual(status['status'], 'error')
        self.assertEqual(status['filename'], '')
        self.assertEqual(list((self.root/'library/videos').iterdir()), [])
        self.assertEqual(list((self.root/'output').iterdir()), [])

    def test_status_lookup_is_scoped_to_owner_and_download(self):
        status = {'status': 'done', 'filename': 'first.mp4'}
        read = load_function('get_yt_preset_audio_status', Query=lambda value, **_: value,
            youtube_status_key=lambda user, kind: user['username'] + ':' + kind,
            yt_preset_statuses={'owner:audio:first': status}, get_youtube_status=lambda *_: {'status': 'idle'})
        self.assertEqual(read({'username': 'owner'}, 'first'), status)
        self.assertEqual(read({'username': 'other'}, 'first')['status'], 'idle')
        self.assertEqual(read({'username': 'owner'}, 'missing')['status'], 'idle')


if __name__ == '__main__':
    unittest.main()
