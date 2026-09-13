import ast
import copy
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from reprocess_cache import copy_reusable_inputs
from subtitle_translator import cover_full_media_timeline
from media_covers import add_cover_to_command, cover_title


class HTTPError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


def admin(user):
    return user.get('role') == 'admin'


def require_admin(user):
    if not admin(user):
        raise HTTPError(403, 'admin only')


def functions(*names, **values):
    tree = ast.parse((ROOT / 'app/main.py').read_text(encoding='utf-8'))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in selected:
        node.decorator_list = []
    scope = dict(HTTPException=HTTPError, is_admin=admin, require_admin=require_admin,
                 Depends=lambda x: None, get_current_user=lambda: None, Response=object,
                 QueueMoveRequest=object, os=os, **values)
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'main.py', 'exec'), scope)
    return scope


class ReprocessingPrivacyAndCovers(unittest.TestCase):
    def test_word_timestamps_remove_leading_and_internal_silence(self):
        original = [{'start': 0, 'end': 20, 'text': 'Hello world', 'words': [
            {'word': 'Hello', 'start': 4, 'end': 5}, {'word': 'world', 'start': 8, 'end': 9}]}]
        saved = copy.deepcopy(original)
        result = cover_full_media_timeline(original, 30)
        self.assertEqual([(x['start'], x['end']) for x in result], [(4, 5), (8, 9)])
        self.assertEqual(original, saved)

    def test_reprocess_copies_audio_but_not_prior_checkpoints_or_result(self):
        with tempfile.TemporaryDirectory() as directory:
            src, dst = Path(directory) / 'old', Path(directory) / 'new'
            src.mkdir()
            for name in ['original_input.mp4', 'vocals.wav', 'instrumental.wav',
                         'transcribed_segments.json', 'cache_meta.json', 'stage_checkpoints.json',
                         'karaoke.ass', 'final_karaoke.mp4', 'final_subtitles_original.srt']:
                (src / name).write_text(name)
            copy_reusable_inputs(src, dst)
            self.assertEqual({x.name for x in dst.iterdir()}, {'original_input.mp4', 'vocals.wav',
                'instrumental.wav', 'transcribed_segments.json', 'cache_meta.json'})
            self.assertTrue((src / 'stage_checkpoints.json').exists())

    def test_any_authenticated_user_can_enqueue(self):
        scope = functions('ensure_processing_queue_access')
        for user in ({'username': 'alice', 'role': 'user'}, {'username': 'admin', 'role': 'admin'}):
            scope['ensure_processing_queue_access'](user)
        with self.assertRaises(HTTPError):
            scope['ensure_processing_queue_access']({})

    def test_only_admin_can_reorder_across_owners(self):
        queue = [{'id': 'running', 'status': 'processing', 'owner_username': 'bob'},
                 {'id': 'a', 'status': 'queued', 'owner_username': 'alice'},
                 {'id': 'b', 'status': 'queued', 'owner_username': 'bob'}]
        scope = functions('move_queued_job', processing_queue=queue,
                          processing_queue_lock=threading.Lock(),
                          processing_queue_event=threading.Event(), save_processing_queue_unlocked=lambda: None)
        with self.assertRaises(HTTPError) as caught:
            scope['move_queued_job']('a', SimpleNamespace(direction='down'), {'username': 'alice'})
        self.assertEqual(caught.exception.status_code, 403)
        scope['move_queued_job']('b', SimpleNamespace(direction='up'), {'username': 'admin', 'role': 'admin'})
        self.assertEqual([x['id'] for x in queue], ['running', 'b', 'a'])

    def test_notifications_go_only_to_owner_and_admin(self):
        users = {'alice': {'role': 'user'}, 'bob': {'role': 'user'}, 'root': {'role': 'admin'}}
        scope = functions('get_notification_targets', load_users=lambda: users,
                          load_telegram_config=lambda user: {'telegram_token': 'bot-' + user['username'],
                                                              'telegram_chat_id': user['username']})
        targets = scope['get_notification_targets']({'username': 'alice', 'role': 'user'})
        self.assertEqual({x['telegram_chat_id'] for x in targets}, {'alice', 'root'})

    def test_other_profile_cannot_request_result_owner(self):
        scope = functions('library_request_user', user_from_username=lambda name: {'username': name, 'role': 'user'})
        with self.assertRaises(HTTPError):
            scope['library_request_user']({'username': 'alice'}, 'bob')
        self.assertEqual(scope['library_request_user']({'username': 'root', 'role': 'admin'}, 'bob')['username'], 'bob')

    def test_private_status_never_exposes_other_users_result(self):
        state = {'owner_username': 'bob', 'status': 'done', 'result_file': '/private/video.mp4',
                 'history_filename': 'secret.mp4'}
        scope = functions('get_status', state=state, state_lock=threading.Lock())
        response = SimpleNamespace(headers={})
        self.assertEqual(scope['get_status'](response, {'username': 'alice'})['status'], 'idle')
        self.assertNotIn('history_filename', scope['get_status'](response, {'username': 'alice'}))
        state['status'] = 'processing'
        self.assertEqual(scope['get_status'](response, {'username': 'alice'})['status'], 'busy')

    def test_explicit_admin_owner_never_falls_back_to_another_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'alice' / 'history'
            path.mkdir(parents=True)
            (path / 'same.mp4').write_bytes(b'keep')
            scope = functions('library_request_user', 'resolve_library_file',
                load_users=lambda: {'alice': {'role': 'user'}},
                get_user_paths=lambda user: {'library': str(Path(directory) / user['username'])})
            target = scope['library_request_user']({'username': 'root', 'role': 'admin'}, 'root')
            self.assertIsNone(scope['resolve_library_file'](target, 'history', 'same.mp4'))
            self.assertEqual((path / 'same.mp4').read_bytes(), b'keep')

    def test_all_categories_keep_distinct_owners_for_bulk_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            for section in ('videos', 'photos'):
                for owner in ('alice', 'bob'):
                    path = Path(directory) / owner / section
                    path.mkdir(parents=True)
                    (path / 'same.mp4').write_bytes(b'video')
                    (path / '.hidden').write_bytes(b'hidden')
            scope = functions('library_history_items',
                load_users=lambda: {'alice': {'role': 'user'}, 'bob': {'role': 'user'}},
                get_user_paths=lambda user: {'library': str(Path(directory) / user['username'])})
            for section in ('videos', 'photos'):
                items = scope['library_history_items']({'username': 'root', 'role': 'admin'}, section)
                self.assertEqual({(item['owner'], item['filename']) for item in items},
                                 {('alice', 'same.mp4'), ('bob', 'same.mp4')})

    def test_admin_results_keep_identical_names_separate_and_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            for index, owner in enumerate(('alice', 'bob')):
                folder = Path(directory) / owner / 'history'
                folder.mkdir(parents=True)
                item = folder / 'same.mp4'
                item.write_bytes(b'video')
                os.utime(item, (100 + index, 100 + index))
            scope = functions('library_history_items',
                              load_users=lambda: {'alice': {'role': 'user'}, 'bob': {'role': 'user'}},
                              get_user_paths=lambda user: {'library': str(Path(directory) / user['username'])})
            items = scope['library_history_items']({'username': 'root', 'role': 'admin'})
            self.assertEqual([item['owner'] for item in items], ['bob', 'alice'])
            self.assertEqual([item['filename'] for item in items], ['same.mp4', 'same.mp4'])
            own = scope['library_history_items']({'username': 'alice', 'role': 'user'})
            self.assertEqual(len(own), 1)
            self.assertEqual(own[0]['owner'], 'alice')

    def test_intro_is_extra_and_silent_without_retiming_content(self):
        command = ['ffmpeg', '-y', '-i', 'background.mp4', '-i', 'song.wav', '-vf', 'subtitles=karaoke.ass',
                   '-map', '0:v:0', '-map', '1:a:0', '-t', '10', 'result.mp4']
        result = add_cover_to_command(command, 'cover.png', 10)
        graph = result[result.index('-filter_complex') + 1]
        self.assertIn('[0:v]subtitles=karaoke.ass', graph)
        self.assertIn('anullsrc=', graph)
        self.assertIn('[intro][silence][main][audio]concat=n=2:v=1:a=1', graph)
        self.assertNotIn('overlay=', graph)
        self.assertEqual(result[result.index('-t') + 1], '13.000')
        self.assertEqual(command[-2], '10')

    def test_cover_wraps_long_titles(self):
        self.assertTrue(all(len(line) <= 36 for line in cover_title('A' * 170).splitlines()))


if __name__ == '__main__':
    unittest.main()
