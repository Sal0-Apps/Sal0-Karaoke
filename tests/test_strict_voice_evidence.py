"""Conservative ASR recovery after the strict 12.7.1 gate.

Textual guide proposals always require complete-window CTC confirmation.
Missing models and uncertain VAD must preserve the supported ASR phrase.
"""
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


class ConservativeVoiceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name)
        self.path = self.cache/'vocals.wav'
        self.path.write_bytes(b'unchanged audio fixture')
        self.audio = (.001*np.sin(np.arange(12*16000)*.1)).astype(np.float32)
        self.original_audio = self.audio.copy()

    def refine(self, source, guide='', **options):
        options.setdefault('backend_factory', SupportedCTC)
        options.setdefault('decode', lambda _: self.audio)
        return alignment.refine_lyrics(self.path, source, guide, self.cache, **options)

    @staticmethod
    def text(result):
        return ' '.join(segment['text'] for segment in result)

    def refine_pair(self, scores):
        calls, emissions = [], []
        class Scored(SupportedCTC):
            def emission(self, audio):
                value = super().emission(audio)
                emissions.append(value)
                return value

            def sequence_score(self, emission, text):
                calls.append((emission, tuple(text)))
                return scores[('cantar' in text, 'noite' in text)]
        source = segments('eu quero gastar com voce nesta noiva')
        result, report = self.refine(source, 'eu quero cantar com você nesta noite',
                                    backend_factory=Scored)
        self.assertEqual(len(emissions), 1)
        self.assertTrue(all(emission is emissions[0] for emission, _ in calls))
        keys = [text for _, text in calls]
        self.assertEqual(len(keys), len(set(keys)), 'Each complete hypothesis is scored once')
        return result, report

    def test_unavailable_alignment_and_vad_preserve_the_complete_phrase(self):
        source = segments('eu quero gastar com voce nesta noite')
        before = copy.deepcopy(source)
        for regions in (None, [], [(8, 9)]):
            with self.subTest(regions=regions):
                result, report = self.refine(source, 'eu quero cantar com você nesta noite',
                    voice_regions=regions, backend_factory=Mock(side_effect=RuntimeError('missing model')))
                self.assertEqual(self.text(result), source[0]['text'])
                self.assertEqual(report['status'], 'fallback')
                self.assertEqual(report['guide_changes'], 0)
        self.assertEqual(source, before)
        np.testing.assert_array_equal(self.audio, self.original_audio)
        self.assertEqual(self.path.read_bytes(), b'unchanged audio fixture')

    def test_disabled_alignment_does_not_drop_words_for_empty_vad(self):
        source = segments('eu quero cantar com voce')
        factory = Mock(side_effect=AssertionError('disabled model cannot load'))
        with patch.dict(alignment.os.environ, {'KARAOKE_ALIGNMENT': 'off'}):
            result, _ = self.refine(source, 'eu quero cantar com você',
                                    voice_regions=[], backend_factory=factory)
        self.assertEqual(self.text(result), source[0]['text'])
        factory.assert_not_called()

    def test_high_word_scores_without_sequence_likelihood_cannot_change_lyrics(self):
        source = segments('eu quero gastar com voce nesta noite')
        result, report = self.refine(source, 'eu quero cantar com você nesta noite')
        self.assertEqual(self.text(result), source[0]['text'])
        self.assertEqual(report['guide_changes'], 0)

    def test_weak_tied_nonfinite_or_opposing_ctc_scores_preserve_asr(self):
        source = segments('eu quero gastar com voce nesta noite')
        for original_score, candidate_score in ((-30, -30), (-30, -25), (-30, -60),
                                                 (-float('inf'), -20), (-30, float('nan'))):
            class Uncertain(SupportedCTC):
                def sequence_score(self, emission, text):
                    return candidate_score if 'cantar' in text else original_score
            with self.subTest(original=original_score, candidate=candidate_score):
                result, report = self.refine(source, 'eu quero cantar com você nesta noite',
                                            backend_factory=Uncertain)
                self.assertEqual(self.text(result), source[0]['text'])
                self.assertEqual(report['guide_changes'], 0)

    def test_strong_full_window_ctc_can_confirm_same_count_correction(self):
        emissions = []
        class Confirmed(SupportedCTC):
            def sequence_score(self, emission, text):
                emissions.append(emission)
                return -20 if 'cantar' in text else -60
        source = segments('eu quero gastar com voce nesta noite')
        before = copy.deepcopy(source)
        result, report = self.refine(source, 'eu quero cantar com você nesta noite',
                                    backend_factory=Confirmed)
        self.assertIn('cantar', self.text(result))
        self.assertNotIn('gastar', self.text(result))
        self.assertEqual(sum(len(s['words']) for s in result), 7)
        self.assertGreater(report['guide_changes'], 0)
        self.assertEqual(len(set(emissions)), 1)
        self.assertEqual(source, before)

    def test_one_good_correction_cannot_mask_an_individually_bad_correction(self):
        result, report = self.refine_pair({(False, False): -100, (True, False): -60,
                                          (False, True): -110, (True, True): -65})
        self.assertIn('cantar', self.text(result))
        self.assertIn('noiva', self.text(result))
        self.assertNotIn('noite', self.text(result))
        self.assertGreater(report['guide_changes'], 0)

    def test_final_marginal_check_prunes_a_harmful_interaction_between_good_corrections(self):
        result, _ = self.refine_pair({(False, False): -100, (True, False): -60,
                                     (False, True): -65, (True, True): -64})
        self.assertIn('cantar', self.text(result))
        self.assertIn('noiva', self.text(result))
        self.assertNotIn('noite', self.text(result))

    def test_individual_gains_do_not_override_a_rejected_joint_sequence(self):
        result, report = self.refine_pair({(False, False): -100, (True, False): -60,
                                          (False, True): -65, (True, True): -99})
        self.assertIn('gastar', self.text(result))
        self.assertIn('noiva', self.text(result))
        self.assertEqual(report['guide_changes'], 0)

    def test_two_corrections_supported_alone_together_and_marginally_are_kept(self):
        result, report = self.refine_pair({(False, False): -100, (True, False): -80,
                                          (False, True): -85, (True, True): -60})
        self.assertIn('cantar', self.text(result))
        self.assertIn('noite', self.text(result))
        self.assertNotIn('gastar', self.text(result))
        self.assertNotIn('noiva', self.text(result))
        self.assertGreater(report['guide_changes'], 0)

    def test_missing_guide_word_is_not_inserted_even_with_high_alignment_confidence(self):
        source = segments('eu quero com voce nesta noite')
        result, report = self.refine(source, 'eu quero cantar com você nesta noite')
        self.assertEqual(self.text(result), source[0]['text'])
        self.assertEqual(sum(len(s['words']) for s in result), 6)
        self.assertEqual(report['guide_changes'], 0)

    def test_ambiguous_guide_keeps_the_complete_recognition(self):
        source = segments('eu quero centar com voce')
        guide = 'eu quero cantar com você\neu quero contar com você'
        self.assertIsNone(alignment.guided_candidate(guide, source[0]['words']))
        result, report = self.refine(source, guide)
        self.assertEqual(self.text(result), source[0]['text'])
        self.assertEqual(report['guide_changes'], 0)

    def test_short_one_word_correction_still_requires_ctc_confirmation(self):
        class Confirmed(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if 'world' in text else -60
        result, report = self.refine(segments('hello word'), 'hello world',
                                    backend_factory=Confirmed)
        self.assertEqual(self.text(result), 'hello world')
        self.assertEqual(sum(len(s['words']) for s in result), 2)
        self.assertGreater(report['guide_changes'], 0)

    def test_distant_recognition_error_can_be_proposed_and_confirmed_by_audio(self):
        class Confirmed(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if 'cantar' in text else -60
        source = segments('eu quero banana com voce nesta noite')
        result, report = self.refine(source, 'eu quero cantar com você nesta noite',
                                    backend_factory=Confirmed)
        self.assertIn('cantar', self.text(result))
        self.assertNotIn('banana', self.text(result))
        self.assertEqual(sum(len(s['words']) for s in result), 7)
        self.assertGreater(report['guide_changes'], 0)

    def test_sequence_scoring_failure_preserves_complete_phrase_and_clocks(self):
        class Unavailable(SupportedCTC):
            def sequence_score(self, emission, text):
                raise RuntimeError('CTC scoring unavailable')
        source = segments('eu quero gastar com voce nesta noite')
        result, report = self.refine(source, 'eu quero cantar com você nesta noite',
                                    backend_factory=Unavailable)
        self.assertEqual([(w['word'], w['start'], w['end']) for w in result[0]['words']],
                         [(w['word'], w['start'], w['end']) for w in source[0]['words']])
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['guide_changes'], 0)

    def test_printed_duplicate_never_prevents_audio_supported_loop_removal(self):
        line = 'deixe uma luz acesa'
        class SingleOccurrence(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if len(text) == 4 else -70
        result, report = self.refine(segments(line+' '+line), line+'\n'+line,
                                    backend_factory=SingleOccurrence)
        self.assertEqual(self.text(result), line)
        self.assertEqual(report['repeated_words'], 4)

    def test_uncertain_repetition_remains_even_when_guide_prints_once(self):
        line = 'deixe uma luz acesa'
        result, report = self.refine(segments(line+' '+line), line)
        self.assertEqual(self.text(result), line+' '+line)
        self.assertEqual(report['repeated_words'], 0)

    def test_correction_keeps_neighboring_context_across_alignment_chunks(self):
        class Confirmed(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if 'cantar' in text else -60
        # The middle word is regrouped into its own acoustic window. Its
        # neighbors still identify the guide phrase, but never supply clocks.
        source = segments('eu quero', start=1.) + segments('gastar', start=2.6)
        source += segments('com voce nesta noite', start=3.6)
        result, report = self.refine(source, 'eu quero cantar com você nesta noite',
                                    backend_factory=Confirmed)
        self.assertIn('cantar', self.text(result))
        self.assertNotIn('gastar', self.text(result))
        self.assertEqual(sum(len(s['words']) for s in result), 7)
        self.assertEqual(report['guide_changes'], 1)

    def test_correcting_one_word_does_not_skip_repetition_check(self):
        line = 'eu quero cantar com voce'
        class CorrectedLoop(SupportedCTC):
            def sequence_score(self, emission, text):
                return -100 + 20 * text.count('cantar') + (40 if len(text) == 5 else 0)
        source = segments('eu quero gastar com voce ' + line)
        result, report = self.refine(source, line, backend_factory=CorrectedLoop)
        self.assertEqual(self.text(result), line)
        self.assertEqual(report['repeated_words'], 5)
        self.assertGreater(report['guide_changes'], 0)

    def test_correction_does_not_remove_a_refrain_that_the_audio_confirms(self):
        line = 'eu quero cantar com voce'
        class SungTwice(SupportedCTC):
            def sequence_score(self, emission, text):
                return -100 + 20 * text.count('cantar') - (40 if len(text) == 5 else 0)
        source = segments('eu quero gastar com voce ' + line)
        result, report = self.refine(source, line, backend_factory=SungTwice)
        self.assertEqual(self.text(result), line + ' ' + line)
        self.assertEqual(report['repeated_words'], 0)

    def test_correcting_one_word_does_not_skip_unvoiced_tail_check(self):
        class CorrectedNoise(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if 'cantar' in text else -60
            def align(self, emission, text):
                result = super().align(emission, text)
                result[-1]['alignment_score'] = .06
                return result
        source = segments('eu quero gastar com voce fantasma')
        result, report = self.refine(source, 'eu quero cantar com voce',
            voice_regions=[(.8, 2.9)], backend_factory=CorrectedNoise)
        self.assertEqual(self.text(result), 'eu quero cantar com voce')
        self.assertEqual(report['unsupported_voice_words'], 1)

    def test_corrected_quiet_word_survives_without_voice_detector_evidence(self):
        class CorrectedQuiet(SupportedCTC):
            def sequence_score(self, emission, text):
                return -20 if 'cantar' in text else -60
            def align(self, emission, text):
                result = super().align(emission, text)
                result[-1]['alignment_score'] = .06
                return result
        source = segments('eu quero gastar com voce')
        result, report = self.refine(source, 'eu quero cantar com voce',
            voice_regions=None, backend_factory=CorrectedQuiet)
        self.assertEqual(self.text(result), 'eu quero cantar com voce')
        self.assertEqual(report['unsupported_voice_words'], 0)

    def test_quiet_long_note_survives_missing_vad(self):
        self.audio *= .0001
        source = segments('cantar', duration=5.)
        result, _ = self.refine(source, 'cantar', voice_regions=[],
            backend_factory=Mock(side_effect=RuntimeError('missing model')))
        self.assertEqual(result[0]['words'], source[0]['words'])

    def test_strict_version_four_output_is_never_reused(self):
        source = segments('eu quero cantar')
        self.refine(source)
        path = self.cache/'aligned_lyrics.json'
        envelope = json.loads(path.read_text())
        envelope['segments'] = []
        envelope['report']['version'] = 4
        path.write_text(json.dumps(envelope))
        factory = Mock(side_effect=RuntimeError('model unavailable after old cache'))
        result, report = self.refine(source, backend_factory=factory)
        self.assertEqual(self.text(result), source[0]['text'])
        self.assertEqual(report['version'], alignment.QUALITY_VERSION)
        self.assertEqual(report['status'], 'fallback')
        factory.assert_called_once()

    def test_acoustic_baseline_restores_lexical_asr_but_keeps_accents(self):
        from lyric_guide import verify_lyrics_guide
        source = segments('eu quero gastar com voce nesta noite')
        checked, report = verify_lyrics_guide('Eu quero cantar com você nesta noite!', source)
        result = alignment.acoustic_baseline(checked, report['checks'])
        self.assertEqual(result[0]['text'], 'Eu quero gastar com você nesta noite!')
        self.assertEqual([(w['start'], w['end']) for w in result[0]['words']],
                         [(w['start'], w['end']) for w in source[0]['words']])
