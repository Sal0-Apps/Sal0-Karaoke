import ast
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from result_publication import record_result_kind, result_kind, youtube_eligible
from youtube_publisher import YouTubePublisher, PublicationError

MAIN = (ROOT / 'app/main.py').read_text()
TREE = ast.parse(MAIN)


class SrtPublicationBlockTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.history = self.root / 'library/history'
        self.history.mkdir(parents=True)
        self.video = self.history / 'song.mp4'
        self.video.write_bytes(b'mp4')

    def test_srt_and_audio_srt_video_are_never_eligible(self):
        self.assertFalse(youtube_eligible(self.video.with_suffix('.srt')))
        record_result_kind(self.video, 'subtitle_video')
        self.assertEqual(result_kind(self.video), 'subtitle_video')
        self.assertFalse(youtube_eligible(self.video))

    def test_only_confirmed_karaoke_is_eligible(self):
        self.assertFalse(youtube_eligible(self.video))
        record_result_kind(self.video, 'karaoke')
        self.assertTrue(youtube_eligible(self.video))
        marker = self.history / '.sal0-results' / (self.video.name + '.json')
        marker.write_text('broken json')
        self.assertFalse(youtube_eligible(self.video))

    def test_legacy_latest_metadata_recognized_and_other_files_blocked(self):
        output = self.root / 'output'
        output.mkdir()
        meta = output / 'result_meta.json'
        for kind, expected in (('subtitle_video', False), ('subtitles', False), (None, True)):
            meta.write_text(json.dumps({'history_filename': self.video.name, 'result_kind': kind}))
            self.assertEqual(youtube_eligible(self.video), expected)
        self.assertFalse(youtube_eligible(self.history / 'older.mp4'))
        meta.write_text(json.dumps({'history_filename': self.video.name, 'original_subtitle_filename':'original.srt'}))
        self.assertFalse(youtube_eligible(self.video))
        record_result_kind(self.video, 'subtitle_video')
        meta.write_text(json.dumps({'history_filename': self.video.name}))
        self.assertFalse(youtube_eligible(self.video), 'Persistent SRT marker overrides legacy metadata')

    def test_new_and_resumed_uploads_blocked_before_any_google_call(self):
        publisher = YouTubePublisher(str(self.root / 'youtube'))
        for kind in ('subtitle_video', None):
            if kind:
                record_result_kind(self.video, kind)
            else:
                (self.history / '.sal0-results' / (self.video.name + '.json')).unlink()
            with patch.object(publisher, 'token') as token, patch.object(publisher, 'upload_request') as upload, patch.object(publisher, 'api') as api:
                with self.assertRaises(PublicationError):
                    publisher.enqueue(self.video, 'Song')
                with self.assertRaises(PublicationError):
                    publisher.publish({'video':str(self.video), 'video_id':'already-uploaded', 'playlist_id':'PL-one'})
                token.assert_not_called()
                upload.assert_not_called()
                api.assert_not_called()
            self.assertEqual(publisher.read('jobs.json', []), [])

    def test_manual_api_resolver_blocks_srt_mp4_and_unknown(self):
        node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'resolve_youtube_publication_video')
        from fastapi import HTTPException
        scope = {'Path':Path, 'os':os, 'HTTPException':HTTPException,
                 'admin_result_owner':lambda *_:{}, 'get_user_paths':lambda _: {'library':str(self.root / 'library')},
                 'youtube_eligible':youtube_eligible}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'resolver', 'exec'), scope)
        for kind in (None, 'subtitle_video', 'karaoke'):
            if kind: record_result_kind(self.video, kind)
            if kind == 'karaoke':
                self.assertEqual(scope['resolve_youtube_publication_video']('__admin__', self.video.name, {}), str(self.video))
            else:
                with self.assertRaises(HTTPException) as error:
                    scope['resolve_youtube_publication_video']('__admin__', self.video.name, {})
                self.assertEqual(error.exception.status_code, 400)

    def test_srt_request_ignores_publication_flag_without_channel_checks(self):
        node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'process_karaoke')
        initial = next(n for n in node.body if isinstance(n, ast.Try) and 'publication_options' in ast.unparse(n))
        publisher = Mock()
        scope = {'youtube_publisher':publisher, 'subtitle_only':True, 'youtube_publish':True,
                 'youtube_playlist_id':'PL-one', 'youtube_title':'Song', 'current_user':{'role':'admin'}}
        exec(compile(ast.Module(body=[initial], type_ignores=[]), 'request', 'exec'), scope)
        self.assertIsNone(scope['publication_options'])
        publisher.publication_options.assert_not_called()

    def test_saved_videos_keep_provenance_independently_of_latest_output(self):
        node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == 'save_video_to_history')
        scope = {'os':os, 'shutil':shutil, 'logger':logging.getLogger('test'),
                 'record_result_kind':record_result_kind, 'karaoke_download_filename':lambda _: 'result.mp4'}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'history', 'exec'), scope)
        source = self.root / 'final.mp4'
        source.write_bytes(b'video')
        srt_name = scope['save_video_to_history'](str(source), 'Song', str(self.root / 'library'), result_kind='subtitle_video')
        karaoke_name = scope['save_video_to_history'](str(source), 'Song', str(self.root / 'library'))
        self.assertFalse(youtube_eligible(self.history / srt_name))
        self.assertTrue(youtube_eligible(self.history / karaoke_name))
        self.assertNotEqual(srt_name, karaoke_name)
