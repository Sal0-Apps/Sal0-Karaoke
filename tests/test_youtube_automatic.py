import ast
import json
import logging
from pathlib import Path
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from youtube_publisher import YouTubePublisher
from result_publication import record_result_kind


class AutomaticPublicationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.publisher = YouTubePublisher(self.root / 'youtube')
        self.publisher.start = Mock()
        self.user = dict(username='alice', role='user')
        self.publisher.user_lookup = lambda name: self.user if name == 'alice' else None
        self.publisher.save('token.json', dict(channel_id='channel', refresh_token='refresh', access_token='access', expires_at=time.time()+3600))
        self.publisher.save('settings.json', dict(defaults=dict(playlist_id='PL-admin'), user_assignments={
            'alice': dict(playlist_id='PL-alice')}))
        self.video = self.root / 'result.mp4'
        self.video.write_bytes(b'completed karaoke video')
        record_result_kind(self.video, 'karaoke')
        self.cover = self.root / 'cover.jpg'
        self.cover.write_bytes(b'\xff\xd8\xffcover')

    def test_omitted_choice_uses_assigned_default_but_false_remains_an_opt_out(self):
        options = self.publisher.publication_options(self.user, None)
        self.assertEqual(options['playlist_id'], 'PL-alice')
        self.assertIsNone(self.publisher.publication_options(self.user, False))
        self.publisher.save('token.json', {})
        self.assertIsNone(self.publisher.publication_options(self.user, None))

    def test_pending_ui_cannot_assign_another_accounts_playlist(self):
        self.publisher.save('settings.json', dict(defaults=dict(playlist_id='PL-admin')))
        self.assertIsNone(self.publisher.publication_options(self.user, None))

    def test_old_clients_omitting_checkbox_keep_opt_out_unless_default_explicitly_requested(self):
        main = Path(__file__).parents[1] / 'app' / 'main.py'
        function = next(node for node in ast.parse(main.read_text(encoding='utf-8')).body
                        if isinstance(node, ast.FunctionDef) and node.name == 'process_karaoke')
        call = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == 'publication_options')
        expression = ast.Expression(body=call)
        for use_default, requested, enabled in [(False, False, False), (True, False, True), (False, True, True)]:
            scope = dict(youtube_publisher=self.publisher, current_user=self.user,
                         youtube_publish=requested, youtube_use_profile_default=use_default,
                         youtube_playlist_id='', youtube_title='', youtube_extra_playlists=False, additional=[])
            result = eval(compile(expression, str(main), 'eval'), scope)
            self.assertEqual(bool(result), enabled)

    def test_automatic_intent_is_durable_before_cover_or_live_playlist_requests(self):
        options = self.publisher.publication_options(self.user, True)
        options['additional_playlists'] = ['PL-extra']
        with patch('youtube_publisher.video_thumbnail', side_effect=RuntimeError('not available yet')) as thumbnail, \
                patch.object(self.publisher, 'playlists', side_effect=RuntimeError('offline')):
            self.publisher.enqueue_automatic(self.video, 'Música', options)
            self.publisher.enqueue_automatic(self.video, 'Música', options)
        thumbnail.assert_not_called()
        jobs = self.publisher.read('jobs.json', [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['status'], 'queued')
        self.assertTrue(jobs[0]['automatic'])
        self.assertEqual(jobs[0]['playlist_ids'], ['PL-alice', 'PL-extra'])
        self.publisher.start.assert_called()

    def test_worker_finishes_automatic_publication_without_a_manual_request(self):
        options = self.publisher.publication_options(self.user, True)
        self.publisher.enqueue_automatic(self.video, 'Música', options)
        def api(method, path, **kwargs):
            if path == '/playlistItems':
                return {'items': []} if method == 'GET' else {'id': 'added'}
            return {'status': {'privacyStatus': 'unlisted'}}
        with patch('youtube_publisher.video_thumbnail', return_value=self.cover), \
                patch.object(self.publisher, 'playlists', return_value=[dict(id='PL-alice')]), \
                patch.object(self.publisher, 'upload_video', return_value='abcdefghijk'), \
                patch.object(self.publisher, 'upload_request', return_value=Mock(status_code=200)), \
                patch.object(self.publisher, 'api', side_effect=api):
            self.publisher.work()
        job = self.publisher.read('jobs.json', [])[0]
        self.assertEqual(job['status'], 'done')
        self.assertTrue(job['thumbnail_done'])
        self.assertEqual(job['actual_privacy'], 'unlisted')

    def test_bad_cover_remains_retryable_and_does_not_start_an_upload(self):
        self.publisher.enqueue_automatic(self.video, 'Música', self.publisher.publication_options(self.user, True))
        with patch.object(self.publisher, 'playlists', return_value=[dict(id='PL-alice')]), \
                patch('youtube_publisher.video_thumbnail', side_effect=RuntimeError('ffmpeg failed')), \
                patch.object(self.publisher, 'upload_video') as upload:
            self.publisher.work()
        upload.assert_not_called()
        job = self.publisher.read('jobs.json', [])[0]
        self.assertEqual(job['status'], 'error')
        self.assertIn('capa', job['error'])
        self.publisher.retry(job['id'])
        self.assertEqual(self.publisher.read('jobs.json', [])[0]['status'], 'queued')

    def test_source_title_with_google_forbidden_characters_can_publish_automatically(self):
        self.publisher.enqueue_automatic(self.video, 'Artista <Ao vivo>\nMúsica',
                                         self.publisher.publication_options(self.user, True))
        title = self.publisher.read('jobs.json', [])[0]['title']
        self.assertNotIn('<', title); self.assertNotIn('>', title); self.assertNotIn('\n', title)

    def test_both_pipeline_completion_paths_enqueue_the_saved_history_result(self):
        main = Path(__file__).parents[1] / 'app' / 'main.py'
        tree = ast.parse(main.read_text(encoding='utf-8'))
        pipeline = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_pipeline')
        blocks = [n for n in ast.walk(pipeline) if isinstance(n, ast.If)
                  and isinstance(n.test, ast.Name) and n.test.id == 'youtube_publish_options']
        self.assertEqual(len(blocks), 2)
        options = self.publisher.publication_options(self.user, True)
        for block in blocks:
            self.publisher.save('jobs.json', [])
            history = self.root / 'history'; history.mkdir(exist_ok=True)
            destination = history / 'song.mp4'
            destination.write_bytes(self.video.read_bytes())
            record_result_kind(destination, 'karaoke')
            scope = dict(youtube_publish_options=options, youtube_publisher=self.publisher,
                         os=os, library_dir=str(self.root), history_filename='song.mp4',
                         orig_name='Música', logger=logging.getLogger('test'), update_process_summary=Mock())
            exec(compile(ast.Module(body=[block], type_ignores=[]), str(main), 'exec'), scope)
            jobs = self.publisher.read('jobs.json', [])
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]['video'], str(destination.resolve()))
            self.assertEqual(jobs[0]['requester'], self.user)
            scope['update_process_summary'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
