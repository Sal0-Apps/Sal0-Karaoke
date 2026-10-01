import ast
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from result_publication import record_result_kind
from youtube_publisher import YouTubePublisher, PublicationError, uploaded_offset, write_private_json


def response(code=200, data=None, headers=None):
    return SimpleNamespace(status_code=code, json=lambda: data or {}, headers=headers or {})


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.publisher = YouTubePublisher(self.folder.name)
        self.publisher.user_lookup = lambda username: {'username': username, 'role': 'user'} if username == 'alice' else None
        self.token = {'access_token': 'server-only-secret', 'refresh_token': 'server-only-refresh',
                      'channel_id': 'channel-one', 'channel_title': 'Canal', 'expires_at': time.time() + 3600}
        self.publisher.save('token.json', self.token)
        self.publisher.save('settings.json', {'defaults':{'playlist_id':'playlist-one'}})
        self.video = Path(self.folder.name) / 'song.mp4'
        self.video.write_bytes(b'mp4-video-fixture')
        record_result_kind(self.video, 'karaoke')
        self.cover = Path(self.folder.name) / 'cover.jpg'
        self.cover.write_bytes(b'\xff\xd8\xfftest')
        self.job = {'id': 'job', 'identity': 'identity', 'video': str(self.video), 'thumbnail': str(self.cover),
                    'title': 'Música', 'privacy': 'public', 'playlist_id': 'playlist-one', 'channel_id': 'channel-one',
                    'status': 'queued', 'progress': 0}
        self.publisher.save('jobs.json', [self.job])

    def test_partial_upload_range_and_no_bytes_yet(self):
        self.assertEqual(uploaded_offset(response(headers={})), 0)
        self.assertEqual(uploaded_offset(response(headers={'Range': 'bytes=0-1048575'})), 1048576)
        with self.assertRaises(PublicationError):
            uploaded_offset(response(headers={'Range': 'unexpected'}))

    def test_upload_starts_private_then_applies_cover_playlist_and_requested_privacy(self):
        calls = []
        def upload(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == 'POST' and url.endswith('/videos'):
                self.assertEqual(kwargs['json']['status']['privacyStatus'], 'private')
                return response(headers={'Location': 'https://www.googleapis.com/upload/session'})
            if method == 'PUT' and kwargs.get('headers', {}).get('Content-Range', '').startswith('bytes */'):
                return response(308)
            if method == 'PUT':
                self.assertEqual(kwargs['data'], b'mp4-video-fixture')
                return response(data={'id': 'abcdefghijk'})
            if url.endswith('/thumbnails/set'):
                self.assertEqual(self.job['video_id'], 'abcdefghijk')
                return response()
            raise AssertionError(url)
        def api(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if method == 'GET': return {'items': []}
            if path == '/playlistItems':
                self.assertTrue(self.job['thumbnail_done'])
                return {'id': 'playlist-item'}
            self.assertTrue(self.job['playlist_done'])
            self.assertEqual(kwargs['json']['status']['privacyStatus'], 'public')
            return {'status': {'privacyStatus': 'public'}}
        with patch.object(self.publisher, 'playlists', return_value=[{'id': 'playlist-one', 'title': 'Playlist'}]), patch.object(self.publisher, 'upload_request', side_effect=upload), patch.object(self.publisher, 'api', side_effect=api):
            self.publisher.publish(self.job)
        self.assertEqual(self.job['status'], 'done')
        self.assertEqual(self.job['actual_privacy'], 'public')
        self.assertEqual(calls[-1][1], '/videos')

    def test_completed_upload_retry_does_not_insert_another_video(self):
        self.job.update(video_id='abcdefghijk', thumbnail_done=True, playlist_done=True, status='error')
        with patch.object(self.publisher, 'upload_request') as upload, patch.object(self.publisher, 'api', return_value={'status': {'privacyStatus': 'public'}}):
            self.publisher.publish(self.job)
            upload.assert_not_called()
        self.assertEqual(self.job['status'], 'done')

    def test_existing_session_probes_for_uncertain_success_without_new_insert(self):
        self.job['upload_uri'] = 'https://www.googleapis.com/upload/session'
        with patch.object(self.publisher, 'upload_request', return_value=response(data={'id': 'abcdefghijk'})) as upload:
            self.assertEqual(self.publisher.upload_video(self.job), 'abcdefghijk')
            self.assertEqual(upload.call_count, 1)
            self.assertEqual(upload.call_args.args[0], 'PUT')

    def test_failed_thumbnail_keeps_video_private_and_never_applies_public_status(self):
        self.job['video_id'] = 'abcdefghijk'
        with patch.object(self.publisher, 'playlists', return_value=[{'id': 'playlist-one', 'title': 'Playlist'}]), patch.object(self.publisher, 'upload_request', return_value=response(403)), patch.object(self.publisher, 'api') as api:
            with self.assertRaises(PublicationError): self.publisher.publish(self.job)
            api.assert_not_called()
        self.assertNotEqual(self.job['status'], 'done')

    def test_wrong_channel_never_uploads(self):
        self.job['channel_id'] = 'different-channel'
        with patch.object(self.publisher, 'upload_request') as upload:
            with self.assertRaises(PublicationError): self.publisher.publish(self.job)
            upload.assert_not_called()

    def test_public_job_never_exposes_tokens_paths_or_upload_session(self):
        self.job.update(upload_uri='secret-session', refresh_token='secret')
        public = self.publisher.public_job(self.job)
        for key in ('video', 'thumbnail', 'upload_uri', 'refresh_token', 'identity'):
            self.assertNotIn(key, public)

    def configure_user(self, playlist='playlist-one', default=True):
        with patch.object(self.publisher, 'playlists', return_value=[{'id': 'playlist-one', 'title': 'Playlist'}]):
            self.publisher.save_settings('admin', {'privacy': 'private', 'users_can_publish': True,
                'title_template': '{title} | Karaokê', 'user_assignments': {
                    'alice': {'enabled': True, 'playlist_id': playlist, 'default_publish': default}}})

    def test_default_checked_never_uploads_without_explicit_request(self):
        self.configure_user()
        user = {'username': 'alice', 'role': 'user'}
        self.assertTrue(self.publisher.quick_options(user)['default_publish'])
        self.assertIsNone(self.publisher.publication_options(user, False))
        self.assertEqual(self.publisher.publication_options(user, True, 'playlist-one')['playlist_id'], 'playlist-one')

    def test_admin_publish_and_playlist_defaults_persist_with_unlisted_privacy(self):
        admin = {'username':'admin', 'role':'admin'}
        playlists = [{'id':'playlist-one', 'title':'Playlist'}]
        with patch.object(self.publisher, 'playlists', return_value=playlists):
            self.assertTrue(self.publisher.quick_options(admin)['default_publish'])
            self.publisher.save_settings('admin', {'privacy':'private', 'playlist_id':'playlist-one',
                'title_template':'{title}', 'default_publish':True})
            options = self.publisher.quick_options(admin)
            self.assertTrue(options['default_publish'])
            self.assertEqual(options['playlist_id'], 'playlist-one')
            self.assertEqual(options['privacy'], 'unlisted')
            self.assertIsNone(self.publisher.publication_options(admin, False))
            self.assertEqual(self.publisher.publication_options(admin, True, 'playlist-one')['privacy'], 'unlisted')
            self.publisher.save_settings('admin', {'privacy':'public', 'title_template':'{title}',
                'default_publish':False, 'playlist_id':''})
            restored = YouTubePublisher(self.folder.name)
            with patch.object(restored, 'playlists', return_value=playlists):
                self.assertFalse(restored.quick_options(admin)['default_publish'])
                self.assertEqual(restored.quick_options(admin)['playlist_id'], '')
                self.assertEqual(restored.quick_options(admin)['privacy'], 'unlisted')

    def test_old_privacy_defaults_migrate_to_unlisted_and_disconnected_never_preselects(self):
        self.publisher.save('settings.json', {'defaults':{'privacy':'private'}})
        with patch.object(self.publisher, 'playlists', return_value=[]):
            self.assertEqual(self.publisher.quick_options({'username':'admin','role':'admin'})['privacy'], 'unlisted')
        self.publisher.save('token.json', {})
        self.assertFalse(self.publisher.quick_options({'username':'admin','role':'admin'})['default_publish'])

    def test_all_users_preselect_publication_including_new_and_legacy_disabled_accounts(self):
        self.publisher.save('settings.json', {'users_can_publish':False, 'user_assignments':{
            'alice':{'enabled':False, 'default_publish':False, 'playlist_id':'playlist-one'}}})
        alice = {'username':'alice', 'role':'user'}
        self.assertTrue(self.publisher.quick_options(alice)['default_publish'])
        self.assertEqual(self.publisher.publication_options(alice, True, 'playlist-one')['privacy'], 'unlisted')
        bob = {'username':'bob', 'role':'user'}
        self.assertFalse(self.publisher.quick_options(bob)['default_publish'])
        self.assertEqual(self.publisher.quick_options(bob)['playlist_id'], '')
        self.assertIsNone(self.publisher.publication_options(bob, False))
        with self.assertRaises(PublicationError): self.publisher.publication_options(bob, True)

    def test_admin_uses_profile_playlist_by_default_and_can_override_per_video(self):
        admin = {'username':'admin', 'role':'admin'}
        self.assertEqual(self.publisher.publication_options(admin, True)['playlist_id'], 'playlist-one')
        alternate = self.publisher.publication_options(admin, True, 'playlist-two')
        self.assertEqual(alternate['playlist_id'], 'playlist-two')
        with patch.object(self.publisher, 'start'):
            queued = self.publisher.enqueue(self.video, 'Title', playlist_id=alternate['playlist_id'], thumbnail=self.cover.read_bytes(), requester=admin)
        self.assertEqual(queued['playlist_id'], 'playlist-two')
        self.assertEqual(self.publisher.settings('admin')['playlist_id'], 'playlist-one')
        self.publisher.save('settings.json', {})
        with self.assertRaises(PublicationError): self.publisher.publication_options(admin, True, 'playlist-two')
        with patch.object(self.publisher, 'upload_video') as upload:
            with self.assertRaises(PublicationError): self.publisher.publish(self.job)
            upload.assert_not_called()
        with self.assertRaises(PublicationError): self.publisher.enqueue(self.video, 'Title', playlist_id='playlist-two')

    def test_legacy_job_without_playlist_never_uploads(self):
        self.job['playlist_id'] = ''
        with patch.object(self.publisher, 'upload_video') as upload:
            with self.assertRaises(PublicationError): self.publisher.publish(self.job)
            upload.assert_not_called()

    def test_user_can_only_publish_to_own_assigned_playlist(self):
        self.configure_user()
        user = {'username': 'alice', 'role': 'user'}
        for playlist in ('other-playlist',):
            with self.assertRaises(PublicationError): self.publisher.publication_options(user, True, playlist)
        with self.assertRaises(PublicationError):
            self.publisher.publication_options({'username': 'bob', 'role': 'user'}, True, 'playlist-one')

    def test_missing_profile_playlist_blocks_publication(self):
        self.configure_user('', False)
        user = {'username': 'alice', 'role': 'user'}
        options = self.publisher.quick_options(user)
        self.assertTrue(options['enabled'])
        self.assertFalse(options['allow_no_playlist'])
        self.assertFalse(options['default_publish'])
        with self.assertRaises(PublicationError): self.publisher.publication_options(user, True)

    def test_revoking_assignment_blocks_queued_job_before_upload(self):
        self.configure_user()
        self.job['requester'] = {'username': 'alice', 'role': 'user'}
        self.publisher.save('settings.json', {})
        with patch.object(self.publisher, 'upload_video') as upload:
            with self.assertRaises(PublicationError): self.publisher.publish(self.job)
            upload.assert_not_called()

    def test_invalid_assignment_is_rejected_without_changing_settings(self):
        self.configure_user()
        original = self.publisher.read('settings.json')
        with patch.object(self.publisher, 'playlists', return_value=[]):
            with self.assertRaises(PublicationError):
                self.publisher.save_settings('admin', {'privacy': 'private', 'users_can_publish': True,
                    'user_assignments': {'alice': {'enabled': True, 'playlist_id': 'another-channel'}}})
        self.assertEqual(self.publisher.read('settings.json'), original)

    def test_client_secret_and_token_files_are_private(self):
        path = Path(self.folder.name) / 'token.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_oauth_state_is_one_time_and_checks_current_admin_role(self):
        self.publisher.oauth_states['state'] = {'expires': time.time() + 60, 'username': 'admin', 'verifier': 'pkce'}
        checker = Mock(side_effect=PublicationError('not admin'))
        with patch('youtube_publisher.requests.post') as post:
            with self.assertRaises(PublicationError): self.publisher.finish_authorization('state', 'code', checker)
            post.assert_not_called()
        self.assertNotIn('state', self.publisher.oauth_states)
        checker.assert_called_once_with('admin')

    def test_session_url_cannot_send_access_token_to_another_host(self):
        with patch('youtube_publisher.requests.request') as request:
            with self.assertRaises(PublicationError): self.publisher.upload_request('PUT', 'https://attacker.example/upload')
            request.assert_not_called()

    def test_duplicate_media_copies_reuse_one_publication(self):
        self.publisher.save('jobs.json', [])
        other = Path(self.folder.name) / 'copy.mp4'; other.write_bytes(self.video.read_bytes()); record_result_kind(other, 'karaoke')
        with patch.object(self.publisher, 'start'):
            first = self.publisher.enqueue(self.video, 'Primeira', thumbnail=self.cover.read_bytes())
            second = self.publisher.enqueue(other, 'Segunda', thumbnail=self.cover.read_bytes())
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.publisher.read('jobs.json', [])), 1)

    def test_identical_media_with_distinct_user_or_playlist_has_distinct_publication(self):
        self.publisher.save('jobs.json', [])
        with patch.object(self.publisher, 'start'):
            first = self.publisher.enqueue(self.video, 'Title', playlist_id='playlist-one', thumbnail=self.cover.read_bytes(), requester={'username': 'alice', 'role':'admin'})
            second = self.publisher.enqueue(self.video, 'Title', playlist_id='playlist-two', thumbnail=self.cover.read_bytes(), requester={'username': 'alice', 'role':'admin'})
            third = self.publisher.enqueue(self.video, 'Title', playlist_id='playlist-one', thumbnail=self.cover.read_bytes(), requester={'username': 'bob', 'role':'admin'})
        self.assertEqual(len({first['id'], second['id'], third['id']}), 3)

    def test_title_privacy_and_playlist_are_validated_before_enqueue(self):
        for title, privacy in [('', 'private'), ('x' * 101, 'private'), ('A < B', 'private'), ('Música', 'invalid')]:
            with self.assertRaises(PublicationError): self.publisher.enqueue(self.video, title, privacy)
        with patch.object(self.publisher, 'playlists', return_value=[]):
            with self.assertRaises(PublicationError): self.publisher.enqueue(self.video, 'Música', playlist_id='../invalid')

    def test_resolver_rejects_traversal_and_symlinks_outside_history(self):
        tree = ast.parse((ROOT / 'app/main.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'resolve_youtube_publication_video')
        class HttpError(Exception):
            def __init__(self, **kwargs): pass
        history = Path(self.folder.name) / 'library/history'; history.mkdir(parents=True)
        (history / 'outside.mp4').symlink_to(self.video)
        scope = {'os': os, 'Path': Path, 'HTTPException': HttpError, 'admin_result_owner': lambda *args: {},
                 'get_user_paths': lambda _: {'library': str(history.parent)}}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        for filename in ('../song.mp4', 'outside.mp4', 'file.srt'):
            with self.assertRaises(HttpError): scope['resolve_youtube_publication_video']('__admin__', filename, {})


if __name__ == '__main__': unittest.main()
