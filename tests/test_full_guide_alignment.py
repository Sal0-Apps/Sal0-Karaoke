"""Recover complete lyrics; weak speech CTC/VAD must not erase sung refrains."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]/'app'))
from full_guide_alignment import (WhisperGuideBackend, align_guide_with_whisper, alignment_lines,
    refine_confirmed_clocks, singing_activity, mark_confirmed_lines, local_candidate_alignments, recover_unconfirmed_lines)
from full_guide_alignment import trim_source_silence
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


class SourceSilenceClockTests(unittest.TestCase):
    def test_neighboring_clocks_can_advance_together_after_a_rest_without_reordering(self):
        words=[dict(word=' '+text,start=start,end=end,guide_token_index=index)
               for index,(text,start,end) in enumerate((('luz',2.,10.9),('na',10.9,11.7),('estrada',11.7,12.5)))]
        aligned=[dict(word=' '+text,start=start,end=end,alignment_score=.9)
                 for text,start,end in (('luz',10.,11.),('na',11.05,11.8),('estrada',11.85,12.4))]
        result,changed=refine_confirmed_clocks([dict(start=2.,end=12.5,words=words)],aligned)
        self.assertEqual([(word['start'],word['end']) for word in result[0]['words']],
                         [(word['start'],word['end']) for word in aligned])
        self.assertEqual(changed,3)
        self.assertEqual(words[0]['start'],2.)

    def test_measured_source_silence_boundary_survives_later_ctc_refinement(self):
        audio=np.zeros(6*16000,dtype=np.float32);audio[int(2.5*16000):int(3.5*16000)]=.1
        original=[dict(word=' luz',start=2.,end=3.9,guide_token_index=0)]
        measured=trim_source_silence(audio,original)
        self.assertEqual((measured[0]['start'],measured[0]['end']),(2.5,3.5))
        self.assertEqual(original[0]['start'],2.)
        refined,_=refine_confirmed_clocks([dict(start=2.5,end=3.5,words=measured)],
            [dict(word=' luz',start=2.3,end=3.3,alignment_score=.9)])
        self.assertEqual(refined[0]['words'][0]['start'],2.5)

    def test_source_zero_check_does_not_apply_a_relative_volume_threshold(self):
        audio=np.full(3*16000,1e-7,dtype=np.float32)
        words=[dict(word=' baixo',start=1.,end=2.)]
        self.assertEqual(trim_source_silence(audio,words),words)


class IndependentVerseRecoveryTests(unittest.TestCase):
    def recover(self, words, expected=None, earliest=10.):
        backend=object.__new__(WhisperGuideBackend)
        backend.cancel=Mock();backend.language='en'
        backend.model=Mock()
        backend.model.transcribe.return_value=([SimpleNamespace(words=[SimpleNamespace(**word) for word in words])],None)
        output=backend.recover_line(np.full(16*16000,.1,dtype=np.float32),10.,15.,
                                    expected or ['Keep','the','light'],earliest)
        return output,backend

    def test_independent_decode_uses_no_guide_and_keeps_measured_source_offsets(self):
        words=verse('Keep the light',.2)
        result,backend=self.recover(words)
        self.assertEqual([(w['start'],w['end']) for w in result],
                         [(10+w['start'],10+w['end']) for w in words])
        options=backend.model.transcribe.call_args.kwargs
        self.assertIsNone(options['initial_prompt']);self.assertIsNone(options['hotwords'])
        self.assertFalse(options['condition_on_previous_text']);self.assertFalse(options['vad_filter'])

    def test_wrong_recognized_text_is_not_replaced_by_the_guide(self):
        result,_=self.recover(verse('Keep another flame',.2))
        self.assertIsNone(result)

    def test_collapsed_and_nonfinite_clocks_cannot_recover_a_word(self):
        for replacement in ({'end':.2},{'start':float('nan')},{'probability':float('nan')}):
            with self.subTest(replacement=replacement):
                words=verse('Keep the light',.2);words[0].update(replacement)
                self.assertIsNone(self.recover(words)[0])

    def test_context_can_confirm_a_weak_syllable_but_not_a_whole_weak_phrase(self):
        words=verse('Keep the light',.2);words[1]['probability']=.001
        self.assertIsNotNone(self.recover(words)[0])
        for word in words:word['probability']=.1
        self.assertIsNone(self.recover(words)[0])

    def test_independent_decode_cannot_rewind_to_an_earlier_refrain(self):
        self.assertIsNone(self.recover(verse('Keep the light',.2),earliest=12.)[0])

    def test_confident_recognition_over_digital_silence_cannot_confirm_the_guide(self):
        _,backend=self.recover(verse('Keep the light',.2))
        self.assertIsNone(backend.recover_line(np.zeros(16*16000,dtype=np.float32),10.,15.,['Keep','the','light']))

    def test_cancellation_happens_before_an_independent_decode(self):
        backend=object.__new__(WhisperGuideBackend)
        backend.cancel=Mock(side_effect=InterruptedError('cancelado'));backend.model=Mock()
        with self.assertRaises(InterruptedError):
            backend.recover_line(np.zeros(16000),0.,1.,['Light'])
        backend.model.transcribe.assert_not_called()


class TwoModelRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.lines=[text.split() for text in ('Guarde esta luz acesa','Encontro você na estrada','Guarde esta luz acesa')]
        self.actual=[word for line,start in zip(self.lines,(1,6,12)) for word in verse(' '.join(line),start)]
        self.segments=[]
        for index in (0,2):
            words=copy.deepcopy(self.actual[index*4:index*4+4])
            for position,word in enumerate(words,index*4):word.update(guide_audio_confirmed=True,guide_token_index=position)
            self.segments.append(dict(start=words[0]['start'],end=words[-1]['end'],words=words,guide_audio_confirmed=True))
        self.segments.insert(1,dict(start=6,end=7.5,words=verse('Encontro palavra errada',6)))
        hints=copy.deepcopy(self.actual[4:8])
        for word in hints:word['probability']=.35
        hints[-1]['end']=hints[-1]['start']
        self.candidates=[dict(line=1,offset=4,unanchored_words=2,alternatives=[hints])]
        self.local={1:copy.deepcopy(self.actual[4:8])}
        for word in self.local[1]:word['alignment_score']=.15
        self.local[1][1]['alignment_score']=.004
        self.evidence=AudioEvidence(np.full(16*16000,.1,dtype=np.float32))

    def recover(self):
        return recover_unconfirmed_lines(self.segments,self.lines,self.local,self.candidates,self.evidence)

    def test_agreement_recovers_complete_text_with_positive_measured_ctc_clocks(self):
        before=copy.deepcopy(self.segments)
        result,report=self.recover();words=[w for s in result for w in s['words']]
        self.assertEqual([w['word'] for w in words],[w['word'] for w in self.actual])
        self.assertTrue(all(w['start']<w['end'] for w in words))
        self.assertTrue(all(w['guide_audio_confirmed'] for w in words))
        self.assertEqual(report,dict(guide_ctc_recovered_lines=1,guide_ctc_recovered_words=4,
                                     guide_ctc_recovered_unanchored_words=2,guide_ctc_recovered_line_indexes=[1]))
        self.assertEqual(self.segments,before)

    def test_uncertain_phrase_remains_asr_if_either_model_lacks_support(self):
        for missing in ('mms','whisper'):
            with self.subTest(missing=missing):
                self.setUp()
                if missing=='mms':self.local={}
                else:self.candidates[0]['alternatives']=[]
                self.assertEqual(self.recover()[0],self.segments)

    def test_ctc_word_cannot_collapse_or_use_weak_or_incompatible_phones(self):
        for change in ({'end':6.}, {'alignment_score':.0001}, {'word':' Outra'}, {'start':float('nan')}):
            with self.subTest(change=change):
                self.setUp();self.local[1][0].update(change)
                self.assertEqual(self.recover()[1]['guide_ctc_recovered_lines'],0)

    def test_digital_silence_cannot_confirm_a_guide_phrase(self):
        self.evidence=AudioEvidence(np.zeros(16*16000,dtype=np.float32))
        self.assertEqual(self.recover()[0],self.segments)

    def test_model_disagreement_cannot_move_a_phrase_to_a_different_occurrence(self):
        for word in self.candidates[0]['alternatives'][0]:word['start']+=4;word['end']+=4
        self.assertEqual(self.recover()[0],self.segments)

    def test_ctc_can_recover_a_tail_that_whisper_placed_one_and_a_half_seconds_early(self):
        for word in self.candidates[0]['alternatives'][0]:word['start']-=1.7;word['end']-=1.7
        self.assertEqual(self.recover()[1]['guide_ctc_recovered_lines'],1)

    def test_ctc_cannot_rewind_before_the_preceding_confirmed_verse(self):
        for word in self.local[1]:word['start']-=5;word['end']-=5
        self.assertEqual(self.recover()[0],self.segments)

    def test_without_neighboring_confirmed_context_no_phrase_is_inserted(self):
        self.segments=self.segments[1:2]
        self.assertEqual(self.recover()[0],self.segments)

    def test_local_ctc_uses_a_bounded_window_and_preserves_absolute_source_clocks(self):
        backend=Mock();backend.align_guide.return_value=copy.deepcopy(self.actual)
        result,clocks=local_candidate_alignments(backend,(np.zeros((800,28)),np.linspace(0,16,801)),
                                         self.segments,self.lines,self.candidates)
        self.assertEqual(result[1],self.actual[4:8])
        self.assertEqual(clocks,self.actual)
        values,edges=backend.align_guide.call_args.args[0]
        self.assertLessEqual(edges[-1]-edges[0],29.)
        self.assertEqual(len(values)+1,len(edges))

    def test_fresh_local_retry_uses_the_exact_source_sample_offset(self):
        for segment in self.segments:
            segment['start']+=20;segment['end']+=20
            for word in segment['words']:word['start']+=20;word['end']+=20
        for word in self.candidates[0]['alternatives'][0]:word['start']+=20;word['end']+=20
        actual=copy.deepcopy(self.actual)
        for word in actual:word['start']+=20;word['end']+=20
        backend=Mock();backend.align_guide.return_value=actual
        backend.full_emission.side_effect=lambda audio,progress:(np.zeros((100,28)),np.linspace(0,len(audio)/16000,101))
        result,_=local_candidate_alignments(backend,(np.zeros((2000,28)),np.linspace(0,40,2001)),
            self.segments,self.lines,self.candidates,audio=np.full(40*16000,.1,dtype=np.float32))
        _,edges=backend.align_guide.call_args.args[0]
        self.assertEqual(edges[0],15.)
        self.assertLessEqual(edges[-1]-edges[0],29.)
        self.assertEqual(result[1],actual[4:8])

    def test_context_spanning_a_long_rest_cannot_expand_ctc_attention_without_limit(self):
        for word in self.segments[-1]['words']:word['start']+=40;word['end']+=40
        backend=Mock()
        result,_=local_candidate_alignments(backend,(np.zeros((4000,28)),np.linspace(0,80,4001)),
                                         self.segments,self.lines,self.candidates)
        self.assertEqual(result,{})
        backend.align_guide.assert_not_called()


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

    def test_independent_local_decode_recovers_a_collapsed_final_verse(self):
        actual=self.actual
        class Retry(AcousticFixture):
            def align(self,*args):
                result=super().align(*args)
                for word in result or []:
                    if word['start'] >= 12:word['end']=word['start']
                return result
            def recover_line(self,audio,left,right,words,earliest=0.):
                return copy.deepcopy(actual[-4:])
        result,report=align_guide_with_whisper(self.source,[dict(words=actual[:-1])],self.guide,self.root,'medium',
            decode=lambda _:self.audio,backend_factory=lambda *_:Retry(actual))
        self.assertEqual(report['status'],'aligned')
        self.assertEqual(report['guide_independent_recoveries'],1)
        self.assertEqual(result[-1]['words'][-1]['end'],actual[-1]['end'])

    def test_guide_printed_once_cannot_erase_an_unprinted_sung_repeat(self):
        self.guide = self.lines[0]
        source = self.actual[:4]+self.actual[8:]
        result, report = self.run_guide(source)
        output=[word for segment in result for word in segment['words']]
        self.assertEqual([(word['word'],word['start'],word['end']) for word in output],
                         [(word['word'],word['start'],word['end']) for word in source])
        self.assertEqual(report['status'], 'incomplete_guide')
        self.assertEqual(report['guide_aligned_words'],4)

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

    def test_confirmed_verse_endings_survive_attenuation_in_the_separated_voice(self):
        confirmed, _ = self.run_guide()
        for word in self.actual[3::4]:
            self.audio[int((word['start']-.02)*16000):int((word['end']+.12)*16000)] = 0
        result, _ = refine_lyrics(self.source, confirmed, self.guide, self.root,
            decode=lambda _: self.audio, backend_factory=Mock(side_effect=RuntimeError('unavailable')))
        self.assertEqual([w['word'] for s in result for w in s['words']],
                         [w['word'] for w in self.actual])

    def test_ctc_proposal_cannot_move_a_final_word_before_its_preceding_word(self):
        confirmed, _ = self.run_guide()
        candidate = [dict(w, alignment_score=.8) for w in self.actual]
        candidate[3].update(start=self.actual[2]['start']-.05,end=self.actual[2]['end']-.01)
        result, _ = refine_confirmed_clocks(confirmed, candidate)
        self.assertEqual(result[0]['words'][-1]['start'],self.actual[3]['start'])

    def test_one_uncertain_verse_does_not_discard_other_confirmed_guide_verses(self):
        actual=self.actual
        class Partial(AcousticFixture):
            def align(self,*args):
                result=super().align(*args)
                for word in result or []:
                    if 6 <= word['start'] < 9: word['probability']=.01
                return result
        baseline=copy.deepcopy(actual); baseline[0]['word']=' Garde'
        baseline.insert(2,dict(word=' inventada',start=1.65,end=1.7,probability=.9))
        source=[dict(start=1,end=14,words=baseline)]
        result,report=align_guide_with_whisper(self.source,source,self.guide,self.root,'medium',
            decode=lambda _:self.audio,backend_factory=lambda *_:Partial(actual))
        words=[w for s in result for w in s['words']]
        self.assertEqual(report['status'],'partial')
        self.assertEqual(report['guide_aligned_words'],8)
        self.assertEqual(words[0]['word'],' Guarde')
        self.assertNotIn(' inventada',[w['word'] for w in words])
        self.assertEqual([w['word'] for w in words[4:8]],[w['word'] for w in actual[4:8]])
        refined,_=refine_lyrics(self.source,result,self.guide,self.root,decode=lambda _:self.audio,
            backend_factory=Mock(side_effect=RuntimeError('unavailable')))
        self.assertEqual([w['word'] for s in refined for w in s['words']],[w['word'] for w in words])
        self.assertEqual(sum(bool(w.get('guide_audio_confirmed')) for s in refined for w in s['words']),8)

    def test_late_verse_with_only_its_final_anchors_gets_a_bounded_local_window(self):
        self.lines=self.lines[:2];self.guide='\n'.join(self.lines)
        self.actual=verse(self.lines[0],1)+verse(self.lines[1],61)
        self.audio=np.full(80*16000,.1,dtype=np.float32)
        actual=self.actual
        class Bounded(AcousticFixture):
            def align(self,audio,left,right,words):
                if right-left > 29:return None
                result=super().align(audio,left,right,words)
                return result if result and left <= result[0]['start'] and result[-1]['end'] <= right else None
        baseline=self.actual[:4]+self.actual[-2:]
        result,report=align_guide_with_whisper(self.source,[dict(words=baseline)],self.guide,self.root,'medium',
            decode=lambda _:self.audio,backend_factory=lambda *_:Bounded(actual))
        self.assertEqual(report['status'],'aligned')
        self.assertEqual([w['start'] for s in result for w in s['words']],[w['start'] for w in actual])

    def test_missing_last_word_is_rechecked_with_audio_beyond_the_last_asr_anchor(self):
        self.guide=self.lines[0]; actual=verse(self.guide,1)
        actual[-1].update(start=5.8,end=6.7)
        class Tail(AcousticFixture):
            def align(self,audio,left,right,words):
                result=super().align(audio,left,right,words)
                if result and result[-1]['end'] > right:return None
                return result
        result,report=align_guide_with_whisper(self.source,[dict(words=actual[:-1])],self.guide,self.root,'medium',
            decode=lambda _:self.audio,backend_factory=lambda *_:Tail(actual))
        self.assertEqual(report['status'],'aligned')
        self.assertEqual(result[0]['words'][-1]['end'],6.7)

    def test_late_ending_retry_keeps_the_preceding_verse_as_acoustic_context(self):
        actual=copy.deepcopy(self.actual);actual[-1]['end']=15.7
        class ContextTail(AcousticFixture):
            def align(self,audio,left,right,words):
                result=super().align(audio,left,right,words)
                if result and result[-1]['end'] > right:return None
                if result and result[-1]['start'] >= 12 and 'Encontro' not in words:return None
                return result
        result,report=align_guide_with_whisper(self.source,[dict(words=actual[:-1])],self.guide,self.root,'medium',
            decode=lambda _:self.audio,backend_factory=lambda *_:ContextTail(actual))
        self.assertEqual(report['status'],'aligned')
        self.assertEqual(result[-1]['words'][-1]['end'],15.7)

    def test_wrong_refrain_occurrence_cannot_rewind_the_recording(self):
        actual=self.actual
        class WrongOccurrence(AcousticFixture):
            def align(self,*args):
                result=super().align(*args)
                for word in result or []:
                    if word['start'] >= 12:
                        word['start']-=11;word['end']-=11
                return result
        result,report=align_guide_with_whisper(self.source,[dict(words=actual)],self.guide,self.root,'medium',
            decode=lambda _:self.audio,backend_factory=lambda *_:WrongOccurrence(actual))
        words=[w for s in result for w in s['words']]
        self.assertEqual([w['word'] for w in words],[w['word'] for w in actual])
        self.assertEqual(words[-4]['start'],12)
        self.assertEqual(report['status'],'partial')

    def test_long_song_can_recover_guide_after_only_one_solid_recognized_phrase(self):
        self.audio=np.full(120*16000,.1,dtype=np.float32)
        result,report=self.run_guide(self.actual[:4])
        self.assertEqual(report['status'],'aligned')
        self.assertEqual([w['start'] for s in result for w in s['words']],[w['start'] for w in self.actual])

    def test_hybrid_ctc_never_uses_repetition_cleanup_to_rewrite_confirmed_words(self):
        actual=verse(self.lines[0],1)+verse(self.lines[0],3)
        first=copy.deepcopy(actual[:4]);second=copy.deepcopy(actual[4:])
        for index,word in enumerate(first):word.update(guide_audio_confirmed=True,guide_token_index=index)
        source=[dict(start=1,end=first[-1]['end'],words=first,guide_audio_confirmed=True),
                dict(start=3,end=second[-1]['end'],words=second)]
        class Backend:
            def __init__(self,*_):pass
            def emission(self,audio):return None
            def align(self,emission,words):
                return [dict(word=' '+word,start=.45+i*.43,end=.57+i*.43,alignment_score=.9)
                        for i,word in enumerate(words)]
            def sequence_score(self,emission,words):return -len(words)*10
            def close(self):pass
        result,_=refine_lyrics(self.source,source,self.lines[0],self.root,decode=lambda _:self.audio,
                               backend_factory=Backend,voice_regions=None)
        protected=[w for s in result for w in s['words'] if w.get('guide_audio_confirmed')]
        self.assertEqual([w['word'] for w in protected],[w['word'] for w in first])
        self.assertEqual([w['guide_token_index'] for w in protected],list(range(4)))

    def test_instrumental_leakage_without_phone_posterior_does_not_hide_a_real_rest(self):
        edges = np.linspace(0, 16, 801)
        values = np.full((800, 28), -30., dtype=np.float32); values[:, 0] = 0.
        source = [dict(start=1., end=14., words=[])]
        self.assertEqual(singing_activity((values, edges), AudioEvidence(self.audio), source), [])


if __name__ == '__main__':
    unittest.main()
