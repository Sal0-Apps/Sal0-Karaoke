"""Acoustic guide pipeline; legacy verse helpers remain covered independently."""
import re
import hashlib
import json
import logging
import os
import sys
import subprocess
import tempfile
import textwrap
import unittest
import unicodedata
import array
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from lyrics_sync import parse_lrc, require_acoustic_word_timing, anchor_synced_animation, assess_synced_timing
from karaoke_generator import generate_ass_karaoke, synced_animation_text
from media_covers import add_cover_to_command
from test_automatic_lyrics_and_search import load_function
from reprocess_cache import copy_reusable_inputs
from lyric_guide import prepare_lyrics_guide, review_lyrics_with_whisper


class SyncedAcousticAnimationTests(unittest.TestCase):
    def run_stage(self, cache_version=None, verses=None, voice=None, reprocess=False, timing="auto", source_mode="vocals", backing_enabled=False, backing_volume=100):
        source = (ROOT / 'app/main.py').read_text()
        stage = source[source.index('            segments = None\n', source.index('# Passo 3: Transcrever vocais')):
                       source.index('            # --- NOVO: Passo de Pausa')]
        lrc = [dict(start=10, end=13, text='Olá mundo', words=[], synced_line=True)]
        acoustic = [{'start':10.2,'end':12.5,'text':' Ola mundo', 'words':[
            {'word':' Ola','start':10.2,'end':10.5},
            {'word':' mundo','start':11.6,'end':12.5}]}]
        lrc = verses if verses is not None else lrc
        acoustic = voice if voice is not None else acoustic
        lyric_text = '\n'.join(segment['text'] for segment in lrc)
        with tempfile.TemporaryDirectory() as folder:
            cached = acoustic if cache_version == 3 else lrc
            (Path(folder) / 'synced_acoustic_segments.json').write_text(json.dumps(cached))
            meta = dict(animation_timing_version=cache_version, vocal_source='lead',
                        transcribe_source=source_mode, whisper_model='medium', enable_vad=False,
                        transcription_preset='standard', whisper_audio_version=2, whisper_quality_mode='max_quality',
                        lyrics_hint_hash=hashlib.sha256(' '.join(lyric_text.split()).encode()).hexdigest())
            transcriber = Mock(return_value=acoustic)
            scope = dict(os=os, hashlib=hashlib, json=json, synced_segments=lrc,
                lyrics_text=lyric_text, cache_dir=folder, cached_meta=meta,
                prepare_lyrics_guide=prepare_lyrics_guide, review_lyrics_with_whisper=review_lyrics_with_whisper,
                cache_meta_file=str(Path(folder) / 'cache_meta.json'), vocal_source='lead',
                transcribe_source=source_mode, whisper_model='medium', enable_vad=True,
                transcription_preset='standard', vocals_wav='lead.wav', converted_wav='mix.wav',
                pm=SimpleNamespace(check_cancelled=Mock()), update_state=Mock(),
                notify_targets=Mock(), telegram_targets=[], orig_name='song',
                telegram_notice=lambda *parts: ' '.join(parts), telegram_escape=str,
                logger=logging.getLogger('test'), is_model_downloaded=lambda _:True,
                transcribe_vocals=transcriber, save_stage_checkpoint=Mock(),
                update_process_summary=Mock(), assess_synced_timing=assess_synced_timing,
                lyrics_timing=timing,
                align_lyrics=load_function('align_lyrics', clean_word=load_function('clean_word', unicodedata=unicodedata)), require_acoustic_word_timing=require_acoustic_word_timing, anchor_synced_animation=anchor_synced_animation)
            policy = source[source.index('    if not subtitle_only:\n', source.index('def run_pipeline(')):
                            source.index('    # Obter o lock', source.index('def run_pipeline('))]
            scope['subtitle_only'] = False
            exec(compile(textwrap.dedent(policy), 'full-audio-policy', 'exec'), scope)
            if backing_enabled:
                preparation = source[source.index('            if keep_backing_vocals:\n', source.index('# Passo 2:')):
                                     source.index('            def publish_render_progress', source.index('# Passo 2:'))]
                preserve = Mock(return_value=('isolated-lead.wav', 'instrumental-with-backing.wav'))
                scope.update(keep_backing_vocals=True, backing_vocals_volume=backing_volume,
                             instrumental_wav='clean-instrumental.wav', preserve_backing_vocals=preserve)
                exec(compile(textwrap.dedent(preparation), 'lead-source-stage', 'exec'), scope)
                scope['notify_targets'].reset_mock()
            exec(compile(textwrap.dedent(stage), 'transcription-stage', 'exec'), scope)
            scope['first_transcription_calls'] = transcriber.call_count
            if reprocess:
                next_cache = Path(folder) / 'next'
                copy_reusable_inputs(folder, next_cache)
                scope.update(cache_dir=str(next_cache),
                    cache_meta_file=str(next_cache / 'cache_meta.json'),
                    cached_meta=json.loads((next_cache / 'cache_meta.json').read_text()),
                    synced_segments=lrc, lyrics_text=lyric_text)
                transcriber.reset_mock()
                exec(compile(textwrap.dedent(stage), 'transcription-stage', 'exec'), scope)
        return scope, transcriber

    def test_synced_lyrics_do_not_bypass_voice_analysis_or_reuse_verse_only_cache(self):
        scope, transcriber = self.run_stage()
        transcriber.assert_called_once()
        self.assertEqual(transcriber.call_args.kwargs['initial_prompt'], 'Olá mundo')
        words = scope['segments'][0]['words']
        self.assertEqual([(w['start'],w['end']) for w in words], [(10.2,10.5),(11.6,12.5)])
        self.assertEqual(words[0]['word'], ' Olá')
        self.assertEqual([(s['start'], s['end'], s['text']) for s in scope['segments']],
                         [(10.2,12.5,'Olá mundo')])
        notices = scope['notify_targets'].call_args_list
        self.assertEqual(len(notices), 1)
        self.assertIn('Transcrição com Whisper', notices[0].args[1])
        self.assertEqual(scope['guide_report']['checked_words'], 2)

    def test_current_acoustic_cache_is_reused(self):
        scope, transcriber = self.run_stage(cache_version=3)
        transcriber.assert_not_called()
        self.assertEqual(scope['segments'][0]['words'][1]['start'], 11.6)

    def test_new_task_reuses_saved_whisper_analysis_without_calling_model(self):
        scope, transcriber = self.run_stage(reprocess=True)
        transcriber.assert_not_called()
        self.assertEqual(scope['segments'][0]['words'][1]['start'], 11.6)

    def test_incompatible_lrc_retry_reuses_analysis_after_copying_cache(self):
        verses, voice = self.timing_fixture([4.13, 2.33, 2.53, 3.28, 3.46, 3.76])
        scope, transcriber = self.run_stage(verses=verses, voice=voice, reprocess=True)
        transcriber.assert_not_called()
        self.assertEqual(scope['synced_segments'], verses)

    def test_guide_corrects_spelling_but_does_not_insert_unrecognized_verses(self):
        verses = [dict(start=10, end=13, text='Olá lindo mundo'),
                  dict(start=13, end=17, text='Outra palavra correta')]
        voice = [dict(start=10.2, end=12.5, text='Ola limbo mundo', words=[
            dict(word=' Ola', start=10.2, end=10.5),
            dict(word=' limbo', start=10.6, end=11),
            dict(word=' mundo', start=11.6, end=12.5)])]
        for timing in ('auto', 'acoustic'):
            scope, _ = self.run_stage(verses=verses, voice=voice, timing=timing)
            self.assertEqual([s['text'] for s in scope['segments']], ['Olá lindo mundo'])
            with tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'text.ass'
                generate_ass_karaoke(scope['segments'], str(target), show_instrumental=False,
                                     show_next_line_preview=False)
                output = target.read_text()
                self.assertIn('lindo', output)
                self.assertNotIn('correta', output)
                self.assertTrue(scope['guide_report']['retry_attempted'])
                self.assertNotIn('limbo', output)

    def test_empty_local_recognition_cannot_render_the_guide_instead(self):
        with self.assertRaisesRegex(ValueError, 'Nenhum vocal detectado'):
            self.run_stage(voice=[])

    def test_backing_option_forces_isolated_lead_even_with_original_source_or_zero_gain(self):
        for gain in (0, 100):
            scope, transcriber = self.run_stage(source_mode='original',
                backing_enabled=True, backing_volume=gain)
            self.assertEqual(transcriber.call_args.args[0], 'isolated-lead.wav')
            self.assertEqual(scope['instrumental_wav'], 'instrumental-with-backing.wav')
            self.assertEqual(scope['cached_meta']['transcribe_source'], 'vocals')
            self.assertEqual(scope['cached_meta']['vocal_source'], 'lead')
            self.assertEqual(scope['preserve_backing_vocals'].call_args.kwargs['gain'], gain / 100)

    def test_old_original_audio_cache_is_replaced_once_then_reused(self):
        scope, transcriber = self.run_stage(cache_version=3, source_mode='original',
                                           backing_enabled=True, reprocess=True)
        self.assertEqual(scope['first_transcription_calls'], 1)
        transcriber.assert_not_called()
        self.assertEqual(scope['cached_meta']['transcribe_source'], 'vocals')

    def test_recognized_text_is_irrelevant_even_when_all_words_are_wrong(self):
        verses = [dict(start=10, end=13, text='  Olá,  lindo mundo!  ')]
        words = [dict(word=word, start=10.1+i*.7, end=10.5+i*.7)
                 for i, word in enumerate(['nonsense', 'WRONG', ''])]
        anchored = anchor_synced_animation(verses, [dict(words=words)])
        other = anchor_synced_animation(verses, [dict(words=[{**w, 'word':'DIFFERENT'} for w in words])])
        self.assertEqual(anchored, other)
        self.assertEqual(anchored[0]['text'], verses[0]['text'])
        self.assertEqual(''.join(w['word'] for w in anchored[0]['animation_words']), verses[0]['text'])
        self.assertEqual([(w['start'], w['end']) for w in anchored[0]['words']],
                         [(w['start'], w['end']) for w in words])

    def test_stale_animation_text_cannot_remove_or_replace_provider_words(self):
        segment = dict(start=10, end=13, text='Texto completo original',
                       animation_words=[dict(word='Texto cortado', start=10.2, end=11)])
        text = synced_animation_text(segment, '&H00FFFFFF', '&H00FFFF00')
        self.assertEqual(re.sub(r'\{[^}]*\}', '', text), segment['text'])
        self.assertNotIn('cortado', text)
        self.assertNotIn(r'\t(', text)

    def test_karaoke_disables_vad_even_when_the_saved_profile_requests_it(self):
        scope, transcriber = self.run_stage()
        self.assertFalse(transcriber.call_args.kwargs['enable_vad'])
        self.assertFalse(scope['cached_meta']['enable_vad'])

    def timing_fixture(self, shifts):
        verses, voice = [], []
        for index, shift in enumerate(shifts):
            start = 7.09 + index * 10
            tokens = ['Verso', str(index), 'cantado']
            verses.append(dict(start=start, end=start + 6, text=' '.join(tokens),
                               words=[], synced_line=True))
            words = [dict(word=' ' + token, start=start + shift + offset * .4,
                          end=start + shift + (offset + 1) * .4)
                     for offset, token in enumerate(tokens)]
            voice.append(dict(start=words[0]['start'], end=words[-1]['end'],
                              text=' '.join(tokens), words=words))
        return verses, voice

    def test_same_duration_can_hide_an_incompatible_video_intro(self):
        verses, voice = self.timing_fixture([4.13, 2.33, 2.53, 3.28, 3.46, 3.76])
        assessment = assess_synced_timing(verses, voice)
        self.assertEqual(assessment['status'], 'incompatible')
        self.assertEqual(assessment['checked_verses'], 6)
        self.assertGreater(assessment['median_offset_seconds'], 3)
        self.assertEqual(verses[0]['start'], 7.09)  # Never shift provider clocks.

    def test_compatible_lyrics_tolerate_small_whisper_error_and_one_outlier(self):
        verses, voice = self.timing_fixture([.2, -.15, .4, .3, .1, 4])
        self.assertEqual(assess_synced_timing(verses, voice)['status'], 'consistent')
        scope, _ = self.run_stage(cache_version=3, verses=verses, voice=voice)
        self.assertEqual(scope['segments'][0]['start'], voice[0]['start'])
        self.assertNotIn('synced_line', scope['segments'][0])

    def test_incompatible_clock_is_rejected_in_both_directions(self):
        for shift in [-3, 4]:
            verses, voice = self.timing_fixture([shift] * 6)
            with self.subTest(shift=shift):
                self.assertEqual(assess_synced_timing(verses, voice)['status'], 'incompatible')

    def test_uncertain_recognition_does_not_move_or_reject_a_verse(self):
        verses, voice = self.timing_fixture([4] * 6)
        self.assertEqual(assess_synced_timing(verses, voice[:1])['status'], 'inconclusive')
        self.assertEqual(assess_synced_timing(verses, [])['status'], 'inconclusive')

    def test_repeated_choruses_are_compared_to_the_nearest_occurrence(self):
        verses = [dict(start=10 + i * 30, end=15 + i * 30, text='Mesmo verso cantado')
                  for i in range(6)]
        voice = [dict(words=[dict(word=token, start=verse['start'] + .2 + j * .4,
                                 end=verse['start'] + .6 + j * .4)
                             for j, token in enumerate(verse['text'].split())])
                 for verse in verses]
        self.assertEqual(assess_synced_timing(verses, voice)['status'], 'consistent')

    def test_incompatible_lrc_cannot_override_whisper_clocks(self):
        verses, voice = self.timing_fixture([4.13, 2.33, 2.53, 3.28, 3.46, 3.76])
        scope, transcriber = self.run_stage(cache_version=3, verses=verses, voice=voice)
        transcriber.assert_not_called()
        self.assertEqual(scope['synced_segments'], verses)
        self.assertAlmostEqual(scope['segments'][0]['start'], 11.22)
        self.assertNotIn('synced_line', scope['segments'][0])
        self.assertEqual([s['text'] for s in scope['segments']], [s['text'] for s in verses])
        self.assertEqual(len(scope['notify_targets'].call_args_list), 0)  # Acoustic cache needs no decode notice.
        scope['update_process_summary'].assert_called_once()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'fallback.ass'
            generate_ass_karaoke(scope['segments'], str(target), show_instrumental=False)
            output = target.read_text()
        self.assertNotIn('0:00:07.09', output)
        self.assertIn('0:00:11.22,', output)

    def test_real_cover_shifts_audio_and_animated_lyric_together(self):
        # All lyric/Whisper clocks are relative to the song, excluding the cover.
        verses = [dict(start=2, end=3, text='Hello world')]
        voice = [dict(words=[dict(word='Hello', start=2.2, end=2.5),
                            dict(word='world', start=2.5, end=2.8)])]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target, audio, cover, output = [root / name for name in
                                          ('lyric.ass', 'voice.wav', 'cover.png', 'result.mp4')]
            generate_ass_karaoke(anchor_synced_animation(verses, voice), str(target),
                                 font_size=60, show_instrumental=False)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'aevalsrc=if(between(t\\,2.2\\,2.8)\\,0.3*sin(2*PI*440*t)\\,0):s=44100:d=4',
                '-ac', '2', str(audio)], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'color=red:s=320x180', '-frames:v', '1', '-threads', '1', str(cover)], check=True)
            command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                'color=black:s=320x180:r=25:d=4', '-i', str(audio), '-vf', 'ass=' + str(target),
                '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'ultrafast',
                '-c:a', 'aac', '-b:a', '192k', '-t', '4', str(output)]
            subprocess.run(add_cover_to_command(command, cover, 4), check=True)
            def frame(time):
                return subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', str(time),
                    '-i', str(output), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
            before, after = frame(4.9), frame(5.7)
            self.assertEqual(sum(min(before[i:i+3]) > 220 for i in range(0, len(before), 3)), 0)
            self.assertGreater(sum(max(after[i:i+3]) > 220 for i in range(0, len(after), 3)), 10)
            samples = array.array('f', subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
                str(output), '-vn', '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']))
            def rms(start, end):
                chunk = samples[int(start * 16000):int(end * 16000)]
                return (sum(value * value for value in chunk) / len(chunk)) ** .5
            self.assertLess(rms(0, 3), .001)  # Silent title opening.
            self.assertLess(rms(4.8, 5), .001)
            self.assertGreater(rms(5.3, 5.7), .1)  # Voice clock 2.3 + 3-second cover.

    def test_animation_preserves_short_word_long_word_and_silent_gap(self):
        scope, _ = self.run_stage()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'karaoke.ass'
            generate_ass_karaoke(scope['segments'], str(target), show_instrumental=False,
                                 break_on_punctuation=False)
            output = target.read_text()
        self.assertIn(r'\kt0\kf30', output)
        self.assertNotIn(r'\h', output)
        self.assertNotIn(r'\alpha&HFF&', output)
        self.assertIn('0:00:10.20,0:00:12.50', output)
        self.assertNotIn(r'\clip', output)
        self.assertIn(r'\kt140\kf90', output)
        self.assertNotIn(r'{\kf300}Olá mundo', output)

    def test_repeated_verses_keep_provider_clocks_and_match_only_local_words(self):
        verses = [{'start':10,'end':13,'text':'Olá mundo'},
                  {'start':30,'end':33,'text':'Olá mundo'}]
        acoustic = [{'words':[{'word':' Olá','start':10.2,'end':10.5},
                              {'word':' mundo','start':11.6,'end':12.5},
                              {'word':' Olá','start':30.5,'end':31},
                              {'word':' mundo','start':31.6,'end':32.5}]}]
        anchored = anchor_synced_animation(verses, acoustic)
        self.assertEqual(anchored[1]['words'][0]['start'], 30.5)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'repeated.ass'
            generate_ass_karaoke(anchored, str(target), show_instrumental=False,
                                 subtitle_mode='syllable', words_per_line=1)
            output = target.read_text()
        self.assertIn('0:00:10.00,0:00:13.00', output)
        self.assertNotIn('0:00:10.00,0:00:30.00', output)
        self.assertIn('0:00:30.00,0:00:33.00', output)
        self.assertIn(r'\kt20\kf30', output)

    def test_unrecognized_words_preserve_complete_lyrics_without_assigned_clocks(self):
        verses = [{'start':10,'end':13,'text':'Olá lindo mundo'}]
        acoustic = [{'words':[{'word':'Olá','start':10.2,'end':10.5},
                              {'word':'mundo','start':11.6,'end':12.5}]}]
        anchored = anchor_synced_animation(verses, acoustic)
        self.assertEqual(anchored[0]['text'], 'Olá lindo mundo')
        self.assertEqual(anchored[0]['animation_words'][2], {'word':'mundo'})
        self.assertEqual(len(anchored[0]['words']), 2)
        self.assertEqual(anchored[0]['end'], 13)

    def test_review_preserves_provider_verse_clocks_and_acoustic_animation(self):
        resume = load_function('continue_process', ContinueProcessModel=object,
            require_task_control=Mock(), segments_to_edit=[{'text':'original'}],
            correction_event=Mock(), anchor_synced_animation=anchor_synced_animation)
        words = [SimpleNamespace(word='Olá ',start=10.2,end=10.5),
                 SimpleNamespace(word='mundo',start=11.6,end=12.5)]
        resume(SimpleNamespace(segments=[SimpleNamespace(text='Olá lindo mundo', start=10,end=13,
                    words=words,synced_line=True,acoustic_animation=True)]), {})
        revised = resume.__globals__['segments_to_edit'][0]
        self.assertEqual((revised['start'], revised['end']), (10,13))
        self.assertEqual([(w['start'],w['end']) for w in revised['words']], [(10.2,10.5),(11.6,12.5)])
        self.assertEqual(revised['animation_words'][2], {'word':'mundo'})

    def test_long_verse_never_disappears_or_changes_layout_during_animation(self):
        verses = parse_lrc('[00:00]Full verse stays visible, unchanged!\n[00:20]Second verse', 25)
        self.assertEqual(verses[0]['end'], 20)
        acoustic = [dict(words=[dict(word='wrong', start=13+i*.7, end=13.4+i*.7)
                               for i in range(5)])]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'stable.ass'
            generate_ass_karaoke(anchor_synced_animation(verses, acoustic), str(target),
                                 font_size=32, show_instrumental=False, show_next_line_preview=False,
                                 words_per_line=1, max_chars_line=3)
            content = target.read_text()
            first = next(line for line in content.splitlines() if line.startswith('Dialogue:'))
            rendered_text = re.sub(r'\{[^}]*\}', '', first.split(',',9)[-1]).replace(r'\N', '')
            self.assertEqual(rendered_text, verses[0]['text'])
            masks = []
            for time in (.1, 12.5, 15, 19.8):
                raw = subprocess.check_output(['ffmpeg','-v','error','-f','lavfi','-i',
                    'color=c=black:s=640x360:r=25:d=21','-vf','ass='+str(target),'-ss',str(time),
                    '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                masks.append(bytes(max(raw[i:i+3]) > 50 for i in range(0,len(raw),3)))
            self.assertGreater(sum(masks[0]),100)
            bounds = []
            for mask in masks:
                pixels = [i for i, visible in enumerate(mask) if visible]
                bounds.append((min(i % 640 for i in pixels), min(i // 640 for i in pixels),
                               max(i % 640 for i in pixels), max(i // 640 for i in pixels)))
            # Color conversion changes antialiasing at glyph edges by one pixel.
            for left, top, right, bottom in bounds[1:]:
                self.assertLessEqual(abs(left - bounds[0][0]), 1)
                self.assertLessEqual(abs(right - bounds[0][2]), 1)
                self.assertLessEqual(abs(top - bounds[0][1]), 1)
                self.assertLessEqual(abs(bottom - bounds[0][3]), 1)
            self.assertLess(max(map(sum, masks)) / min(map(sum, masks)), 1.15)

    def test_ffmpeg_highlight_stops_during_whisper_pause_inside_fixed_verse(self):
        verses = [{'start':0,'end':3,'text':'Hello world'}]
        acoustic = [{'words':[{'word':'Hello','start':0.2,'end':0.5},
                              {'word':'world','start':1.6,'end':2.5}]}]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'pause.ass'
            generate_ass_karaoke(anchor_synced_animation(verses,acoustic), str(target),
                font_size=24, show_instrumental=False, show_next_line_preview=False)
            def highlight_amount(time):
                raw = subprocess.check_output(['ffmpeg','-v','error','-f','lavfi','-i',
                    'color=c=black:s=640x360:r=25:d=3','-vf','ass='+str(target),'-ss',str(time),
                    '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
                # Measure color across antialiased glyphs too. At a 12px
                # rendered font some platforms have very few solid pixels.
                return sum(max(0, (raw[i+1] + raw[i+2]) // 2 - raw[i]) for i in range(0,len(raw),3))
            before, during, gap_start, gap_end, after = map(highlight_amount, [0.1,0.35,0.6,1.2,2.6])
        self.assertEqual(before, 0)
        self.assertGreater(during, before)
        self.assertLess(during, gap_start)
        self.assertGreater(gap_start, before)
        self.assertEqual(gap_start, gap_end)
        self.assertGreater(after, gap_end)

    def test_missing_or_invalid_word_clocks_fail_instead_of_artificial_animation(self):
        for segments in ([], [{'words':[]}], [{'words':[{'start':float('nan'),'end':2}]}],
                         [{'words':[{'start':3,'end':2}]}]):
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                require_acoustic_word_timing(segments)


if __name__ == '__main__':
    unittest.main()
