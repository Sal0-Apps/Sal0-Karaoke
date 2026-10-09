"""Download sessions stay private, recoverable and independent of channel OAuth."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_download_access import YouTubeDownloadAccess, DownloadAccessError, install_routes, version_key


def cookies(value='private-session', expiry=4102444800):
    return ('# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t'+str(expiry)+'\tSID\t'+value+'\n').encode()


class DownloadAccessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.access = YouTubeDownloadAccess(self.folder.name)

    def module(self, callback):
        calls = []
        class Downloader:
            def __init__(self, options): self.options = options; calls.append(options)
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def extract_info(self, url, download): return callback(self.options, url, download)
        return SimpleNamespace(YoutubeDL=Downloader), calls

    def test_export_accepts_bom_crlf_and_httponly_filters_unrelated_domains(self):
        raw = b'\xef\xbb\xbf' + cookies().replace(b'.youtube.com',b'#HttpOnly_.youtube.com').replace(b'\n',b'\r\n')
        raw += b'.example.com\tTRUE\t/\tTRUE\t4102444800\tSID\tother-private-session\r\n'
        self.access.save(raw)
        content = self.access.cookies_path.read_bytes()
        self.assertIn(b'#HttpOnly_.youtube.com',content); self.assertNotIn(b'other-private-session',content)
        self.assertNotIn(b'\r',content); self.assertEqual(self.access.cookies_path.stat().st_mode & 0o777,0o600)
        self.assertNotIn('private-session',json.dumps(self.access.status()))

    def test_invalid_upload_preserves_working_session(self):
        self.access.save(cookies())
        for raw in (b'{"refresh_token":"wrong-format"}', b'x'*524289, cookies().replace(b'TRUE',b'invalid',1), cookies().replace(b'.youtube.com',b'.youtube.com.attacker.example'), cookies().replace(b'\tSID\t',b'\tbad name\t'), b'\xff'):
            with self.assertRaises(DownloadAccessError): self.access.save(raw)
            self.assertEqual(self.access.cookies_path.read_bytes(),cookies())

    def test_cookie_expiration_and_session_cookies_are_distinguished(self):
        self.assertEqual(self.access.status()['session_state'],'anonymous')
        self.access.save(cookies(expiry=1)); self.assertEqual(self.access.status()['session_state'],'expired')
        self.access.save(cookies(expiry=0)); self.assertEqual(self.access.status()['session_state'],'saved')

    def test_extract_uses_private_disposable_jar_without_mutating_saved_cookie(self):
        self.access.save(cookies())
        def extract(options,url,download):
            jar = Path(options['cookiefile']); self.assertNotEqual(jar,self.access.cookies_path)
            self.assertEqual(jar.read_bytes(),cookies()); self.assertEqual(jar.stat().st_mode & 0o777,0o600)
            jar.write_bytes(cookies('rotated'))
            self.assertEqual(url,'https://youtu.be/abcdefghijk'); self.assertFalse(download)
            return {'title':'Video'}
        module,calls = self.module(extract)
        self.assertEqual(self.access.extract_info(module,'https://youtu.be/abcdefghijk',{'skip_download':True})['title'],'Video')
        self.assertEqual(self.access.cookies_path.read_bytes(),cookies())
        self.assertFalse(Path(calls[0]['cookiefile']).exists())
        self.assertTrue(self.access.status()['last_check']['used_cookies'])

    def test_renewal_while_old_extraction_finishes_keeps_new_cookies_untested(self):
        self.access.save(cookies())
        def extract(options,url,download):
            self.access.save(cookies('renewed-session'))
            Path(options['cookiefile']).write_bytes(cookies('old-rotated'))
            return {'title':'Video'}
        module,_ = self.module(extract); self.access.extract_info(module,'url',{})
        self.assertEqual(self.access.cookies_path.read_bytes(),cookies('renewed-session'))
        self.assertIsNone(self.access.status()['last_check'])

    def test_expired_login_attempt_can_fall_back_to_public_video_once(self):
        self.access.save(cookies())
        def extract(options,url,download):
            if options.get('cookiefile'): raise RuntimeError('The provided YouTube account cookies are no longer valid')
            return {'title':'Public video'}
        module,calls = self.module(extract)
        self.assertEqual(self.access.extract_info(module,'url',{})['title'],'Public video')
        self.assertEqual(len(calls),2); self.assertNotIn('cookiefile',calls[1])
        self.assertTrue(self.access.cookies_path.exists()); self.assertFalse(self.access.status()['last_check']['used_cookies'])

    def test_failed_login_is_bounded_and_returns_action_without_signed_url(self):
        self.access.save(cookies())
        def extract(*args): raise RuntimeError('Sign in to confirm you are not a bot https://private.example/?signature=secret')
        module,calls = self.module(extract)
        with self.assertRaises(DownloadAccessError) as caught: self.access.extract_info(module,'url',{})
        self.assertEqual(len(calls),2); self.assertEqual(caught.exception.recovery,'renew_cookies')
        self.assertNotIn('signature',str(caught.exception)); self.assertNotIn('private.example',json.dumps(self.access.status()))

    def test_cancellation_passes_through_without_anonymous_retry(self):
        self.access.save(cookies())
        def extract(*args): raise InterruptedError('User canceled')
        module,calls = self.module(extract)
        with self.assertRaises(InterruptedError): self.access.extract_info(module,'url',{})
        self.assertEqual(len(calls),1)

    def test_expired_cookies_are_not_sent_to_youtube(self):
        self.access.save(cookies(expiry=1))
        module,calls = self.module(lambda *args:{'title':'Public'})
        self.access.extract_info(module,'url',{})
        self.assertNotIn('cookiefile',calls[0]); self.assertEqual(len(calls),1)

    def test_removing_download_session_does_not_touch_channel_authorization(self):
        token = Path(self.folder.name)/'token.json'; token.write_text('{"refresh_token":"channel-refresh"}')
        self.access.save(cookies()); self.access.clear()
        self.assertTrue(token.exists()); self.assertFalse(self.access.cookies_path.exists())

    def test_engine_date_comparison_does_not_let_old_persistent_engine_win(self):
        self.assertGreater(version_key('2026.10.08'),version_key('2026.09.01.123456.dev0'))
        self.assertGreater(version_key('2026.10.09.123456.dev0'),version_key('2026.10.08'))
        self.assertGreater(version_key('2026.10.08'),version_key('2026.10.08.123456.dev0'))


class DownloadRoutesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.access = YouTubeDownloadAccess(self.folder.name)
        self.patch = patch('youtube_download_access.DOWNLOAD_ACCESS',self.access)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.user = {'username':'owner','role':'admin'}
        self.probe = Mock(return_value={'title':'Song'})
        app = FastAPI()
        def require_admin(user):
            if user['role'] != 'admin': raise HTTPException(403,'Somente administrador.')
        install_routes(app,lambda:self.user,require_admin,self.probe)
        self.client = TestClient(app)

    def test_mobile_file_upload_and_clear_do_not_expose_session_content(self):
        response = self.client.post('/api/youtube-tools/cookies',files={'cookies_file':('cookies.txt',cookies(),'text/plain')})
        self.assertEqual(response.status_code,200); self.assertNotIn('private-session',response.text)
        self.assertEqual(self.client.get('/api/youtube-tools/access').json()['session_state'],'saved')
        self.assertEqual(self.client.delete('/api/youtube-tools/cookies').json()['session_state'],'anonymous')

    def test_non_admin_cannot_read_change_test_or_clear_shared_download_session(self):
        self.user['role'] = 'user'
        self.assertEqual(self.client.get('/api/youtube-tools/access').status_code,403)
        self.assertEqual(self.client.post('/api/youtube-tools/cookies',files={'cookies_file':('cookies.txt',cookies())}).status_code,403)
        self.assertEqual(self.client.delete('/api/youtube-tools/cookies').status_code,403)
        self.assertEqual(self.client.post('/api/youtube-tools/test',json={'url':'https://youtu.be/abcdefghijk'}).status_code,403)
        self.probe.assert_not_called()

    def test_link_test_requires_youtube_address_and_reports_actual_probe(self):
        for url in ('http://127.0.0.1:7860/api/admin', 'https://youtube.com.attacker.example/watch?v=x', 'https://user:secret@www.youtube.com/watch?v=x','file:///data/users.json'):
            self.assertEqual(self.client.post('/api/youtube-tools/test',json={'url':url}).status_code,400)
        self.probe.assert_not_called()
        response = self.client.post('/api/youtube-tools/test',json={'url':'https://youtu.be/abcdefghijk'})
        self.assertEqual(response.json()['title'],'Song'); self.probe.assert_called_once()

    def test_login_and_extractor_failures_return_recovery_action(self):
        self.probe.side_effect = DownloadAccessError('Renove a sessão.','renew_cookies')
        response = self.client.post('/api/youtube-tools/test',json={'url':'https://youtu.be/abcdefghijk'})
        self.assertEqual(response.status_code,400); self.assertEqual(response.headers['X-YouTube-Recovery'],'renew_cookies')
