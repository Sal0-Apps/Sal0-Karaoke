"""Guide words need vocal evidence even through fallback, cache and manual review."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
import lyric_alignment as alignment


def segments(text, start=1., step=.4, duration=.3):
    words = [dict(word=' '+token, start=start+index*step, end=start+index*step+duration)
             for index, token in enumerate(text.split())]
    return [dict(start=words[0]['start'], end=words[-1]['end'], text=text, words=words)]


class SupportedCTC:
    def __init__(self, *_):
        self.closed = False

    def emission(self, audio):
        return len(audio)/16000

    def align(self, emission, text):
        return [dict(word=' '+word, start=.45+index*.4, end=.75+index*.4,
                     alignment_score=.85) for index, word in enumerate(text)]

    def close(self):
        self.closed = True


class StrictVoiceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.path = self.cache/'vocals.wav'
        self.path.write_bytes(b'unchanged audio fixture')
        self.audio = (.001*np.sin(np.arange(12*16000)*.1)).astype(np.float32)
        self.audio[2*16000:4*16000] *= 100
        self.original_audio = self.audio.copy()
        self.context = dict(audio_hash='same recording')

    def refine(self, source, guide='voz', **options):
        options.setdefault('backend_factory', SupportedCTC)
        options.setdefault('decode', lambda _: self.audio)
        return alignment.refine_lyrics(self.path, source, guide, self.cache,
            context=self.context, **options)

    def test_guide_correction_is_not_reverted_to_the_out_of_guide_recognition(self):
        from lyric_guide import verify_lyrics_guide
        source = segments('eu quero gastar com voce nesta noite')
        guide = 'eu quero cantar com você nesta noite'
        checked, report = verify_lyrics_guide(guide, source)
        result = alignment.acoustic_baseline(checked, report['checks'], guide=guide)
        self.assertEqual(result, checked)
        self.assertNotIn('gastar', result[0]['text'])
        self.assertEqual(source[0]['text'], 'eu quero gastar com voce nesta noite')

    def test_model_failure_cannot_mistake_instrumental_leak_for_voice(self):
        source = segments('voz', .5)+segments('voz', 2.2)+segments('voz', 7)
        before = copy.deepcopy(source)
        result, report = self.refine(source, voice_regions=[(2,4)],
            backend_factory=Mock(side_effect=RuntimeError('model unavailable')))
        self.assertEqual([word['start'] for segment in result for word in segment['words']], [2.2])
        self.assertEqual(report['ambiguous_voice_words'], 2)
        self.assertEqual(report['status'], 'fallback')
        self.assertEqual(source, before)
        np.testing.assert_array_equal(self.audio, self.original_audio)
        self.assertEqual(self.path.read_bytes(), b'unchanged audio fixture')

    def test_no_voice_and_unavailable_detector_are_distinct_and_fail_safely(self):
        source = segments('voz', 2.2)
        for regions, expected in (([], 'no_voice'), (None, 'unavailable')):
            with self.subTest(regions=regions), patch.object(alignment, 'detect_voice_regions', return_value=None):
                result, report = self.refine(source, voice_regions=regions,
                    backend_factory=Mock(side_effect=RuntimeError('model unavailable')))
                self.assertEqual(result, [])
                self.assertEqual(report['voice_detector'], expected)
                self.assertEqual(report['voice_regions'], [])

    def test_explicit_empty_voice_result_is_not_treated_as_energy_evidence(self):
        factory = Mock(side_effect=AssertionError('disabled model cannot be loaded'))
        with patch.dict(alignment.os.environ, {'KARAOKE_ALIGNMENT':'off'}):
            result, report = self.refine(segments('voz', 2.2), voice_regions=[], backend_factory=factory)
        self.assertEqual(result, [])
        factory.assert_not_called()
        self.assertEqual(report['voice_detector'], 'no_voice')

    def test_unavailable_model_and_vad_do_not_trust_old_alignment_scores(self):
        source = segments('voz', 2.2)
        source[0]['words'][0]['alignment_score'] = 1.
        source[0]['words'][0]['_fresh_ctc_voice_score'] = 1.
        with patch.object(alignment, 'detect_voice_regions', return_value=None):
            result, _ = self.refine(source, backend_factory=Mock(side_effect=RuntimeError('missing')))
        self.assertEqual(result, [])

    def test_quiet_long_note_can_be_confirmed_by_ctc_when_speech_vad_misses_it(self):
        class HeldNote(SupportedCTC):
            def align(self, emission, text):
                return [dict(word=' cantar', start=.45, end=4.45, alignment_score=.9)]
        self.audio[:] = 0
        self.audio[16000:5*16000] = 5e-6*np.sin(np.arange(4*16000)*.1)
        source = segments('cantar', 1, duration=4)
        result, report = self.refine(source, 'cantar', voice_regions=[],
            backend_factory=HeldNote, preserve_timing=True)
        self.assertEqual(result[0]['words'][0]['start'], 1)
        self.assertEqual(result[0]['words'][0]['end'], 5)
        self.assertEqual(report['ctc_confirmed_words'], 1)
        self.assertEqual(report['voice_regions'], [[1.,5.]])

    def test_weak_forced_path_or_blank_emissions_cannot_authorize_text_on_music(self):
        class Weak(SupportedCTC):
            def align(self, emission, text):
                words = super().align(emission, text)
                for word in words:
                    word['alignment_score'] = .15
                return words
        class Blank(SupportedCTC):
            def word_has_voice(self, emission, word):
                return False
        for backend in (Weak, Blank):
            with self.subTest(backend=backend):
                result, report = self.refine(segments('voz', 7), voice_regions=[], backend_factory=backend)
                self.assertEqual(result, [])
                self.assertEqual(report['ambiguous_voice_words'], 1)

    def test_valid_manual_clocks_stay_exact_and_unvoiced_edges_are_trimmed(self):
        source = segments('voz', 2.2)
        result, _ = alignment.validate_display_evidence(self.path, source, 'voz', self.cache,
            context=self.context, voice_regions=[(2,4)], backend_factory=SupportedCTC,
            decode=lambda _: self.audio)
        self.assertEqual(result[0]['words'][0]['start'], source[0]['words'][0]['start'])
        self.assertEqual(result[0]['words'][0]['end'], source[0]['words'][0]['end'])
        extended = segments('voz', .5, duration=5)
        result, report = self.refine(extended, voice_regions=[(2,4)],
            backend_factory=Mock(side_effect=RuntimeError('missing')), preserve_timing=True)
        word = result[0]['words'][0]
        self.assertEqual(word['start'], 2)
        self.assertAlmostEqual(word['end'], 4.04)
        self.assertEqual(report['voice_trimmed_words'], 1)

    def test_broad_manual_phrase_cannot_expand_a_short_ctc_confirmation_over_music(self):
        class ShortConfirmation(SupportedCTC):
            def align(self, emission, text):
                return [dict(word=' voz', start=1., end=2., alignment_score=.95)]
        source = segments('voz', 1, duration=8)
        result, report = self.refine(source, voice_regions=[],
            backend_factory=ShortConfirmation, preserve_timing=True)
        word = result[0]['words'][0]
        self.assertAlmostEqual(word['start'], 1.55)
        self.assertAlmostEqual(word['end'], 2.59)
        self.assertEqual(report['voice_regions'], [[1.55,2.55]])

    def test_final_validation_reuses_verified_output_without_loading_a_second_model(self):
        source = segments('voz', 2.2)
        first, report = self.refine(source, voice_regions=[(2,4)])
        second, second_report = alignment.validate_display_evidence(self.path, first, 'voz', self.cache,
            context=self.context, voice_regions=[(2,4)],
            backend_factory=Mock(side_effect=AssertionError('must not reload')),
            decode=Mock(side_effect=AssertionError('must not decode')))
        self.assertEqual(first, second)
        self.assertEqual(report, second_report)
        self.assertTrue(report['cache_signature'])

    def test_cache_integrity_and_audio_or_guide_changes_cannot_bypass_validation(self):
        source = segments('voz', 2.2)
        first, _ = self.refine(source, voice_regions=[(2,4)])
        envelope = json.loads((self.cache/'aligned_lyrics.json').read_text())
        envelope['voice_regions'] = [[0,12]]
        (self.cache/'aligned_lyrics.json').write_text(json.dumps(envelope))
        self.assertIsNone(alignment._read_validated_output(self.path, first, 'voz', self.cache,
                                                          self.context, [(2,4)]))
        self.refine(source, voice_regions=[(2,4)])
        self.assertIsNone(alignment._read_validated_output(self.path, first, 'outra', self.cache,
                                                          self.context, [(2,4)]))
        self.path.write_bytes(b'changed audio')
        self.assertIsNone(alignment._read_validated_output(self.path, first, 'voz', self.cache,
                                                          self.context, [(2,4)]))

    def test_report_cannot_override_verified_voice_regions_or_output_signature(self):
        source = segments('voz', 2.2)
        first, _ = self.refine(source, voice_regions=[(2,4)])
        path = self.cache/'aligned_lyrics.json'
        original = json.loads(path.read_text(encoding='utf-8'))
        for field, value in (('voice_regions', [[0.,12.]]), ('cache_signature', 'unverified')):
            with self.subTest(field=field):
                altered = copy.deepcopy(original)
                altered['report'][field] = value
                path.write_text(json.dumps(altered), encoding='utf-8')
                self.assertIsNone(alignment._read_validated_output(self.path, first, 'voz',
                    self.cache, self.context, [(2,4)]))
        path.write_text(json.dumps(original), encoding='utf-8')
        self.assertIsNotNone(alignment._read_validated_output(self.path, first, 'voz',
            self.cache, self.context, [(2,4)]))

    def test_guide_repetition_count_never_forces_a_second_sung_occurrence(self):
        line = 'deixe uma luz acesa'
        class Single(SupportedCTC):
            def sequence_score(self, emission, text):
                return -100 if len(text) == 8 else -20
        result, report = self.refine(segments(line+' '+line), line+'\n'+line,
            voice_regions=[], backend_factory=Single)
        self.assertEqual(' '.join(segment['text'] for segment in result), line)
        self.assertEqual(report['repeated_words'], 4)

    def test_real_refrain_is_retained_when_the_full_audio_prefers_both_occurrences(self):
        line = 'deixe uma luz acesa'
        class Repeated(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if len(text) == 8 else -100
        result, report = self.refine(segments(line+' '+line), line,
            voice_regions=[], backend_factory=Repeated)
        self.assertEqual(sum(len(segment['words']) for segment in result), 8)
        self.assertEqual(report['repeated_words'], 0)

    def test_reviewed_loop_is_deleted_on_audio_evidence_without_retiming_retained_words(self):
        line = 'deixe uma luz acesa'
        class Single(SupportedCTC):
            def sequence_score(self, emission, text):
                return -100 if len(text) == 8 else -20
        source = segments(line+' '+line)
        expected = [(word['start'],word['end']) for word in source[0]['words'][:4]]
        result, report = alignment.validate_display_evidence(self.path, source, line+'\n'+line,
            self.cache, context=self.context, voice_regions=[], backend_factory=Single,
            decode=lambda _: self.audio)
        self.assertEqual([(word['start'],word['end']) for segment in result for word in segment['words']], expected)
        self.assertEqual(report['repeated_words'], 4)
        self.assertEqual(len(source[0]['words']), 8)

    def test_real_reviewed_repeat_retains_all_original_clocks(self):
        line = 'deixe uma luz acesa'
        class Repeated(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if len(text) == 8 else -100
        source = segments(line+' '+line)
        expected = [(word['start'],word['end']) for word in source[0]['words']]
        result, report = alignment.validate_display_evidence(self.path, source, line,
            self.cache, context=self.context, voice_regions=[], backend_factory=Repeated,
            decode=lambda _: self.audio)
        self.assertEqual([(word['start'],word['end']) for segment in result for word in segment['words']], expected)
        self.assertEqual(report['repeated_words'], 0)

    def test_rejecting_one_word_does_not_discard_other_strong_ctc_confirmation(self):
        class Partial(SupportedCTC):
            def align(self, emission, text):
                result = super().align(emission, text)
                result[-1]['alignment_score'] = .01
                return result
        result, report = self.refine(segments('voz fantasma'), 'voz', voice_regions=[(5,6)],
            backend_factory=Partial)
        self.assertEqual(result[0]['text'], 'voz')
        self.assertEqual(report['unsupported_voice_words'], 1)
        self.assertEqual(report['ctc_confirmed_words'], 1)

    def test_unguided_fallback_retains_legacy_energy_behavior(self):
        result, report = self.refine(segments('voz', 2.2), '',
            backend_factory=Mock(side_effect=RuntimeError('model unavailable')))
        self.assertEqual(result[0]['text'], 'voz')
        self.assertNotIn('strict_voice_policy', report)


if __name__ == '__main__':
    unittest.main()
