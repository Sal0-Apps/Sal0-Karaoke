"""Review, submission and recovery behavior found during the 10.7 flow audit."""
import copy
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.responses import FileResponse, Response
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from processing_validation import validate_processing_options
from lyrics_sync import anchor_synced_animation
from test_automatic_lyrics_and_search import HTTPError, load_function
from test_easy_mode_config import load_normalizer


def segment(**changes):
    return SimpleNamespace(start=10, end=13, text='  Exact lyric  ', words=[],
                           synced_line=True, acoustic_animation=True, **changes)


class ReviewTests(unittest.TestCase):
    def resume(self):
        original = [{'start': 10, 'end': 13, 'text': '  Exact lyric  '}]
        return load_function('continue_process', ContinueProcessModel=object,
            require_task_control=Mock(), segments_to_edit=copy.deepcopy(original),
            correction_event=threading.Event(), anchor_synced_animation=anchor_synced_animation)

    def test_unchanged_synced_review_preserves_every_character_and_provider_clock(self):
        resume = self.resume()
        resume(SimpleNamespace(segments=[segment()]), {})
        result = resume.__globals__['segments_to_edit'][0]
        self.assertEqual(result['text'], '  Exact lyric  ')
        self.assertEqual((result['start'], result['end']), (10, 13))
        self.assertTrue(resume.__globals__['correction_event'].is_set())

    def test_bad_review_keeps_existing_lyrics_and_does_not_release_the_pipeline(self):
        bad = [SimpleNamespace(start=10, end=13, text=' ', synced_line=False,
               words=[SimpleNamespace(word='old', start=10, end=11)])]
        for changes in ({'text': ''}, {'start': -1}, {'start': float('nan')},
                        {'end': float('inf')}, {'end': 10}):
            item = segment()
            for key, value in changes.items():
                setattr(item, key, value)
            bad.append(item)
        for item in bad:
            with self.subTest(item=item):
                resume = self.resume()
                before = copy.deepcopy(resume.__globals__['segments_to_edit'])
                with self.assertRaises(HTTPError) as error:
                    resume(SimpleNamespace(segments=[segment(), item]), {})
                self.assertEqual(error.exception.status_code, 400)
                self.assertIn('Linha 2', str(error.exception))
                self.assertEqual(resume.__globals__['segments_to_edit'], before)
                self.assertFalse(resume.__globals__['correction_event'].is_set())

    def test_empty_review_or_reversed_order_is_rejected(self):
        for items in ([], [segment(), SimpleNamespace(start=9, end=10, text='Earlier', words=[])]):
            with self.assertRaises(HTTPError):
                self.resume()(SimpleNamespace(segments=items), {})

    def test_bad_word_clock_is_rejected_before_reanchoring(self):
        item = segment()
        item.words = [SimpleNamespace(word='wrong', start=float('nan'), end=12)]
        with self.assertRaises(HTTPError):
            self.resume()(SimpleNamespace(segments=[item]), {})


class ProcessingChoicesTests(unittest.TestCase):
    def test_invalid_choices_are_rejected_before_creating_job_files(self):
        paths = Mock(side_effect=AssertionError('Must not create files'))
        process = load_function('process_karaoke', Form=lambda value: value,
            File=lambda value: value, UploadFile=object, youtube_publisher=Mock(),
            ensure_processing_queue_access=Mock(), ensure_processing_queue_capacity=Mock(),
            normalize_translation_language=lambda language: language,
            SUPPORTED_TARGET_LANGUAGES={'pt-BR'}, get_user_paths=paths)
        for values in ({'font_size': 0}, {'text_color': 'invalid'}, {'text_position': 'left'},
                       {'whisper_model': 'absent'}, {'backing_vocals_volume': -1},
                       {'youtube_url': 'https://example.com/watch?v=abcdefghijk'},
                       {'library_audio': '../other/music.mp4'}):
            with self.subTest(values=values), self.assertRaises(HTTPError) as error:
                process(current_user={'username': 'owner'}, **values)
            self.assertEqual(error.exception.status_code, 400)
        paths.assert_not_called()

    def test_valid_limits_and_youtube_variants_are_accepted(self):
        for url in ('https://youtu.be/abcdefghijk', 'https://www.youtube.com/watch?v=abcdefghijk',
                    'https://music.youtube.com/watch?v=abcdefghijk', 'https://youtube.com/shorts/abcdefghijk'):
            validate_processing_options(font_size=120, words_per_line=30, max_chars_line=100,
                backing_vocals_volume=0, youtube_url=url, text_color='#aBc012')

    def test_old_quick_configuration_is_normalized_without_crashing_or_enabling_vad(self):
        defaults, normalize = load_normalizer()
        result = normalize({'font_size': 'bad', 'words_per_line': None, 'max_chars_line': float('inf'),
                            'enable_vad': 'true', 'enable_correction': 'false', 'enabled': 'true'})
        self.assertEqual(result['font_size'], defaults['font_size'])
        self.assertEqual(result['words_per_line'], defaults['words_per_line'])
        self.assertFalse(result['enable_vad'])
        self.assertFalse(result['enable_correction'])
        self.assertTrue(result['enabled'])


class QueueRecoveryTests(unittest.TestCase):
    def test_user_paths_restore_analysis_after_an_interrupted_cache_swap(self):
        for empty_cache in (False, True):
            with self.subTest(empty_cache=empty_cache), tempfile.TemporaryDirectory() as folder:
                cache = Path(folder) / 'cache'
                previous = Path(str(cache) + '.previous')
                previous.mkdir()
                (previous / 'analysis.json').write_text('preserved')
                if empty_cache:
                    cache.mkdir()
                paths = load_function('get_user_paths', os=os, is_admin=lambda _: True,
                    LEGACY_CACHE_DIR=str(cache), LEGACY_LIBRARY_DIR=str(Path(folder) / 'library'),
                    LEGACY_OUTPUT_DIR=str(Path(folder) / 'output'), legacy_cache_promotion_lock=threading.RLock())
                self.assertEqual(paths({})['cache'], str(cache))
                self.assertEqual((cache / 'analysis.json').read_text(), 'preserved')
                self.assertFalse(previous.exists())

    def test_interrupted_queue_write_preserves_last_saved_jobs_and_pause_state(self):
        for name, key in (('save_processing_queue_unlocked', 'PROCESSING_QUEUE_FILE'),
                          ('save_processing_queue_control_unlocked', 'PROCESSING_QUEUE_CONTROL_FILE')):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'queue.json'
                path.write_text('{"previous": true}')
                save = load_function(name, os=os, json=json, processing_queue=[{'status': 'queued'}],
                    processing_queue_paused=True, ACTIVE_QUEUE_STATUSES={'queued', 'processing'}, **{key: str(path)})
                with patch.object(json, 'dump', side_effect=OSError('disk full')), self.assertRaises(OSError):
                    save()
                self.assertEqual(json.loads(path.read_text()), {'previous': True})

    def test_failed_submission_cannot_leave_a_hidden_duplicate_in_memory(self):
        existing = {'status': 'queued', 'owner_username': 'owner', 'id': 'old'}
        queue = [existing]
        event = threading.Event()
        enqueue = load_function('enqueue_processing_job', processing_queue=queue,
            processing_queue_lock=threading.Lock(), processing_queue_event=event,
            save_processing_queue_unlocked=Mock(side_effect=OSError('disk full')))
        with self.assertRaises(HTTPError) as error:
            enqueue({'status': 'queued', 'owner_username': 'owner', 'id': 'new'})
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(queue, [existing])
        self.assertFalse(event.is_set())

    def test_failed_cache_copy_or_swap_preserves_both_old_and_new_analysis(self):
        for failure in ('copy', 'swap'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                job, cache = Path(folder) / 'job', Path(folder) / 'cache'
                job.mkdir(); cache.mkdir()
                (job / 'new.json').write_text('new'); (cache / 'old.json').write_text('old')
                cleanup = Mock()
                promote = load_function('promote_queue_cache_in_background', os=os, shutil=shutil,
                    legacy_cache_promotion_lock=threading.Lock(), get_user_paths=lambda _: {'cache': str(cache)},
                    remove_finished_queue_cache=cleanup)
                real_replace = os.replace
                def broken_swap(source, destination):
                    if str(source).endswith('.promoting'):
                        raise OSError('swap failed')
                    return real_replace(source, destination)
                target, method, behavior = (shutil, 'copytree', OSError('copy failed')) if failure == 'copy' else (os, 'replace', broken_swap)
                with patch.object(target, method, side_effect=behavior):
                    promote(str(job), {})
                self.assertEqual((cache / 'old.json').read_text(), 'old')
                self.assertEqual((job / 'new.json').read_text(), 'new')
                cleanup.assert_not_called()


class ReviewBackgroundTests(unittest.TestCase):
    def test_audio_preview_uses_the_active_original_without_a_title_cover(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = Path(folder) / 'source.wav'
            audio.write_bytes(b'audio')
            view = load_function('get_cached_audio', os=os, mimetypes=mimetypes,
                active_queue_pipeline_for_user=lambda _: {'input_audio_path': str(audio)}, FileResponse=FileResponse)
            self.assertEqual(view({'username': 'owner'}).path, str(audio))

    def test_audio_preview_does_not_fall_back_to_a_previous_song_when_current_source_is_missing(self):
        view = load_function('get_cached_audio', os=os,
            active_queue_pipeline_for_user=lambda _: {'input_audio_path': '/missing/current.wav'})
        with self.assertRaises(HTTPError) as error:
            view({'username': 'owner'})
        self.assertEqual(error.exception.status_code, 404)

    def test_original_video_wins_over_an_unused_uploaded_background(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            (cache / 'cache_meta.json').write_text(json.dumps({'has_bg': True, 'bg_ext': '.png'}))
            (cache / 'original_bg.png').write_bytes(b'unused')
            pipeline = {'input_audio_path': '/own/source.mp4', 'background_mode': 'original'}
            view = load_function('get_cached_background', os=os, json=json, mimetypes=mimetypes,
                queue_cache_dir_for_user=lambda _: str(cache), active_queue_pipeline_for_user=lambda _: pipeline,
                check_has_video=lambda _: True, FileResponse=FileResponse)
            self.assertEqual(view({}).path, '/own/source.mp4')

    def test_solid_color_preview_matches_the_black_render(self):
        view = load_function('get_cached_background', os=os, queue_cache_dir_for_user=lambda _: '/own/cache',
            active_queue_pipeline_for_user=lambda _: {'background_mode': 'color'}, Response=Response)
        self.assertIn(b'fill="black"', view({}).body)


if __name__ == '__main__':
    unittest.main()
