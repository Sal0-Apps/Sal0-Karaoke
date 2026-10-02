"""Regression coverage for lost acoustic caches and failed promotion."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from reprocess_cache import copy_reusable_inputs, file_fingerprint
from test_automatic_lyrics_and_search import load_function


class WhisperCacheReuseTests(unittest.TestCase):
    def test_synced_and_srt_analysis_are_copied_but_review_is_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'old', Path(folder) / 'new'
            source.mkdir()
            reusable = {'synced_acoustic_segments.json', 'whisper_cache_meta.json',
                        'subtitle_segments_original.json', 'subtitle_info_original.json'}
            excluded = {'reviewed_segments.json', 'reviewed_synced_segments.json',
                        'stage_checkpoints.json', 'karaoke.ass'}
            for name in reusable | excluded:
                (source / name).write_text('[]')
            copy_reusable_inputs(source, destination)
            self.assertEqual({file.name for file in destination.iterdir()}, reusable)

    def test_same_youtube_recording_reuses_source_across_url_variants(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'old', Path(folder) / 'new'
            source.mkdir()
            (source / 'original_input.mp4').write_bytes(b'media')
            (source / 'cache_meta.json').write_text(json.dumps({
                'youtube_url':'https://www.youtube.com/watch?v=abcdefghijk',
                'download_quality_version':2}))
            copy_reusable_inputs(source, destination, 'https://youtu.be/abcdefghijk?si=tracking')
            self.assertEqual((destination / 'original_input.mp4').read_bytes(), b'media')
            copy_reusable_inputs(source, Path(folder) / 'different', 'https://youtu.be/other-video')
            self.assertFalse((Path(folder) / 'different').exists())

    def test_same_size_different_media_has_different_fingerprint(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'input.wav'
            source.write_bytes(b'first')
            original = file_fingerprint(source)
            source.write_bytes(b'other')
            self.assertNotEqual(file_fingerprint(source), original)

    def test_failed_cache_copy_does_not_delete_original_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'job', Path(folder) / 'reusable'
            source.mkdir()
            (source / 'synced_acoustic_segments.json').write_text('[]')
            remove = Mock()
            promote = load_function('promote_queue_cache_in_background', os=os,
                shutil=shutil, legacy_cache_promotion_lock=threading.Lock(),
                get_user_paths=lambda owner:{'cache':str(destination)},
                remove_finished_queue_cache=remove)
            with patch.object(shutil, 'copytree', side_effect=OSError('disk full')):
                promote(str(source), {'username':'owner'})
            remove.assert_not_called()
            self.assertTrue((source / 'synced_acoustic_segments.json').exists())

    def test_successful_copy_can_clean_up_isolated_job(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'job', Path(folder) / 'reusable'
            source.mkdir()
            (source / 'synced_acoustic_segments.json').write_text('[]')
            remove = Mock()
            promote = load_function('promote_queue_cache_in_background', os=os,
                shutil=shutil, legacy_cache_promotion_lock=threading.Lock(),
                get_user_paths=lambda owner:{'cache':str(destination)},
                remove_finished_queue_cache=remove)
            promote(str(source), {'username':'owner'})
            remove.assert_called_once_with(str(source))
            self.assertTrue((destination / 'synced_acoustic_segments.json').exists())
