"""Recover complete lyrics; weak speech CTC/VAD must not erase sung refrains."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]/'app'))
from full_guide_alignment import align_guide_with_whisper, alignment_lines, refine_confirmed_clocks, singing_activity, mark_confirmed_lines
from lyric_alignment import refine_lyrics, roman_word, AudioEvidence
from karaoke_generator import generate_ass_karaoke, insert_instrumental_breaks


def verse(text, start):
    return [dict(word=' '+word, start=start+i*.43, end=start+i*.43+.12+(i % 2)*.07,
                 probability=.9) for i, word in enumerate(text.split())]


class AcousticFixture:
    """Independent measured clocks for the requested text, including omissions."""
    def __init__(self, actual, probability=.9, cancel=lambda: None):
        self.actual = actual; self.probability = probability; self.cancel = cancel

    def align(self, audio, left, right, words):
        self.cancel()
        wanted = [' '+word for word in words]
        candidates = [self.actual[i:i+len(words)] for i in range(len(self.actual)-len(words)+1)
                      if [w['word'] for w in self.actual[i:i+len(words)]] == wanted]
        if not candidates:
            return None
        selected = copy.deepcopy(min(candidates, key=lambda part: abs(part[0]['start']-left)))
        for word in selected:
            word['probability'] = self.probability
        return selected


class CompleteGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root/'source.wav'; self.source.write_bytes(b'audio')
        self.lines = ['Guarde esta luz acesa', 'Encontro você na estrada', 'Guarde esta luz acesa']
        self.guide = '\n'.join(self.lines)
        self.actual = verse(self.lines[0], 1)+verse(self.lines[1], 6)+verse(self.lines[2], 12)
        self.audio = np.full(16*16000, .1, dtype=np.float32)

    def run_guide(self, baseline=None, probability=.9, cancel=lambda: None):
        words = baseline if baseline is not None else self.actual
        segments = [dict(start=words[0]['start'], end=words[-1]['end'], words=words)] if words else []
        factory = lambda *args: AcousticFixture(self.actual, probability, cancel)
        return align_guide_with_whisper(self.source, segments, self.guide, self.root, 'medium',
            decode=lambda _: self.audio, backend_factory=factory, cancel=cancel)

    def test_whole_missing_verse_and_missing_refrain_words_get_acoustic_clocks(self):
        source = self.actual[:2]+self.actual[8:]; before = copy.deepcopy(source)
        result, report = self.run_guide(source)
        output = [w for s in result for w in s['words']]
        self.assertEqual([w['word'] for w in output], [w['word'] for w in self.actual])
        self.assertEqual([(w['start'], w['end']) for w in output],
                         [(w['start'], w['end']) for w in self.actual])
        self.assertEqual(report['recovered_words'], 6)
        self.assertEqual(report['guide_aligned_words'], 12)
        self.assertEqual(source, before)

    def test_every_refrain_is_a_separate_acoustic_occurrence(self):
        result, report = self.run_guide(self.actual[:4])
        self.assertEqual([s['start'] for s in result], [1, 6, 12])
        self.assertEqual(report['status'], 'aligned')

    def test_guide_printed_once_cannot_erase_an_unprinted_sung_repeat(self):
        self.guide = self.lines[0]
        source = self.actual[:4]+self.actual[8:]
        result, report = self.run_guide(source)
        self.assertEqual(result[0]['words'], source)
        self.assertEqual(report['status'], 'incomplete_guide')

    def test_weak_audio_evidence_preserves_the_recognized_recording(self):
        result, report = self.run_guide(probability=.01)
        self.assertEqual(result[0]['words'], self.actual)
        self.assertEqual(report['status'], 'partial')
        self.assertFalse((self.root/'guided_whisper_lyrics.json').exists())

    def test_empty_whisper_can_recover_a_bounded_recording_from_its_audio(self):
        result, report = self.run_guide([])
        self.assertEqual(sum(len(s['words']) for s in result), 12)
        self.assertEqual(report['recovered_words'], 12)

    def test_cache_reuse_never_reloads_the_whisper_model(self):
        first, report = self.run_guide()
        unavailable = Mock(side_effect=AssertionError('must reuse measured clocks'))
        source = [dict(start=self.actual[0]['start'], end=self.actual[-1]['end'], words=self.actual)]
        cached, _ = align_guide_with_whisper(self.source, source, self.guide, self.root, 'medium',
                                           backend_factory=unavailable)
        self.assertEqual(first, cached); unavailable.assert_not_called()
        self.assertEqual(report['status'], 'aligned')

    def test_changed_model_or_guide_invalidates_the_known_text_cache(self):
        self.run_guide()
        unavailable = Mock(side_effect=RuntimeError('changed model'))
        with self.assertRaisesRegex(RuntimeError, 'changed model'):
            align_guide_with_whisper(self.source, [], self.guide, self.root, 'large-v3',
                decode=lambda _: self.audio, backend_factory=unavailable)

    def test_cancel_never_publishes_a_partial_guide_cache(self):
        cancel = Mock(side_effect=InterruptedError('cancelado'))
        with self.assertRaises(InterruptedError):
            self.run_guide(cancel=cancel)
        self.assertFalse((self.root/'guided_whisper_lyrics.json').exists())

    def test_a_collapsed_word_retries_with_context_instead_of_losing_the_refrain(self):
        actual, calls = self.actual, []
        class Retry(AcousticFixture):
            def align(self, audio, left, right, words):
                result = super().align(audio, left, right, words)
                calls.append((left, right))
                if len(calls) == 1:
                    result[0]['end'] = result[0]['start']
                return result
        baseline = [dict(start=self.actual[0]['start'], end=self.actual[-1]['end'], words=self.actual)]
        result, report = align_guide_with_whisper(self.source, baseline, self.guide, self.root, 'medium',
            decode=lambda _: self.audio, backend_factory=lambda *_: Retry(actual))
        self.assertEqual(report['status'], 'aligned')
        self.assertEqual(report['guide_line_checks'][0]['attempts'], 2)
        self.assertEqual(sum(len(s['words']) for s in result), 12)

    def test_external_lrc_clocks_are_ignored_and_every_printed_repeat_survives(self):
        self.assertEqual(alignment_lines('[99:00]Luz acesa\n[Refrão]\n[00:01]Luz acesa', roman_word),
                         [['Luz', 'acesa'], ['Luz', 'acesa']])
        self.assertEqual(alignment_lines('日本語', roman_word), [])

    def test_wrong_long_song_without_anchors_cannot_supply_lyrics(self):
        self.audio = np.ones(40*16000, dtype=np.float32)
        result, report = self.run_guide(verse('Uma outra canção qualquer', 1))
        self.assertEqual(report['status'], 'unconfirmed')
        self.assertEqual(result[0]['words'][0]['word'], ' Uma')

    def test_weak_ctc_and_empty_speech_vad_do_not_erase_confirmed_singing(self):
        confirmed, _ = self.run_guide(self.actual[:2]+self.actual[8:])
        actual = self.actual
        class WeakCTC:
            def __init__(self, *_): pass
            def full_emission(self, audio, progress): return None
            def align_guide(self, emission, lines):
                return [dict(w, alignment_score=.0001) for w in actual]
            def close(self): pass
        result, report = refine_lyrics(self.source, confirmed, self.guide, self.root,
            decode=lambda _: self.audio, backend_factory=WeakCTC, voice_regions=[])
        output = [w for s in result for w in s['words']]
        self.assertEqual([w['word'] for w in output], [w['word'] for w in self.actual])
        self.assertEqual(report['unsupported_voice_words'], 0)
        self.assertEqual(report['aligned_words'], 12)

    def test_ctc_failure_keeps_the_confirmed_guide_and_marks_a_retry(self):
        confirmed, _ = self.run_guide()
        unavailable = Mock(side_effect=RuntimeError('CTC unavailable'))
        result, report = refine_lyrics(self.source, confirmed, self.guide, self.root,
            decode=lambda _: self.audio, backend_factory=unavailable)
        self.assertEqual(sum(len(s['words']) for s in result), 12)
        self.assertEqual(report['status'], 'fallback')

    def test_instrumental_pause_is_recovered_without_an_early_bridge(self):
        confirmed, _ = self.run_guide()
        confirmed[2]['words'][0]['start'] = 8.; confirmed[2]['start'] = 8.
        ctc = [dict(word, alignment_score=.8, alignment_chars=[]) for word in self.actual]
        result, count = refine_confirmed_clocks(confirmed, ctc)
        self.assertEqual(result[2]['start'], 12.)
        target = self.root/'instrumental.ass'
        generate_ass_karaoke(result, str(target), show_instrumental=True, media_duration=16)
        self.assertIn('Instrumental', target.read_text())
        self.assertEqual(count, 12)

    def test_ctc_cannot_move_a_chorus_word_into_the_next_refrain(self):
        confirmed, _ = self.run_guide()
        ctc = [dict(word, alignment_score=.8, alignment_chars=[]) for word in self.actual]
        ctc[0].update(start=12., end=12.3)
        result, _ = refine_confirmed_clocks(confirmed, ctc)
        self.assertEqual(result[0]['words'][0]['start'], 1.)

    def test_complete_verse_is_not_split_by_other_short_lines_in_the_same_guide(self):
        lines = ['Luz acesa', 'Luz acesa quando eu voltar', 'quando eu voltar']
        confirmed = []
        offset = 0
        for index, line in enumerate(lines):
            words = verse(line, 1+index*4)
            for word in words:
                word.update(guide_token_index=offset, guide_audio_confirmed=True); offset += 1
            confirmed.append(dict(start=words[0]['start'], end=words[-1]['end'], words=words,
                                  guide_audio_confirmed=True))
        with patch.dict('os.environ', {'KARAOKE_ALIGNMENT': 'off'}):
            result, _ = refine_lyrics(self.source, confirmed, '\n'.join(lines), self.root,
                                     decode=lambda _: self.audio)
        self.assertEqual([segment['text'] for segment in result], lines)

    def test_held_sung_note_prevents_instrumental_notice_and_preserves_its_verse(self):
        from test_guided_silence_render import events
        frames = 800
        edges = np.linspace(0, 16, frames+1); centers = (edges[:-1]+edges[1:])/2
        values = np.full((frames, 28), -30., dtype=np.float32); values[:, 0] = 0.
        values[(centers >= 1)&(centers < 5.6), 0] = np.log(.97)
        words = [dict(word=' Luz', start=1., end=2., guide_audio_confirmed=True)]
        source = [dict(start=1., end=2., text='Luz', words=words),
                  dict(start=13., end=14., text='Voltei', words=[dict(word=' Voltei', start=13., end=14.)])]
        source = mark_confirmed_lines(source)
        regions = singing_activity((values, edges), AudioEvidence(self.audio), source)
        cues = insert_instrumental_breaks(source, media_duration=16, voice_regions=regions)
        self.assertFalse(any(s.get('instrumental') and s['start'] < 5.5 and s['end'] > 2 for s in cues))
        self.assertTrue(any(s.get('instrumental') and s['start'] <= 8 < s['end'] for s in cues))
        target = self.root/'held-note.ass'
        generate_ass_karaoke(source, str(target), show_instrumental=True, media_duration=16, voice_regions=regions)
        rendered = events(target)
        verse = next(event for event in rendered if event['text'] == 'Luz')
        self.assertGreaterEqual(verse['end'], 5.5)
        self.assertLess(verse['end'], 6.)

    def test_instrumental_leakage_without_phone_posterior_does_not_hide_a_real_rest(self):
        edges = np.linspace(0, 16, 801)
        values = np.full((800, 28), -30., dtype=np.float32); values[:, 0] = 0.
        source = [dict(start=1., end=14., words=[])]
        self.assertEqual(singing_activity((values, edges), AudioEvidence(self.audio), source), [])


if __name__ == '__main__':
    unittest.main()
