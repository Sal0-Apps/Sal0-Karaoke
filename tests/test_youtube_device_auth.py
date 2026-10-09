"""Phone consent for the headless server, including resumable Google replies."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_device_auth import DeviceAuthorization, AuthorizationError, DEVICE_SCOPE
from youtube_publisher import write_private_json


def reply(data, code=200):
    return SimpleNamespace(status_code=code, json=lambda: data)


class DeviceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = 1000
        self.clock = patch('youtube_device_auth.time.time', side_effect=lambda: self.now)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.finish = Mock(return_value='Meu canal')
        self.device = DeviceAuthorization(self.folder.name, write_private_json, self.finish)
        self.credentials = {'client_id': 'device-client', 'client_secret': 'private-secret'}
        self.code = {'device_code': 'private-code', 'user_code': 'ABCD-EFGH',
            'verification_url': 'https://www.google.com/device', 'expires_in': 1800, 'interval': 5}

    def start(self, username='owner'):
        with patch('youtube_device_auth.requests.post', return_value=reply(self.code)) as post:
            result = self.device.start(username, self.credentials)
            self.assertEqual(post.call_args.kwargs['data']['scope'], DEVICE_SCOPE)
        return result

    def test_configuration_and_status_never_return_private_credentials(self):
        session = self.start()
        self.assertTrue(self.device.configured())
        public = json.dumps(self.device.status('owner'))
        for secret in ('private-secret', 'private-code', 'client_secret', 'device_code'):
            self.assertNotIn(secret, public)
        self.assertEqual(session['user_code'], 'ABCD-EFGH')
        for name in ('device_client.json', 'device_sessions.json'):
            self.assertEqual((Path(self.folder.name) / name).stat().st_mode & 0o777, 0o600)

    def test_poll_honors_interval_and_never_replays_an_approved_grant(self):
        session = self.start()
        token = {'access_token': 'private-access', 'refresh_token': 'private-refresh', 'scope': DEVICE_SCOPE}
        with patch('youtube_device_auth.requests.post', return_value=reply(token)) as post:
            self.assertEqual(self.device.poll('owner', session['session_id'])['status'], 'pending')
            post.assert_not_called()
            self.now += 5
            result = self.device.poll('owner', session['session_id'])
            self.assertEqual(result['status'], 'connected')
            self.device.poll('owner', session['session_id'])
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs['data']['grant_type'], 'urn:ietf:params:oauth:grant-type:device_code')
        self.finish.assert_called_once_with(token, self.credentials)
        contents = (Path(self.folder.name) / 'device_sessions.json').read_text()
        for secret in ('private-code', 'private-secret', 'private-access', 'private-refresh'):
            self.assertNotIn(secret, contents)

    def test_pending_and_slow_down_keep_code_and_follow_google_interval(self):
        session = self.start(); self.now += 5
        with patch('youtube_device_auth.requests.post', side_effect=[reply({'error':'authorization_pending'},428), reply({'error':'slow_down'},403)]) as post:
            self.assertEqual(self.device.poll('owner', session['session_id'])['status'], 'pending')
            self.now += 5
            self.assertEqual(self.device.poll('owner', session['session_id'])['interval'], 10)
            self.now += 5; self.device.poll('owner', session['session_id'])
            self.assertEqual(post.call_count, 2)

    def test_device_code_is_bound_to_admin_and_latest_attempt(self):
        old = self.start(); new = self.start()
        for username, nonce in [('other', new['session_id']), ('owner', old['session_id']), ('owner', '')]:
            with self.assertRaises(AuthorizationError): self.device.poll(username, nonce)
        with self.assertRaises(AuthorizationError): self.device.cancel('owner', old['session_id'])
        self.assertEqual(self.device.status('owner')['session_id'], new['session_id'])
        self.device.cancel('owner', new['session_id'])
        self.assertIsNone(self.device.status('owner'))

    def test_expired_and_denied_codes_show_a_recovery_action(self):
        session = self.start(); self.now += 1801
        with patch('youtube_device_auth.requests.post') as post:
            self.assertEqual(self.device.poll('owner', session['session_id'])['status'], 'expired')
            post.assert_not_called()
        session = self.start(); self.now += 5
        with patch('youtube_device_auth.requests.post', return_value=reply({'error':'access_denied'},403)):
            result = self.device.poll('owner', session['session_id'])
        self.assertEqual(result['status'], 'error'); self.assertEqual(result['recovery'], 'auth_required')

    def test_wrong_client_type_cannot_replace_working_credentials(self):
        self.start()
        with patch('youtube_device_auth.requests.post', return_value=reply({'error':'invalid_client'},401)):
            with self.assertRaises(AuthorizationError) as caught:
                self.device.start('owner', {'client_id':'desktop-client', 'client_secret':'wrong-secret'})
        self.assertEqual(caught.exception.kind, 'configure_client')
        self.assertEqual(self.device.read('device_client.json'), self.credentials)

    def test_untrusted_google_uri_and_malformed_payload_are_rejected(self):
        for payload in ({**self.code,'verification_url':'https://google.com.attacker.example/device'}, [], {**self.code,'interval':'invalid'}, {**self.code,'device_code':None}):
            with patch('youtube_device_auth.requests.post', return_value=reply(payload)):
                with self.assertRaises(AuthorizationError): self.device.start('owner', self.credentials)
        self.assertFalse(self.device.configured())

    def test_granted_token_survives_channel_network_failure_and_server_restart(self):
        import requests
        session = self.start(); self.now += 5
        self.finish.side_effect = requests.ConnectionError('offline')
        token = {'access_token':'private-access','refresh_token':'private-refresh','scope':DEVICE_SCOPE}
        with patch('youtube_device_auth.requests.post', return_value=reply(token)) as post:
            result = self.device.poll('owner', session['session_id'])
            self.assertEqual(result['status'], 'pending')
            self.assertNotIn('private-access', json.dumps(result))
            post.assert_called_once()
        restarted = DeviceAuthorization(self.folder.name, write_private_json, Mock(return_value='Meu canal'))
        self.now += 1900  # The Google code may expire after it has been approved.
        with patch('youtube_device_auth.requests.post') as post:
            self.assertEqual(restarted.poll('owner', session['session_id'])['status'], 'connected')
            post.assert_not_called()

    def test_starting_another_admin_session_preserves_existing_code(self):
        first = self.start('first'); second = self.start('second')
        self.assertEqual(self.device.status('first')['session_id'], first['session_id'])
        self.assertEqual(self.device.status('second')['session_id'], second['session_id'])
        self.device.cancel('second', second['session_id'])
        self.assertIsNotNone(self.device.status('first'))
