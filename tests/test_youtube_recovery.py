"""Expired credentials must be visible and recoverable without losing uploads."""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_publisher import install_routes


def reply(data, code=200, headers=None):
    return SimpleNamespace(status_code=code, json=lambda: data, headers=headers or {})


class YouTubeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        app = FastAPI()
        self.publisher = install_routes(app, lambda: {'username': 'owner', 'role': 'admin'},
            lambda user: None, lambda *args: None, lambda name: None)
        self.publisher.root = Path(self.folder.name)
        self.client = TestClient(app)
        self.token = dict(access_token='old-access', refresh_token='private-refresh',
            channel_id='channel', channel_title='Meu canal', expires_at=time.time() - 5,
            desktop_client={'client_id': 'client', 'client_secret': 'private-client-secret'})
        self.publisher.save('token.json', self.token)

    def test_status_is_not_connected_when_refresh_permission_was_revoked(self):
        with patch('youtube_publisher.requests.post', return_value=reply({'error': 'invalid_grant'}, 400)):
            response = self.client.get('/api/admin/youtube/status')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['connected'])
        self.assertNotIn('private-refresh', response.text)


if __name__ == '__main__':
    unittest.main()

class ConnectionLifecycleTests(YouTubeRecoveryTests):
    def test_revocation_is_cached_but_verify_can_force_a_real_renewal(self):
        with patch('youtube_publisher.requests.post', return_value=reply({'error':'invalid_grant'},400)) as post:
            for _ in range(3):
                self.assertFalse(self.client.get('/api/admin/youtube/status').json()['connected'])
            self.assertEqual(post.call_count, 1)
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token':'new-access','expires_in':3600})), patch.object(self.publisher, 'confirm_channel', return_value={'id':'channel','snippet':{'title':'Meu canal'}}):
            result = self.client.post('/api/admin/youtube/verify-connection').json()
        self.assertTrue(result['connected']); self.assertNotIn('auth_error', self.publisher.read('token.json'))

    def test_network_failure_preserves_grant_and_does_not_loop_on_status(self):
        import requests
        with patch('youtube_publisher.requests.post', side_effect=requests.ConnectionError('private-server-details')) as post:
            result = self.client.get('/api/admin/youtube/status')
            self.client.get('/api/admin/youtube/status')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result.json()['connection_state'], 'network_error')
        self.assertNotIn('private-server-details', result.text)
        saved = self.publisher.read('token.json')
        self.assertEqual(saved['refresh_token'], 'private-refresh'); self.assertNotIn('auth_error', saved)

    def test_early_401_refreshes_once_and_rewinds_thumbnail_body(self):
        import io
        self.token['expires_at'] = time.time() + 3600; self.publisher.save('token.json', self.token)
        body = io.BytesIO(b'image-bytes')
        def consume(*args, **kwargs):
            self.assertEqual(kwargs['data'].read(), b'image-bytes')
            return reply({}, 401 if consume.calls == 0 else 200)
        consume.calls = 0
        def request(*args, **kwargs):
            result = consume(*args, **kwargs); consume.calls += 1; return result
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token':'new-access'})) as refresh, patch('youtube_publisher.requests.request', side_effect=request):
            response = self.publisher.upload_request('POST','https://www.googleapis.com/upload/youtube/v3/thumbnails/set',data=body)
        self.assertEqual(response.status_code, 200); self.assertEqual(consume.calls,2); refresh.assert_called_once()

    def test_repeated_401_requires_consent_and_is_visible_on_status(self):
        from youtube_publisher import PublicationError
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token':'new-access'})), patch('youtube_publisher.requests.request', return_value=reply({},401)) as request:
            with self.assertRaises(PublicationError) as caught: self.publisher.api('GET','/playlists')
        self.assertEqual(caught.exception.kind,'auth_required'); self.assertEqual(request.call_count,2)
        self.assertFalse(self.client.get('/api/admin/youtube/status').json()['connected'])

    def test_channel_401_after_renewal_is_not_reported_connected_later(self):
        with patch('youtube_publisher.requests.post',return_value=reply({'access_token':'new-access'})), patch('youtube_publisher.requests.get',return_value=reply({},401)):
            self.assertFalse(self.client.post('/api/admin/youtube/verify-connection').json()['connected'])
        self.assertFalse(self.client.get('/api/admin/youtube/status').json()['connected'])

    def test_channel_network_failure_preserves_the_freshly_rotated_refresh_token(self):
        import requests
        with patch('youtube_publisher.requests.post',return_value=reply({'access_token':'new-access','refresh_token':'new-refresh'})), patch('youtube_publisher.requests.get',side_effect=requests.ConnectionError('offline')):
            response = self.client.post('/api/admin/youtube/verify-connection').json()
        self.assertEqual(response['connection_state'],'network_error')
        self.assertEqual(self.publisher.read('token.json')['refresh_token'],'new-refresh')

    def test_same_channel_renewal_resumes_only_authorization_jobs_without_duplicates(self):
        jobs = [dict(id='one',status='auth_required',channel_id='channel',video_id='abcdefghijk',upload_uri='private-session',progress=92),
                dict(id='two',status='queued',channel_id='channel'),
                dict(id='three',status='finalizing',channel_id='channel'),
                dict(id='four',status='error',channel_id='channel')]
        self.publisher.save('jobs.json',jobs)
        self.publisher.save('settings.json',{'defaults':{'playlist_id':'playlist'}})
        with patch.object(self.publisher,'start') as start: self.publisher.save_authorization(dict(self.token,access_token='new-access'))
        saved = self.publisher.read('jobs.json',[])
        self.assertEqual(saved[0]['status'],'queued'); self.assertEqual(saved[0]['video_id'],'abcdefghijk')
        self.assertEqual(saved[0]['upload_uri'],'private-session'); self.assertEqual(saved[0]['progress'],92)
        self.assertEqual(saved[3]['status'],'error'); start.assert_called_once()
        self.assertEqual(self.publisher.read('settings.json')['defaults']['playlist_id'],'playlist')

    def test_pending_upload_to_another_channel_blocks_account_switch(self):
        from youtube_publisher import PublicationError
        for status in ('queued','uploading','finalizing','auth_required'):
            self.publisher.save('jobs.json',[dict(id='one',status=status,channel_id='other-channel')])
            with self.assertRaises(PublicationError): self.publisher.save_authorization(self.token)
        self.assertEqual(self.publisher.read('token.json')['refresh_token'],'private-refresh')

    def test_worker_pauses_expired_jobs_and_keeps_resumable_session(self):
        from youtube_publisher import PublicationError
        self.publisher.save('jobs.json',[dict(id='one',status='queued',channel_id='channel',upload_uri='private-session')])
        with patch.object(self.publisher,'publish',side_effect=PublicationError('Reconecte o canal.','auth_required')):
            self.publisher.work()
        job = self.publisher.read('jobs.json',[])[0]
        self.assertEqual(job['status'],'auth_required'); self.assertEqual(job['upload_uri'],'private-session')

    def test_approved_grant_is_refreshed_if_channel_confirmation_was_delayed(self):
        from youtube_device_auth import DEVICE_SCOPE
        candidate = {'access_token':'old-candidate','refresh_token':'candidate-refresh','scope':DEVICE_SCOPE,'expires_at':time.time()-10}
        with patch('youtube_publisher.requests.post',return_value=reply({'access_token':'new-candidate'})) as refresh, patch.object(self.publisher,'confirm_channel',return_value={'id':'channel','snippet':{'title':'Meu canal'}}) as channel:
            self.publisher.accept_device_token(candidate,{'client_id':'tv-client','client_secret':'secret'})
        refresh.assert_called_once();channel.assert_called_once_with('new-candidate')
        self.assertGreater(self.publisher.read('token.json')['expires_at'],time.time())

    def test_forced_verification_resumes_authorization_jobs_after_successful_refresh(self):
        self.publisher.save('jobs.json',[dict(id='one',status='auth_required',channel_id='channel',video_id='abcdefghijk')])
        with patch('youtube_publisher.requests.post',return_value=reply({'access_token':'renewed'})), patch.object(self.publisher,'confirm_channel',return_value={'id':'channel','snippet':{'title':'Meu canal'}}), patch.object(self.publisher,'start') as start:
            self.assertTrue(self.client.post('/api/admin/youtube/verify-connection').json()['connected'])
        self.assertEqual(self.publisher.read('jobs.json',[])[0]['status'],'queued');start.assert_called_once()

    def test_device_routes_are_admin_only_and_do_not_leak_private_config(self):
        from fastapi import HTTPException
        app = FastAPI()
        def require_admin(user):
            if user['role'] != 'admin': raise HTTPException(403,'Somente administrador.')
        install_routes(app,lambda:{'username':'guest','role':'user'},require_admin,lambda *args:None,lambda name:None)
        client = TestClient(app)
        for path in ('device/start','device/poll','device/cancel','verify-connection'):
            self.assertEqual(client.post('/api/admin/youtube/'+path,json={}).status_code,403)

    def test_device_code_grant_connects_channel_and_can_be_renewed_on_server(self):
        from youtube_device_auth import DEVICE_SCOPE
        credentials = {'client_id':'tv-client','client_secret':'private-secret'}
        code = {'device_code':'private-code','user_code':'ABCD-EFGH','verification_url':'https://www.google.com/device','interval':5}
        with patch('youtube_device_auth.requests.post',return_value=reply(code)):
            response = self.client.post('/api/admin/youtube/device/start',json={'credentials':credentials})
        self.assertEqual(response.status_code,200)
        with patch('youtube_device_auth.time.time',return_value=time.time()+10), patch('youtube_device_auth.requests.post',return_value=reply({'access_token':'private-access','refresh_token':'private-refresh','scope':DEVICE_SCOPE})), patch.object(self.publisher,'confirm_channel',return_value={'id':'channel','snippet':{'title':'Meu canal'}}):
            completed = self.client.post('/api/admin/youtube/device/poll',json={'session_id':response.json()['session_id']})
        self.assertEqual(completed.json()['status'],'connected')
        for secret in ('private-access','private-refresh','private-secret','private-code'):
            self.assertNotIn(secret,completed.text)
        self.assertEqual(self.publisher.read('token.json')['oauth_client'],credentials)
