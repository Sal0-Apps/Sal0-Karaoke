import http.client
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_desktop_oauth import obtain_authorization, save_authorization
from youtube_publisher import YouTubePublisher, PublicationError, SCOPE


def reply(data, code=200):
    return SimpleNamespace(status_code=code, json=lambda: data)


class DesktopAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.publisher = YouTubePublisher(self.folder.name)
        self.authorization = {'format': 'sal0-youtube-desktop-v1', 'client_id': 'desktop-client', 'client_secret': 'private-client', 'refresh_token': 'private-refresh'}

    def test_desktop_loopback_callback_uses_state_pkce_and_fixed_https_token_endpoint(self):
        observed = {}
        def browser(url):
            values = parse_qs(urlparse(url).query)
            redirect = urlparse(values['redirect_uri'][0])
            self.assertEqual(redirect.hostname, '127.0.0.1')
            self.assertEqual(redirect.scheme, 'http')
            self.assertEqual(values['code_challenge_method'], ['S256'])
            observed['challenge'] = values['code_challenge'][0]
            # Run HTTP requests concurrently with the local listener.
            import threading
            def callback():
                connection = http.client.HTTPConnection(redirect.hostname, redirect.port, timeout=3)
                connection.request('GET', '/callback?state=wrong&code=attacker')
                invalid = connection.getresponse(); observed['rejected'] = invalid.status; invalid.read(); connection.close()
                connection = http.client.HTTPConnection(redirect.hostname, redirect.port, timeout=3)
                connection.request('GET', '/callback?state=' + values['state'][0] + '&code=valid-code')
                valid = connection.getresponse(); observed['body'] = valid.read(); connection.close()
            thread = threading.Thread(target=callback); thread.start(); observed['thread'] = thread
            return True
        def token(request, timeout):
            import hashlib, base64
            self.assertEqual(request.full_url, 'https://oauth2.googleapis.com/token')
            values = parse_qs(request.data.decode())
            self.assertEqual(values['code'], ['valid-code'])
            self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(values['code_verifier'][0].encode()).digest()).decode().rstrip('='), observed['challenge'])
            return io.BytesIO(json.dumps({'refresh_token': 'private-refresh'}).encode())
        with patch('youtube_desktop_oauth.urllib.request.urlopen', side_effect=token):
            result = obtain_authorization(self.authorization, opener=browser, timeout=5)
        observed['thread'].join(3)
        self.assertEqual(observed['rejected'], 400)
        self.assertNotIn(b'valid-code', observed['body'])
        self.assertEqual(result['format'], 'sal0-youtube-desktop-v1')
        self.assertNotIn('access_token', result)

    def test_import_validates_channel_and_scope_instead_of_trusting_uploaded_identity(self):
        self.authorization['channel_id'] = 'forged-channel'
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token': 'access', 'scope': SCOPE, 'expires_in': 3600})), patch('youtube_publisher.requests.get', return_value=reply({'items': [{'id': 'verified-channel', 'snippet': {'title': 'Canal'}}]})):
            self.assertEqual(self.publisher.import_desktop_authorization(self.authorization), 'Canal')
        saved = self.publisher.read('token.json')
        self.assertEqual(saved['channel_id'], 'verified-channel')
        self.assertEqual(saved['desktop_client']['client_id'], 'desktop-client')
        self.assertEqual((Path(self.folder.name) / 'token.json').stat().st_mode & 0o777, 0o600)

    def test_import_without_required_scope_preserves_existing_connection(self):
        self.publisher.save('token.json', {'channel_id': 'previous'})
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token': 'access', 'scope': 'openid'})), patch('youtube_publisher.requests.get') as channel:
            with self.assertRaises(PublicationError): self.publisher.import_desktop_authorization(self.authorization)
            channel.assert_not_called()
        self.assertEqual(self.publisher.read('token.json')['channel_id'], 'previous')

    def test_desktop_refresh_works_without_https_web_oauth_configuration(self):
        self.publisher.save('token.json', {'refresh_token': 'refresh', 'channel_id': 'channel', 'expires_at': 0,
            'desktop_client': {'client_id': 'desktop-client', 'client_secret': 'secret'}})
        with patch.object(self.publisher, 'client_config', side_effect=AssertionError('Must not use web callback')), patch('youtube_publisher.requests.post', return_value=reply({'access_token': 'new', 'expires_in': 3600})) as refresh:
            self.assertEqual(self.publisher.token()['access_token'], 'new')
            self.assertNotIn('redirect_uri', refresh.call_args.kwargs['data'])
            self.assertEqual(refresh.call_args.kwargs['data']['client_id'], 'desktop-client')

    def test_export_file_is_private_and_invalid_import_never_requests_google(self):
        output = Path(self.folder.name) / 'authorization.json'
        save_authorization(output, self.authorization)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with patch('youtube_publisher.requests.post') as request:
            with self.assertRaises(PublicationError): self.publisher.import_desktop_authorization({'format': 'wrong'})
            request.assert_not_called()
