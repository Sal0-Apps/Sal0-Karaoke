import ast
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from telegram_delivery import TelegramDelivery, units
from telegram_results import ResultNotifications
from youtube_publisher import YouTubePublisher
from result_publication import record_result_kind


class TelegramResultTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.video = self.root / 'owner/history/song.mp4'
        self.video.parent.mkdir(parents=True)
        self.video.write_bytes(b'video')
        self.calls = []
        self.on_post = None
        def post(url, **kwargs):
            method = url.rsplit('/', 1)[1]
            payload = kwargs.get('json', kwargs.get('data'))
            self.calls.append((method, payload))
            if self.on_post:
                override = self.on_post(method, payload)
                if override:
                    return override
            return SimpleNamespace(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 42}})
        self.delivery = TelegramDelivery(post=post, sleep=lambda _: None)
        self.notifications = ResultNotifications(self.delivery, self.root / 'receipts')
        self.targets = [{'telegram_token': 'private-token', 'telegram_chat_id': '-1001'}]
        self.caption = '✅ <b>Karaokê concluído</b>\n\n🎵 Música 🎤\n<a href="https://local.test/download/a">Local</a> · <a href="https://external.test/download/a">Externo</a>'

    def send(self, message=False):
        args = (str(self.video), 'private-token', '-1001')
        return self.notifications.send_message(*args, self.caption) if message else self.notifications.send_video(*args, str(self.video), self.caption)

    def publish(self, automatic=True, targets=None, video=None):
        return self.notifications.published(str(video or self.video), 'abcdefghijk', 'Música',
            self.targets if targets is None else targets, automatic=automatic)

    def test_later_upload_edits_original_caption_and_keeps_all_download_links(self):
        self.assertTrue(self.send().ok)
        self.assertTrue(self.publish())
        self.assertEqual([m for m, _ in self.calls], ['sendVideo', 'editMessageCaption'])
        edit = self.calls[-1][1]
        self.assertEqual(edit['message_id'], 42)
        self.assertIn('Música 🎤', edit['caption'])
        urls = {e['url'] for e in edit['caption_entities'] if e['type'] == 'text_link'}
        self.assertEqual(urls, {'https://www.youtube.com/watch?v=abcdefghijk', 'https://local.test/download/a', 'https://external.test/download/a'})
        self.assertLessEqual(units(edit['caption']), 1024)

    def test_upload_completed_first_includes_link_in_initial_message(self):
        self.publish()
        self.assertEqual(self.calls, [])
        self.send()
        self.assertEqual([m for m, _ in self.calls], ['sendVideo'])
        self.assertIn('Assistir no YouTube', self.calls[0][1]['caption'])

    def test_upload_completing_during_send_updates_the_same_message(self):
        def during(method, _):
            if method == 'sendVideo':
                self.publish()
        self.on_post = during
        self.send()
        self.assertEqual([m for m, _ in self.calls], ['sendVideo', 'editMessageCaption'])

    def test_channel_username_keeps_receipt_for_confirmed_numeric_chat(self):
        self.on_post = lambda method, _: SimpleNamespace(status_code=200,
            json=lambda: {'ok': True, 'result': {'message_id': 42, 'chat': {'id': -1001}}})
        self.notifications.send_video(str(self.video), 'private-token', '@mychannel', str(self.video), self.caption)
        self.publish(targets=[{'telegram_token': 'private-token', 'telegram_chat_id': '@mychannel'}])
        self.assertEqual([m for m, _ in self.calls], ['sendVideo', 'editMessageCaption'])
        self.assertEqual(self.calls[-1][1]['chat_id'], '-1001')

    def test_migrated_chat_reuses_original_receipt(self):
        self.on_post = lambda method, _: SimpleNamespace(status_code=200,
            json=lambda: {'ok': True, 'result': {'message_id': 42, 'chat': {'id': -100222}}})
        self.send()
        self.publish(targets=[{'telegram_token': 'private-token', 'telegram_chat_id': '-100222'}])
        self.assertEqual([m for m, _ in self.calls], ['sendVideo', 'editMessageCaption'])
        self.assertEqual(self.calls[-1][1]['chat_id'], '-100222')

    def test_text_fallback_receives_link_without_another_video(self):
        self.send(message=True)
        self.publish()
        self.assertEqual([m for m, _ in self.calls], ['sendMessage', 'editMessageText'])
        self.assertEqual(self.calls[-1][1]['message_id'], 42)
        self.assertIn('Assistir no YouTube', self.calls[-1][1]['text'])

    def test_restart_and_repeated_completion_do_not_duplicate_notifications(self):
        self.send()
        self.notifications = ResultNotifications(self.delivery, self.root / 'receipts')
        self.publish()
        self.notifications = ResultNotifications(self.delivery, self.root / 'receipts')
        self.publish()
        self.assertEqual(len(self.calls), 2)
        for record in (self.root / 'receipts').glob('*.json'):
            self.assertNotIn('private-token', record.read_text())

    def test_manual_publication_of_older_result_sends_link_once(self):
        self.publish(automatic=False)
        self.notifications = ResultNotifications(self.delivery, self.root / 'receipts')
        self.publish(automatic=False)
        self.assertEqual([m for m, _ in self.calls], ['sendMessage'])
        self.assertIn('abcdefghijk', json.dumps(self.calls))

    def test_different_account_path_bot_and_destination_never_edit_another_result(self):
        self.send()
        self.publish(targets=[{'telegram_token': 'other-bot', 'telegram_chat_id': '-1001'}])
        self.publish(targets=[{'telegram_token': 'private-token', 'telegram_chat_id': '-1002'}])
        self.publish(video=self.root / 'other/history/song.mp4')
        self.assertEqual([m for m, _ in self.calls], ['sendVideo'])

    def test_missing_original_message_gets_one_confirmation_without_reupload(self):
        self.send()
        self.on_post = lambda method, _: SimpleNamespace(status_code=400,
            json=lambda: {'ok': False, 'description': 'Bad Request: message to edit not found'}) if method.startswith('edit') else None
        self.publish()
        self.publish()
        self.assertEqual([m for m, _ in self.calls].count('sendVideo'), 1)
        self.assertEqual([m for m, _ in self.calls].count('sendMessage'), 1)

    def test_unconfirmed_edit_can_resume_without_resending_video(self):
        self.send()
        self.on_post = lambda method, _: SimpleNamespace(status_code=503,
            json=lambda: {'ok': False, 'error_code': 503}) if method.startswith('edit') else None
        self.assertFalse(self.publish())
        self.on_post = None
        self.assertTrue(self.publish())
        self.assertEqual([m for m, _ in self.calls].count('sendVideo'), 1)

    def test_already_edited_response_is_success_and_invalid_video_id_is_rejected(self):
        self.send()
        self.on_post = lambda method, _: SimpleNamespace(status_code=400,
            json=lambda: {'ok': False, 'description': 'Bad Request: message is not modified'}) if method.startswith('edit') else None
        self.assertTrue(self.publish())
        self.assertFalse(self.notifications.published(str(self.video), 'bad<script>', 'Title', self.targets))

    def test_main_completion_callback_uses_media_owner_instead_of_admin_requester(self):
        tree = ast.parse((ROOT / 'app/main.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'notify_youtube_publication')
        service = Mock()
        scope = {'Path': Path, 're': re, 'TELEGRAM_RESULTS': service,
                 'load_users': lambda: {'alice': {'role': 'user'}, 'admin': {'role': 'admin'}},
                 'get_user_paths': lambda user: {'library': str(self.root / user['username'])},
                 'get_notification_targets': lambda user: [{'owner': user['username']}, {'owner': 'admin'}]}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'main.py', 'exec'), scope)
        job = {'video': str(self.root / 'alice/history/song.mp4'), 'video_id': 'abcdefghijk', 'status': 'done',
               'title': 'Música', 'requester': {'username': 'admin', 'role': 'admin'}}
        scope['notify_youtube_publication'](job)
        self.assertEqual(service.published.call_args.args[3], [{'owner': 'alice'}, {'owner': 'admin'}])
        service.reset_mock()
        job['status'] = 'finalizing'
        self.assertFalse(scope['notify_youtube_publication'](job))
        service.published.assert_not_called()


class PublicationCompletionTests(unittest.TestCase):
    def test_reused_upload_links_each_result_without_publishing_duplicate_video(self):
        with tempfile.TemporaryDirectory() as folder:
            publisher = YouTubePublisher(folder)
            original = Path(folder) / 'original.mp4'
            duplicate = Path(folder) / 'duplicate.mp4'
            for video in (original, duplicate):
                video.write_bytes(b'identical video')
                record_result_kind(video, 'karaoke')
            publisher.save('token.json', {'refresh_token': 'private', 'channel_id': 'channel'})
            calls = []
            publisher.on_published = lambda job: (calls.append(job) or True)
            with patch.object(publisher, 'start'), patch.object(publisher, 'validate_profile_playlist', return_value='playlist'):
                first = publisher.enqueue(original, 'Title', thumbnail=b'\xff\xd8\xff', automatic=True)
                active_job = publisher.read('jobs.json', [])[0]
                second = publisher.enqueue(duplicate, 'Title', thumbnail=b'\xff\xd8\xff', automatic=True)
            self.assertEqual(first['id'], second['id'])
            # The active worker still holds the job from before the second result arrived.
            publisher.checkpoint(active_job, status='done', video_id='abcdefghijk')
            jobs = publisher.read('jobs.json', [])
            self.assertEqual(len(jobs), 1)
            with patch.object(publisher, 'publish') as upload:
                publisher.work()
                upload.assert_not_called()
            self.assertEqual({job['video'] for job in calls}, {str(original), str(duplicate)})
            calls.clear()
            # A manual request can also reuse an already completed upload.
            with patch.object(publisher, 'start'), patch.object(publisher, 'validate_profile_playlist', return_value='playlist'), patch('youtube_publisher.threading.Thread') as background:
                publisher.enqueue(duplicate, 'Title', thumbnail=b'\xff\xd8\xff')
                background.assert_called_once()
                self.assertEqual(background.call_args.kwargs['target'], publisher.notify_published)
            publisher.work()
            self.assertFalse(next(job for job in calls if job['video'] == str(duplicate))['automatic'])

    def test_callback_runs_only_after_confirmed_final_privacy(self):
        with tempfile.TemporaryDirectory() as folder:
            publisher = YouTubePublisher(folder)
            video = Path(folder) / 'song.mp4'; video.write_bytes(b'video'); record_result_kind(video, 'karaoke')
            job = {'id': 'job', 'video': str(video), 'video_id': 'abcdefghijk', 'channel_id': 'channel',
                   'playlist_id': 'playlist', 'privacy': 'unlisted', 'thumbnail_done': True, 'playlist_done': True, 'status': 'queued'}
            publisher.save('jobs.json', [job])
            calls = []
            publisher.on_published = lambda completed: (calls.append(completed) or True)
            with patch.object(publisher, 'validate_profile_playlist', return_value='playlist'), patch.object(publisher, 'token', return_value={'channel_id':'channel'}), patch.object(publisher, 'api', return_value={'status': {'privacyStatus':'private'}}):
                with self.assertRaises(Exception): publisher.publish(job)
            self.assertEqual(calls, [])
            with patch.object(publisher, 'validate_profile_playlist', return_value='playlist'), patch.object(publisher, 'token', return_value={'channel_id':'channel'}), patch.object(publisher, 'api', return_value={'status': {'privacyStatus':'unlisted'}}):
                publisher.publish(job)
            self.assertEqual(calls[0]['status'], 'done')
            self.assertEqual(calls[0]['video_id'], 'abcdefghijk')
            self.assertFalse(job['telegram_link_pending'])

    def test_failed_telegram_callback_does_not_turn_completed_video_into_error(self):
        with tempfile.TemporaryDirectory() as folder:
            publisher = YouTubePublisher(folder)
            job = {'id': 'job', 'video': str(Path(folder) / 'song.mp4'), 'status': 'done',
                   'telegram_link_enabled': True, 'telegram_link_pending': True}
            publisher.save('jobs.json', [job])
            publisher.on_published = Mock(side_effect=RuntimeError('private credential'))
            with self.assertLogs('youtube_publisher', 'WARNING') as messages:
                publisher.work()
            self.assertEqual(publisher.read('jobs.json', [])[0]['status'], 'done')
            self.assertNotIn('private credential', str(messages.output))
