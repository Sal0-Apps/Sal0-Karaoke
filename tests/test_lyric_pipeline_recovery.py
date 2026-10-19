"""12.7.1 must not filter reviews or reuse its fragmented subtitle checkpoint."""
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from karaoke_generator import generate_ass_karaoke
from lyric_alignment import QUALITY_VERSION
from test_automatic_lyrics_and_search import load_function


class LyricPipelineRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = [dict(start=1, end=4, text='Minha frase completa', words=[
            dict(word='Minha', start=1, end=1.4),
            dict(word=' frase', start=2, end=2.4),
            dict(word=' completa', start=3, end=4)])]

    def run_render_stage(self, activity=None, checkpoint=None):
        main = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        stage = main[main.index('            # Passo 4: Gerar legendas ASS'):
                     main.index('            # Passo 5: Renderizar o vídeo final')]
        generator = Mock(wraps=generate_ass_karaoke)
        scope = dict(os=os, cache_dir=str(self.root), segments=copy.deepcopy(self.source),
            lyrics_text='Uma guia diferente da revisão manual',
            instrumental_wav='instrumental.wav', get_file_duration=lambda _: 5,
            queue_cache=SimpleNamespace(read_json=lambda *args: activity or {}),
            stage_checkpoint=lambda *args: checkpoint() if checkpoint else {},
            pm=SimpleNamespace(check_cancelled=Mock()),
            update_state=Mock(), notify_targets=Mock(), telegram_targets=[], telegram_notice=Mock(),
            generate_ass_karaoke=generator, save_stage_checkpoint=Mock(), font_size=50,
            text_color='#00FFFF', text_position='middle', subtitle_mode='syllable',
            words_per_line=0, max_chars_line=0, break_on_punctuation=True,
            show_instrumental=False, show_next_line_preview=False, keep_first_line_visible=False,
            karaoke_visual_settings={'animation_style': 'classic'})
        with patch('lyric_alignment.refine_lyrics') as refine:
            exec(compile(textwrap.dedent(stage), 'render-stage-recovery', 'exec'), scope)
        refine.assert_not_called()
        return generator

    def test_rendering_a_review_keeps_its_complete_text_and_does_not_rerun_models(self):
        generator = self.run_render_stage(dict(report=dict(version=QUALITY_VERSION), voice_regions=[]))
        self.assertEqual(generator.call_args.kwargs['segments'], self.source)
        self.assertNotIn('strict_guide', generator.call_args.kwargs)
        events = [line for line in (self.root / 'karaoke.ass').read_text(encoding='utf-8').splitlines()
                  if line.startswith('Dialogue:')]
        self.assertEqual(len(events), 1)
        plain = re.sub(r'\{[^}]*\}', '', events[0].split(',', 9)[-1])
        self.assertEqual(plain.replace(r'\N', ' '), self.source[0]['text'])
        self.assertIn(',0:00:01.00,0:00:04.00,', events[0])

    def test_strict_quality_four_activity_is_not_reused_after_the_rollback(self):
        generator = self.run_render_stage(dict(report=dict(version=4), voice_regions=[]))
        self.assertIsNone(generator.call_args.kwargs['voice_regions'])

    def test_display_policy_upgrade_rebuilds_fragmented_ass_and_keeps_raw_and_review(self):
        checkpoint = self.root / 'stage_checkpoints.json'
        checkpoint.write_text(json.dumps(dict(completed_stages={name: {'saved': True} for name in
            ('transcription_ready', 'transcription_reviewed', 'subtitles_generated', 'video_rendered')})))
        raw, review = self.root / 'transcribed_segments.json', self.root / 'reviewed_segments.json'
        for path in (raw, review):
            path.write_text(json.dumps(self.source))
        (self.root / 'karaoke.ass').write_text('fragmented old ass')
        load = load_function('load_stage_checkpoints', os=os, json=json)
        invalidate = load_function('invalidate_subtitle_display_cache', os=os, json=json,
            load_stage_checkpoints=load)
        meta = dict(subtitle_display_options=dict(version=7, guide_contract=2))
        self.assertTrue(invalidate(str(self.root), meta, dict(version=8)))
        saved = json.loads(checkpoint.read_text())['completed_stages']
        self.assertEqual(set(saved), {'transcription_ready', 'transcription_reviewed'})
        generator = self.run_render_stage(checkpoint=lambda: load(str(self.root)).get('completed_stages', {}).get('subtitles_generated'))
        generator.assert_called_once()
        for path in (raw, review):
            self.assertEqual(json.loads(path.read_text()), self.source)
        self.assertFalse(invalidate(str(self.root), meta, dict(version=8)))


if __name__ == '__main__':
    unittest.main()
