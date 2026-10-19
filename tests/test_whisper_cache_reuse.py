"""Regression coverage for lost acoustic caches and failed promotion."""
import json
import os
import shutil
import sys
import tempfile
import threading
import textwrap
import hashlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from reprocess_cache import copy_reusable_inputs, file_fingerprint
from lyric_guide import prepare_lyrics_guide, GUIDE_POLICY_VERSION
import queue_cache
from test_automatic_lyrics_and_search import load_function


class WhisperCacheReuseTests(unittest.TestCase):
    def policy_upgrade(self, folder, policy=2, review='valid', **changes):
        source = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        start = source.index('        # Upgrade prior verse-based reviews once;')
        end = source.index('        save_stage_checkpoint(cache_dir, "input_ready"', start)
        code = compile(textwrap.dedent(source[start:end]), 'guide-policy-migration', 'exec')
        root = Path(folder)
        stages = {name: {'saved': True} for name in ('audio_extracted', 'vocals_separated',
            'transcription_ready', 'transcription_reviewed', 'subtitles_generated', 'video_rendered')}
        checkpoint = root / 'stage_checkpoints.json'
        checkpoint.write_text(json.dumps(dict(completed_stages=stages)), encoding='utf-8')
        raw = [dict(start=1, end=3, text='Recognition before user review', words=[
            dict(word='Recognition before user review', start=1, end=3)])]
        human = [dict(start=1, end=3, text='Minha revisão completa', words=[
            dict(word='Minha revisão completa', start=1, end=3)])]
        (root / 'transcribed_segments.json').write_text(json.dumps(raw), encoding='utf-8')
        (root / 'vocals.wav').write_bytes(b'untouched audio')
        if review == 'valid':
            (root / 'reviewed_segments.json').write_text(json.dumps(human), encoding='utf-8')
        elif review != 'missing':
            (root / 'reviewed_segments.json').write_text(review, encoding='utf-8')
        previous = dict(lyrics_policy_version=policy, lyrics=prepare_lyrics_guide('Eu canto assim'),
            whisper_model='medium', transcription_preset='karaoke', voice_source='all',
            whisper_audio_version=3, audio_hash='audio-one')
        meta = dict(lyrics_clock_hash=hashlib.sha256(json.dumps(previous, sort_keys=True).encode()).hexdigest())
        load = load_function('load_stage_checkpoints', os=os, json=json)
        scope = dict(hashlib=hashlib, json=json, os=os, queue_cache=queue_cache,
            cache_dir=folder, cache_meta_file=str(root / 'cache_meta.json'), cached_meta=meta,
            load_stage_checkpoints=load, GUIDE_POLICY_VERSION=GUIDE_POLICY_VERSION,
            prepare_lyrics_guide=prepare_lyrics_guide, lyrics_text='Eu canto assim',
            output_options={}, whisper_model='medium', transcription_preset='karaoke',
            keep_backing_vocals=False, transcribe_source='vocals', new_audio_hash='audio-one')
        scope.update(changes)
        before = {path.name: path.read_bytes() for path in root.iterdir() if path != checkpoint}
        exec(code, scope)
        for name, content in before.items():
            self.assertEqual((root / name).read_bytes(), content, f'Migration changed {name}')
        return load(folder)['completed_stages']

    def test_known_policy_upgrade_keeps_confirmed_human_review_and_raw_recognition(self):
        for policy in (1, 2):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as folder:
                remaining = self.policy_upgrade(folder, policy=policy)
                self.assertEqual(set(remaining), {'audio_extracted', 'vocals_separated',
                    'transcription_ready', 'transcription_reviewed'})

    def test_policy_upgrade_does_not_keep_review_for_different_audio_guide_model_or_voice_source(self):
        variants = [dict(new_audio_hash='different-audio'), dict(lyrics_text='Outra letra cantada'),
            dict(whisper_model='large-v3'), dict(transcribe_source='original'),
            dict(keep_backing_vocals=True), dict(transcription_preset='difficult')]
        for changes in variants:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as folder:
                remaining = self.policy_upgrade(folder, **changes)
                self.assertEqual(set(remaining), {'audio_extracted', 'vocals_separated', 'transcription_ready'})

    def test_policy_upgrade_requires_a_real_nonempty_review_before_preserving_checkpoint(self):
        for review in ('missing', '[]', '{}', 'not-json'):
            with self.subTest(review=review), tempfile.TemporaryDirectory() as folder:
                remaining = self.policy_upgrade(folder, review=review)
                self.assertEqual(set(remaining), {'audio_extracted', 'vocals_separated', 'transcription_ready'})

    def test_policy_upgrade_discards_lrc_reviews_but_preserves_audio_and_raw_whisper(self):
        source = (ROOT / 'app/main.py').read_text()
        start = source.index('        # Upgrade prior verse-based reviews once;')
        end = source.index('        save_stage_checkpoint(cache_dir, "input_ready"', start)
        code = compile(textwrap.dedent(source[start:end]), 'guide-policy-migration', 'exec')
        load = load_function('load_stage_checkpoints', os=os, json=json)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            meta = {'lyrics_clock_hash':'old_lrc_clock'}
            names = ('audio_extracted', 'vocals_separated', 'transcription_ready',
                     'transcription_reviewed', 'subtitles_generated', 'video_rendered')
            checkpoint = root / 'stage_checkpoints.json'
            def restore():
                checkpoint.write_text(json.dumps({'completed_stages':{name:{} for name in names}}))
            restore()
            for name in ('vocals.wav', 'transcribed_segments.json'):
                (root/name).write_text('preserved')
            scope = dict(hashlib=hashlib, json=json, os=os, cache_dir=folder,
                cache_meta_file=str(root/'cache_meta.json'), cached_meta=meta,
                load_stage_checkpoints=load, GUIDE_POLICY_VERSION=GUIDE_POLICY_VERSION,
                prepare_lyrics_guide=prepare_lyrics_guide, lyrics_text='[00:01]eu canto assim',
                output_options={}, whisper_model='medium', transcription_preset='karaoke',
                keep_backing_vocals=True, transcribe_source='vocals', new_audio_hash='audio-one')
            exec(code, scope)
            self.assertEqual(set(load(folder)['completed_stages']), set(names[:3]))
            self.assertEqual((root/'vocals.wav').read_text(), 'preserved')
            self.assertEqual((root/'transcribed_segments.json').read_text(), 'preserved')
            restore()
            scope['lyrics_text'] = '[09:58]eu canto assim'
            exec(code, scope)
            self.assertEqual(set(load(folder)['completed_stages']), set(names))
            scope['whisper_model'] = 'large-v3'
            exec(code, scope)
            self.assertEqual(set(load(folder)['completed_stages']), set(names[:3]))
            restore()
            scope['transcribe_source'] = 'original'
            exec(code, scope)
            self.assertEqual(set(load(folder)['completed_stages']), set(names[:3]))
            restore()
            # Once original is selected, backing changes the mix, not recognition.
            scope['keep_backing_vocals'] = False
            exec(code, scope)
            self.assertEqual(set(load(folder)['completed_stages']), set(names))
            self.assertEqual((root/'vocals.wav').read_text(), 'preserved')
            self.assertEqual((root/'transcribed_segments.json').read_text(), 'preserved')

    def test_display_update_rebuilds_render_without_losing_recognition_or_review(self):
        load = load_function('load_stage_checkpoints', os=os, json=json)
        invalidate = load_function('invalidate_subtitle_display_cache', os=os, json=json, load_stage_checkpoints=load)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stages = {name: {'done': True} for name in ('audio_extracted', 'vocals_separated',
                      'transcription_ready', 'transcription_reviewed', 'subtitles_generated', 'video_rendered')}
            checkpoint = root / 'stage_checkpoints.json'
            checkpoint.write_text(json.dumps({'completed_stages': stages, 'active_processing_seconds': 42}))
            for name in ('vocals.wav', 'transcribed_segments.json', 'reviewed_segments.json'):
                (root / name).write_text('saved recognition or user correction')
            before = {file.name: file.read_bytes() for file in root.iterdir() if file != checkpoint}
            meta = {'subtitle_display_options': {'version': 1}}
            options = {'version': 2, 'words_per_line': 6}
            self.assertTrue(invalidate(folder, meta, options))
            remaining = json.loads(checkpoint.read_text())
            self.assertEqual(set(remaining['completed_stages']), set(stages) - {'subtitles_generated', 'video_rendered'})
            self.assertEqual(remaining['active_processing_seconds'], 42)
            self.assertEqual({file.name: file.read_bytes() for file in root.iterdir() if file != checkpoint}, before)
            self.assertEqual(meta['subtitle_display_options'], options)
            unchanged = checkpoint.read_bytes()
            self.assertFalse(invalidate(folder, meta, dict(options)))
            self.assertEqual(checkpoint.read_bytes(), unchanged)

    def test_synced_and_srt_analysis_are_copied_but_review_is_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / 'old', Path(folder) / 'new'
            source.mkdir()
            reusable = {'synced_acoustic_segments.json', 'whisper_cache_meta.json', 'lyrics_guide_cache.json',
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
