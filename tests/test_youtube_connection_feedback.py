import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_publisher import YouTubePublisher, PublicationError, SCOPE

def reply(data, code=200):
    return SimpleNamespace(status_code=code, json=lambda: data)

class ConnectionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.publisher = YouTubePublisher(self.folder.name)
        self.data = {'format':'sal0-youtube-desktop-v1','client_id':'client','client_secret':'secret','refresh_token':'refresh'}
    def test_refresh_without_scope_is_verified_with_google_before_saving(self):
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token':'access'})), patch('youtube_publisher.requests.get', side_effect=[
            reply({'scope':SCOPE}), reply({'items':[{'id':'channel','snippet':{'title':'My channel'}}]})]) as request:
            self.assertEqual(self.publisher.import_desktop_authorization(self.data), 'My channel')
            self.assertEqual(request.call_args_list[0].args[0], 'https://oauth2.googleapis.com/tokeninfo')
        self.assertEqual(self.publisher.read('token.json')['channel_id'], 'channel')
    def test_missing_scope_never_bypasses_permission_check(self):
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token':'access'})), patch('youtube_publisher.requests.get', return_value=reply({'scope':'openid'})) as request:
            with self.assertRaises(PublicationError): self.publisher.import_desktop_authorization(self.data)
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.publisher.read('token.json'), {})
    def test_disabled_api_returns_actionable_message_and_preserves_existing_connection(self):
        self.publisher.save('token.json', {'channel_id':'previous'})
        with patch('youtube_publisher.requests.post', return_value=reply({'access_token':'access','scope':SCOPE})), patch('youtube_publisher.requests.get', return_value=reply({'error':{'errors':[{'reason':'accessNotConfigured'}]}},403)):
            with self.assertRaisesRegex(PublicationError, 'Ative a YouTube Data API v3'): self.publisher.import_desktop_authorization(self.data)
        self.assertEqual(self.publisher.read('token.json')['channel_id'], 'previous')
