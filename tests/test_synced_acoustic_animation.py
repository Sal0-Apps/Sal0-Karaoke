"""Synced lyrics must use recording word clocks, including cache and ASS gaps."""
import hashlib
import json
import logging
import os
import sys
import tempfile
import textwrap
import unittest
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from lyrics_sync import parse_lrc, require_acoustic_word_timing
from karaoke_generator import generate_ass_karaoke
from test_automatic_lyrics_and_search import load_function


class SyncedAcousticAnimationTests(unittest.TestCase):
    def run_stage(self, cache_version=None):
        source = (ROOT / 'app/main.py').read_text()
        stage = source[source.index('            segments = None\n', source.index('# Passo 3: Transcrever vocais')):
                       source.index('            # --- NOVO: Passo de Pausa')]
        lrc = parse_lrc('[00:10]Olá mundo\n[00:13]Outra linha\n[00:17]', 20)
        acoustic = [{'start':10.2,'end':12.5,'text':' Ola mundo', 'words':[
            {'word':' Ola','start':10.2,'end':10.5},
            {'word':' mundo','start':11.6,'end':12.5}]}]
        with tempfile.TemporaryDirectory() as folder:
            cached = acoustic if cache_version == 2 else lrc
            (Path(folder) / 'transcribed_segments.json').write_text(json.dumps(cached))
            meta = dict(animation_timing_version=cache_version, vocal_source='lead',
                        transcribe_source='vocals', whisper_model='medium', enable_vad=True,
                        transcription_preset='standard', lyrics_hint_hash=hashlib.sha256('Olá mundo\nOutra linha'.encode()).hexdigest())
            transcriber = Mock(return_value=acoustic)
            scope = dict(os=os, hashlib=hashlib, json=json, synced_segments=lrc,
                lyrics_text='original guide', cache_dir=folder, cached_meta=meta,
                cache_meta_file=str(Path(folder) / 'meta.json'), vocal_source='lead',
                transcribe_source='vocals', whisper_model='medium', enable_vad=True,
                transcription_preset='standard', vocals_wav='lead.wav', converted_wav='mix.wav',
                pm=SimpleNamespace(check_cancelled=Mock()), update_state=Mock(),
                notify_targets=Mock(), telegram_targets=[], orig_name='song',
                telegram_notice=lambda *parts: ' '.join(parts), telegram_escape=str,
                logger=logging.getLogger('test'), is_model_downloaded=lambda _:True,
                transcribe_vocals=transcriber, save_stage_checkpoint=Mock(),
                align_lyrics=load_function('align_lyrics', clean_word=load_function('clean_word', unicodedata=unicodedata)), require_acoustic_word_timing=require_acoustic_word_timing)
            exec(compile(textwrap.dedent(stage), 'transcription-stage', 'exec'), scope)
        return scope, transcriber

    def test_synced_lyrics_do_not_bypass_voice_analysis_or_reuse_verse_only_cache(self):
        scope, transcriber = self.run_stage()
        transcriber.assert_called_once()
        self.assertEqual(transcriber.call_args.kwargs['initial_prompt'], 'Olá mundo\nOutra linha')
        words = scope['segments'][0]['words']
        self.assertEqual([(w['start'],w['end']) for w in words], [(10.2,10.5),(11.6,12.5)])
        self.assertEqual(words[0]['word'], ' Olá')
        notices = scope['notify_targets'].call_args_list
        self.assertEqual(len(notices), 1)
        self.assertIn('Sincronização da animação pela voz', notices[0].args[1])

    def test_current_acoustic_cache_is_reused(self):
        scope, transcriber = self.run_stage(cache_version=2)
        transcriber.assert_not_called()
        self.assertEqual(scope['segments'][0]['words'][1]['start'], 11.6)

    def test_animation_preserves_short_word_long_word_and_silent_gap(self):
        scope, _ = self.run_stage()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'karaoke.ass'
            generate_ass_karaoke(scope['segments'], str(target), show_instrumental=False,
                                 break_on_punctuation=False)
            output = target.read_text()
        self.assertIn(r'{\kf30}Olá', output)
        self.assertIn(r'{\k110\alpha&HFF&}\h', output)
        self.assertIn(r'{\kf90}mundo', output)
        self.assertNotIn(r'{\kf300}Olá mundo', output)

    def test_missing_or_invalid_word_clocks_fail_instead_of_artificial_animation(self):
        for segments in ([], [{'words':[]}], [{'words':[{'start':float('nan'),'end':2}]}],
                         [{'words':[{'start':3,'end':2}]}]):
            with self.subTest(segments=segments), self.assertRaises(ValueError):
                require_acoustic_word_timing(segments)


if __name__ == '__main__':
    unittest.main()
