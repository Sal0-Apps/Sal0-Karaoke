import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from guided_output import finalize_guided_output
from lyric_guide import prepare_lyrics_guide


def spoken(text):
    words = [dict(word=' '+word, start=1+i*.3, end=1.2+i*.3) for i, word in enumerate(text.split())]
    return [dict(start=words[0]['start'], end=words[-1]['end'], text=text, words=words)]


class GuidedOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / 'vocals.wav'
        self.audio.write_bytes(b'fixture')
        self.report = dict(voice_regions=[(1, 4)], status='aligned', strict_voice_policy=1)

    def test_without_a_guide_does_not_change_speech_or_run_a_voice_model(self):
        source = spoken('palavras livres aqui')
        with patch('lyric_alignment.validate_display_evidence', create=True) as voice:
            result, report = finalize_guided_output('missing.wav', source, '', self.root)
        voice.assert_not_called()
        self.assertIs(result, source)
        self.assertEqual(report, {})

    def test_backend_fallback_cannot_reintroduce_words_outside_the_guide(self):
        source = spoken('fantasma eu canto aqui')
        with patch('lyric_alignment.validate_display_evidence', create=True, return_value=(source, self.report)):
            result, report = finalize_guided_output(self.audio, source, 'Eu canto aqui', self.root)
        self.assertNotIn('fantasma', ' '.join(segment['text'] for segment in result))
        self.assertEqual({word['word'].strip().lower() for segment in result for word in segment['words']}, {'eu', 'canto', 'aqui'})
        self.assertTrue(report['strict_signature'])
        self.assertIn('fantasma', source[0]['text'])

    def test_unrelated_guide_invalidates_old_render_instead_of_showing_asr(self):
        source = spoken('fantasmas inventados juntos')
        checkpoint = self.root / 'stage_checkpoints.json'
        checkpoint.write_text(json.dumps(dict(completed_stages=dict(transcription_reviewed={'saved': True},
            subtitles_generated={'saved': True}, video_rendered={'saved': True}))))
        with patch('lyric_alignment.validate_display_evidence', create=True, return_value=(source, self.report)):
            with self.assertRaisesRegex(ValueError, 'letra-guia'):
                finalize_guided_output(self.audio, source, 'Eu canto aqui', self.root)
        saved = json.loads(checkpoint.read_text())['completed_stages']
        self.assertIn('transcription_reviewed', saved)
        self.assertNotIn('video_rendered', saved)
        self.assertNotIn('subtitles_generated', saved)
        self.assertEqual(json.loads((self.root/'display_segments.json').read_text()), [])

    def test_final_postcondition_preserves_the_acoustic_pass_omission_report(self):
        from lyric_guide import enforce_guide_text
        source, _ = enforce_guide_text('eu canto aqui', spoken('eu canto aqui'))
        report = dict(self.report, guide_contract=dict(status='filtered', removed_words=3, corrected_words=1))
        with patch('lyric_alignment.validate_display_evidence', return_value=(source, report)):
            _, final = finalize_guided_output(self.audio, source, 'eu canto aqui', self.root)
        self.assertEqual(final['guide_contract']['removed_words'], 3)
        self.assertEqual(final['guide_contract']['corrected_words'], 1)
        self.assertEqual(final['final_postcondition']['removed_words'], 0)

    def test_same_validated_output_reuses_render_but_changed_output_rebuilds_it(self):
        source = spoken('eu canto aqui')
        review = self.root / 'review_draft.json'; review.write_text('human original')
        with patch('lyric_alignment.validate_display_evidence', create=True, return_value=(source, self.report)):
            finalize_guided_output(self.audio, source, 'eu canto aqui', self.root)
            checkpoint = self.root / 'stage_checkpoints.json'
            checkpoint.write_text(json.dumps(dict(completed_stages=dict(video_rendered={'saved': True}))))
            finalize_guided_output(self.audio, source, 'eu canto aqui', self.root)
            self.assertIn('video_rendered', json.loads(checkpoint.read_text())['completed_stages'])
            shifted = copy.deepcopy(source); shifted[0]['words'][0]['start'] += .02
            with patch('lyric_alignment.validate_display_evidence', return_value=(shifted, self.report)):
                finalize_guided_output(self.audio, shifted, 'eu canto aqui', self.root)
            self.assertNotIn('video_rendered', json.loads(checkpoint.read_text())['completed_stages'])
        self.assertEqual(review.read_text(), 'human original')

    def test_pipeline_checks_final_review_before_accepting_old_ass_checkpoint(self):
        main = (Path(__file__).parents[1] / 'app/main.py').read_text(encoding='utf-8')
        stage = main[main.index('            # Passo 4: Gerar legendas ASS'):
                     main.index('            # Passo 5: Renderizar o vídeo final')]
        source = spoken('fantasma eu canto aqui')
        (self.root / 'karaoke.ass').write_text('OLD INVALID ASS')
        checkpoint = self.root / 'stage_checkpoints.json'
        checkpoint.write_text(json.dumps(dict(completed_stages=dict(subtitles_generated={'saved': True}, video_rendered={'saved': True}))))
        generate = Mock()
        scope = dict(os=os, cache_dir=str(self.root), cached_meta={}, segments=source,
            lyrics_text='eu canto aqui', prepare_lyrics_guide=prepare_lyrics_guide,
            vocals_wav=str(self.audio), instrumental_wav='instrumental.wav',
            get_file_duration=lambda _:4, pm=SimpleNamespace(check_cancelled=Mock()),
            update_process_summary=Mock(), update_state=Mock(), notify_targets=Mock(),
            telegram_targets=[], telegram_notice=Mock(), stage_checkpoint=lambda _, name:
                json.loads(checkpoint.read_text()).get('completed_stages', {}).get(name, {}),
            generate_ass_karaoke=generate, save_stage_checkpoint=Mock(), font_size=50,
            text_color='#00FFFF', text_position='middle', subtitle_mode='syllable',
            words_per_line=0, max_chars_line=0, break_on_punctuation=True,
            show_instrumental=False, show_next_line_preview=True, keep_first_line_visible=True,
            karaoke_visual_settings={})
        with patch('lyric_alignment.validate_display_evidence', create=True, return_value=(source, self.report)):
            exec(compile(textwrap.dedent(stage), 'final-pipeline-stage', 'exec'), scope)
        generate.assert_called_once()
        rendered = generate.call_args.kwargs
        self.assertTrue(rendered['strict_guide'])
        self.assertNotIn('fantasma', ' '.join(segment['text'] for segment in rendered['segments']))
        self.assertEqual(rendered['voice_regions'], [(1, 4)])


if __name__ == '__main__':
    unittest.main()
