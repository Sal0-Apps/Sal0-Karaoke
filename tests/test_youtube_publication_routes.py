"""Exercise real FastAPI dependencies: user publishing, admin-only management."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_publisher import install_routes


class PublicationRouteTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.user = {'username': 'alice', 'role': 'user'}
        self.app = FastAPI()
        def require_admin(user):
            if user['role'] != 'admin':
                raise HTTPException(403, 'admin only')
        self.publisher = install_routes(self.app, lambda: self.user, require_admin,
            lambda *args: Path(self.folder.name) / 'video.mp4', lambda name: None,
            lambda name: {'username': name, 'role': 'user'} if name == 'alice' else None)
        self.publisher.root = Path(self.folder.name)
        self.client = TestClient(self.app)

    def test_ordinary_user_cannot_manage_channel_or_other_results(self):
        for path in ('status', 'playlists', 'desktop-helper'):
            self.assertEqual(self.client.get('/api/admin/youtube/' + path).status_code, 403)
        for path in ('connect', 'settings', 'cover', 'jobs/id/retry'):
            self.assertEqual(self.client.post('/api/admin/youtube/' + path, json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/admin/youtube/publish', data={
            'owner_key': 'other', 'filename': 'video.mp4', 'title': 'Title'}).status_code, 403)

    def test_regular_user_cannot_import_authorization(self):
        response = self.client.post('/api/admin/youtube/import-authorization', files={'authorization': ('authorization.json', b'{}', 'application/json')})
        self.assertEqual(response.status_code, 403)

    def test_user_options_only_expose_assigned_playlist_without_secrets(self):
        self.publisher.save('token.json', {'refresh_token': 'secret', 'channel_id': 'channel', 'channel_title': 'Canal'})
        self.publisher.save('settings.json', {'users_can_publish': True, 'user_assignments': {
            'alice': {'enabled': True, 'playlist_id': 'playlist-one', 'playlist_title': 'Minha playlist', 'default_publish': True},
            'bob': {'enabled': True, 'playlist_id': 'playlist-other'}}})
        response = self.client.get('/api/youtube/publication-options')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result['default_publish'])
        self.assertEqual(result['playlists'], [{'id': 'playlist-one', 'title': 'Minha playlist'}])
        self.assertNotIn('secret', response.text)
        self.assertNotIn('playlist-other', response.text)

    def test_admin_saves_assignments_through_api(self):
        self.user['role'] = 'admin'
        with patch.object(self.publisher, 'playlists', return_value=[{'id': 'playlist-one', 'title': 'Minha playlist'}]), patch.object(self.publisher, 'token', return_value={}):
            response = self.client.post('/api/admin/youtube/settings', json={'privacy': 'unlisted',
                'users_can_publish': True, 'user_assignments': {
                    'alice': {'enabled': True, 'playlist_id': 'playlist-one', 'default_publish': True}}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.publisher.settings('admin')['user_assignments']['alice']['playlist_title'], 'Minha playlist')

    def test_callback_rejects_missing_state_without_credentials(self):
        response = self.client.get('/api/admin/youtube/callback?code=untrusted')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Não foi possível', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
