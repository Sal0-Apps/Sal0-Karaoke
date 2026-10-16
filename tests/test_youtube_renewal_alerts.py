"""Grant renewal, expired upload sessions and administrator notifications."""
from pathlib import Path
import sys
import threading
import time
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_publisher import YouTubePublisher, PublicationError
from test_youtube_publisher import response
from test_automatic_lyrics_and_search import load_function


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.publisher = YouTubePublisher(self.folder.name)
        self.token = dict(access_token='private-access', refresh_token='private-refresh',
            channel_id='channel', channel_title='Meu canal', expires_at=time.time()+3600)
        self.publisher.save('token.json', self.token)
        self.video = Path(self.folder.name) / 'video.mp4'
        self.video.write_bytes(b'video fixture')
        self.job = dict(id='job', title='Canção', channel_id='channel', status='queued',
            video=str(self.video), upload_uri='https://www.googleapis.com/upload/youtube/v3/videos?upload_id=expired', progress=43)
        self.publisher.save('jobs.json', [self.job])

    def wait_alert(self):
        deadline = time.monotonic()+3
        while self.publisher._auth_alert_pending and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertFalse(self.publisher._auth_alert_pending)

    def test_expired_session_restarts_once_with_same_job_and_new_uri(self):
        replies = [response(404), response(headers={'Location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=new'}),
                   response(308), response(data={'id':'abcdefghijk'})]
        with patch.object(self.publisher, 'upload_request', side_effect=replies) as request:
            self.assertEqual(self.publisher.upload_video(self.job), 'abcdefghijk')
        self.assertEqual(request.call_count, 4)
        self.assertEqual(request.call_args_list[-1].kwargs['data'], b'video fixture')
        self.assertEqual(len(self.publisher.read('jobs.json', [])), 1)
        self.assertEqual(self.job['video_id'], 'abcdefghijk')

    def test_expired_sessions_cannot_create_unbounded_uploads(self):
        replies = [response(404), response(headers={'Location':'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=new'}), response(404)]
        with patch.object(self.publisher, 'upload_request', side_effect=replies) as request:
            with self.assertRaises(PublicationError) as caught:
                self.publisher.upload_video(self.job)
        self.assertEqual(caught.exception.kind, 'upload_session_expired')
        self.assertEqual(request.call_count, 3)

    def test_confirmed_video_is_never_uploaded_again(self):
        self.job['video_id'] = 'abcdefghijk'
        with patch.object(self.publisher, 'upload_request') as request:
            self.assertEqual(self.publisher.upload_video(self.job), 'abcdefghijk')
        request.assert_not_called()

    def test_renewal_resumes_legacy_session_error_but_keeps_unrelated_errors(self):
        self.job.update(status='error', error='A sessão de envio expirou ou foi recusada. Verifique o canal antes de iniciar outro envio.')
        other = {**self.job, 'id':'other', 'error':'Disco cheio', 'video_id':'existing001'}
        self.publisher.save('jobs.json', [self.job, other])
        with patch.object(self.publisher, 'start') as start:
            self.publisher.save_authorization(dict(self.token))
        jobs = self.publisher.read('jobs.json', [])
        self.assertEqual(jobs[0]['status'], 'queued')
        self.assertEqual(jobs[0]['upload_uri'], self.job['upload_uri'])
        self.assertEqual(jobs[1]['status'], 'error')
        start.assert_called_once()

    def test_late_error_from_old_authorization_does_not_block_new_grant(self):
        calls = []
        self.publisher.start = Mock()
        def publish(job):
            calls.append(job['id'])
            if len(calls) == 1:
                self.publisher.save_authorization(dict(self.token))
                raise PublicationError('Old grant expired', 'auth_required')
            self.publisher.checkpoint(job, status='done')
        with patch.object(self.publisher, 'publish', side_effect=publish):
            self.publisher.work()
        self.assertEqual(calls, ['job', 'job'])
        self.assertEqual(self.publisher.read('jobs.json', [])[0]['status'], 'done')
        self.assertNotIn('auth_error', self.publisher.read('token.json'))

    def test_alert_is_deduplicated_across_polling_and_process_restart(self):
        notify = Mock(return_value=True)
        self.publisher.on_auth_required = notify
        for _ in range(4):
            self.publisher.notify_auth_required('Expired')
        self.wait_alert()
        restarted = YouTubePublisher(self.folder.name)
        restarted.on_auth_required = notify
        restarted.notify_auth_required('Expired')
        self.assertEqual(notify.call_count, 1)
        self.assertNotIn('private-', str(notify.call_args))

    def test_failed_alert_can_be_retried_and_renewal_allows_next_expiry_alert(self):
        notify = Mock(side_effect=[False, True, True])
        self.publisher.on_auth_required = notify
        self.publisher.notify_auth_required('Expired'); self.wait_alert()
        self.assertNotIn('auth_alert_notified_at', self.publisher.read('token.json'))
        self.publisher.notify_auth_required('Expired'); self.wait_alert()
        with patch.object(self.publisher, 'start'):
            self.publisher.save_authorization(dict(self.token))
        self.publisher.notify_auth_required('Expired again'); self.wait_alert()
        self.assertEqual(notify.call_count, 3)

    def test_notification_acknowledgement_cannot_restore_old_token_after_renewal(self):
        entered, release = threading.Event(), threading.Event()
        def notify(event):
            entered.set(); release.wait(3); return True
        self.publisher.on_auth_required = notify
        try:
            self.publisher.notify_auth_required('Expired')
            self.assertTrue(entered.wait(2))
            with patch.object(self.publisher, 'start'):
                self.publisher.save_authorization(dict(self.token, access_token='renewed'))
        finally:
            release.set(); self.wait_alert()
        saved = self.publisher.read('token.json')
        self.assertEqual(saved['access_token'], 'renewed')
        self.assertNotIn('auth_error', saved)
        self.assertNotIn('auth_alert_notified_at', saved)

    def test_google_paid_api_endpoints_and_redirects_are_blocked(self):
        invalid = ['https://www.googleapis.com/drive/v3/files',
            'https://www.googleapis.com/youtube/v3/../../billing/v1/projects',
            'https://www.googleapis.com/youtube/v3/%2e%2e/billing',
            'https://speech.googleapis.com/v1/speech:recognize',
            'https://www.googleapis.com.evil.test/youtube/v3/videos']
        with patch('youtube_publisher.requests.request') as request:
            for url in invalid:
                with self.subTest(url=url), self.assertRaises(PublicationError):
                    self.publisher.authenticated_request('GET', url, 10)
            request.assert_not_called()
        with patch('youtube_publisher.requests.request', return_value=response()) as request:
            self.publisher.api('GET', '/videos')
        self.assertIs(request.call_args.kwargs['allow_redirects'], False)

    def test_paid_google_translation_cannot_be_configured_as_libretranslate(self):
        from libretranslate_client import normalize_url
        for url in ('https://translation.googleapis.com', 'https://generativelanguage.googleapis.com',
                    'https://translation.googleapis.com.', 'https://translation.googleapis.com.../translate',
                    'https://translation.google%61pis.com', 'https://google%61pis.com',
                    'https://translation.ｇｏｏｇｌｅａｐｉｓ.com', 'https://translation.googleapis。com'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_url(url)
        self.assertEqual(normalize_url('http://libretranslate:5000'), 'http://libretranslate:5000')

    def test_quota_limit_stops_work_without_billing_or_renewal_alert(self):
        self.publisher.on_auth_required = Mock()
        error = response(403, {'error':{'errors':[{'reason':'quotaExceeded'}]}})
        with patch('youtube_publisher.requests.request', return_value=error) as request:
            with self.assertRaises(PublicationError) as caught:
                self.publisher.api('GET', '/videos')
        self.assertEqual(caught.exception.kind, 'quota_exceeded')
        self.assertEqual(request.call_count, 1)
        self.publisher.on_auth_required.assert_not_called()

    def test_upload_post_and_put_quota_limits_stop_without_probe_or_alert(self):
        self.publisher.on_auth_required = Mock()
        for method in ('POST', 'PUT'):
            for reason in ('quotaExceeded', 'dailyLimitExceeded'):
                with self.subTest(method=method, reason=reason):
                    error = response(403, {'error': {'errors': [{'reason': reason}]}})
                    with patch('youtube_publisher.requests.request', return_value=error) as request:
                        with self.assertRaises(PublicationError) as caught:
                            self.publisher.upload_request(method,
                                'https://www.googleapis.com/upload/youtube/v3/videos', data=b'video fixture')
                    self.assertEqual(caught.exception.kind, 'quota_exceeded')
                    self.assertIn('Aguarde', str(caught.exception))
                    self.assertEqual(request.call_count, 1)
                    self.assertNotIn('auth_error', self.publisher.read('token.json'))
        self.publisher.on_auth_required.assert_not_called()

    def test_upload_permission_failure_requires_renewal_and_notifies_admins(self):
        self.publisher.on_auth_required = Mock(return_value=True)
        error = response(403, {'error': {'errors': [{'reason': 'insufficientPermissions'}]}})
        with patch('youtube_publisher.requests.request', return_value=error) as request:
            with self.assertRaises(PublicationError) as caught:
                self.publisher.upload_request('POST',
                    'https://www.googleapis.com/upload/youtube/v3/videos', data=b'video fixture')
        self.wait_alert()
        self.assertEqual(caught.exception.kind, 'auth_required')
        self.assertEqual(request.call_count, 1)
        self.publisher.on_auth_required.assert_called_once()
        saved = self.publisher.read('token.json')
        self.assertIn('Reconecte', saved['auth_error'])
        self.assertIn('auth_alert_notified_at', saved)

    def test_telegram_hook_targets_only_administrators(self):
        targets = Mock(return_value=[{'telegram_token':'admin-bot', 'telegram_chat_id':'admin-chat'}])
        delivery = SimpleNamespace(send_message=Mock(return_value=SimpleNamespace(ok=True)))
        notify = load_function('notify_youtube_authorization_required',
            get_notification_targets=targets, telegram_notice=lambda *lines:'\n'.join(lines),
            telegram_escape=str, TELEGRAM_DELIVERY=delivery)
        self.assertTrue(notify({'channel_title':'Canal'}))
        targets.assert_called_once_with(None)
        args = delivery.send_message.call_args.args
        self.assertEqual(args[:2], ('admin-bot','admin-chat'))
        self.assertIn('Verificar e renovar', args[2])
        self.assertIn('Reconectar canal', args[2])


if __name__ == '__main__':
    unittest.main()
