import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
from lyric_alignment import (AudioEvidence,clean_segments,roman_word,guided_candidate,
    refine_lyrics,accept_alignment,invalidate_quality_outputs,QUALITY_VERSION,MMSAligner,acoustic_baseline,
    repetition_candidates,supports_deletion)
from karaoke_generator import generate_ass_karaoke


def words(text,start=1,step=.4):
    items=[dict(word=' '+token,start=start+i*step,end=start+i*step+.3) for i,token in enumerate(text.split())]
    return [dict(start=items[0]['start'],end=items[-1]['end'],text=text,words=items)]


def sounding(seconds=8,start=.5,end=6,gain=.1):
    values=np.zeros(int(seconds*16000),np.float32)
    begin,finish=int(start*16000),int(end*16000)
    values[begin:finish]=gain*np.sin(np.arange(finish-begin)*.1)
    return values


class Backend:
    def __init__(self,progress,cancel):self.cancel=cancel;self.closed=False
    def emission(self,audio):return len(audio)/16000
    def align(self,emission,text):
        return [dict(word=' '+token,start=.45+i*.4,end=.7+i*.4,alignment_score=.8,
                     alignment_chars=[dict(text=c,start=.45+i*.4+j*.02,end=.47+i*.4+j*.02) for j,c in enumerate(token)])
                for i,token in enumerate(text)]
    def close(self):self.closed=True


class EvidenceTests(unittest.TestCase):
    def test_overlapping_phrase_with_slightly_different_clocks_is_one_event(self):
        first = words('deixe uma luz acesa', 1)
        duplicate = words('deixe uma luz acesa', 1.1)
        later = words('deixe uma luz acesa', 6)
        source = first + duplicate + later
        before = copy.deepcopy(source)
        result, report = clean_segments(source, AudioEvidence(sounding(10, .5, 9)))
        self.assertEqual(sum(len(s['words']) for s in result), 8)
        self.assertEqual(report['silent_or_invalid_words'], 4)
        self.assertEqual(source, before)

    def test_words_in_introduction_gaps_and_silent_tail_are_removed_without_moving_audio(self):
        audio=sounding(12,start=2,end=4)
        source=words('intro',.1)+words('voz real',2.2)+words('fim inventado',7)
        before=copy.deepcopy(source)
        result,report=clean_segments(source,AudioEvidence(audio))
        self.assertEqual(' '.join(s['text'] for s in result),'voz real')
        self.assertEqual(report['silent_or_invalid_words'],3)
        self.assertEqual(source,before);self.assertEqual(len(audio),12*16000)
        self.assertEqual(result[0]['words'][0]['start'],2.2)

    def test_end_of_last_word_does_not_extend_into_silence(self):
        source=words('voz',2);source[0]['words'][0]['end']=10
        result,report=clean_segments(source,AudioEvidence(sounding(12,2,3)))
        self.assertLessEqual(result[-1]['end'],3.081)
        self.assertEqual(report['trimmed_words'],1)

    def test_quiet_recording_and_long_held_vowel_are_preserved(self):
        source=words('cantar',1);source[0]['words'][0]['end']=5
        result,_=clean_segments(source,AudioEvidence(sounding(8,.9,5.1,gain=.000005)))
        self.assertEqual(result[0]['words'],source[0]['words'])

    def test_exact_duplicate_clock_is_removed_but_later_chorus_is_preserved(self):
        source=words('eu canto',1);source+=copy.deepcopy(source);source+=words('eu canto',4)
        result,report=clean_segments(source,AudioEvidence(sounding(8,.5,7)))
        self.assertEqual(sum(len(s['words']) for s in result),4)
        self.assertEqual(report['silent_or_invalid_words'],2)
        self.assertEqual([s['start'] for s in result],[1,4])

    def test_invalid_and_outside_media_words_never_make_an_artificial_final_verse(self):
        source=words('voz',1)
        source[0]['words'] += [dict(word=' extra',start=12,end=13),dict(word=' nan',start=float('nan'),end=5)]
        result,report=clean_segments(source,AudioEvidence(sounding()))
        self.assertEqual(result[0]['text'],'voz');self.assertEqual(report['silent_or_invalid_words'],2)


class GuideTests(unittest.TestCase):
    def test_complete_adjacent_loop_can_be_proposed_even_with_low_guide_coverage(self):
        raw = words('deixe uma luz acesa deixe uma luz acesa')[0]['words']
        self.assertIn('deixe uma luz acesa'.split(), repetition_candidates(raw, 'deixe uma luz acesa'))
        self.assertIn('deixe uma luz acesa'.split(),
                      repetition_candidates(raw, 'deixe uma luz acesa\ndeixe uma luz acesa'))

    def test_single_word_stutters_and_distant_refrains_are_not_loop_proposals(self):
        self.assertEqual(repetition_candidates(words('não não não')[0]['words'], ''), [])
        raw = words('deixe uma luz acesa', 1)[0]['words'] + words('deixe uma luz acesa', 10)[0]['words']
        self.assertEqual(repetition_candidates(raw, ''), [])

    def test_three_copies_offer_every_audio_hypothesis_despite_printed_guide_repeats(self):
        line = 'deixe uma luz acesa'
        raw = words(' '.join([line]*3))[0]['words']
        self.assertIn(line.split(), repetition_candidates(raw, line))
        proposals = repetition_candidates(raw, f'{line}\n{line}')
        self.assertIn((line+' '+line).split(), proposals)
        self.assertIn(line.split(), proposals)

    def test_surviving_word_confidence_alone_cannot_authorize_a_deletion(self):
        self.assertFalse(supports_deletion(Backend(lambda *a: None, lambda: None), None,
                                           ['deixe', 'uma', 'luz'] * 2, ['deixe', 'uma', 'luz']))
    def test_lexical_guide_changes_return_to_asr_baseline_until_acoustically_confirmed(self):
        from lyric_guide import verify_lyrics_guide
        source=words('eu quero gastar com voce nesta noite')
        checked,report=verify_lyrics_guide('Eu quero cantar com você nesta noite!',source)
        baseline=acoustic_baseline(checked,report['checks'])
        self.assertEqual(baseline[0]['text'],'Eu quero gastar com você nesta noite!')
        self.assertEqual(checked[0]['text'],'Eu quero cantar com você nesta noite!')
        self.assertEqual([(w['start'],w['end']) for w in baseline[0]['words']],[(w['start'],w['end']) for w in source[0]['words']])

    def test_real_backend_character_mapping_preserves_contractions(self):
        class Span:
            def __init__(self,index):self.start=index;self.end=index+1;self.score=.9
            def __len__(self):return 1
        backend=object.__new__(MMSAligner)
        backend.tokenizer=lambda words:words
        backend.aligner=lambda emission,tokens:[[Span(i) for i in range(len(word))] for word in tokens]
        value=Mock();value.size.return_value=100
        result=backend.align((value,2),["Don't"])
        self.assertIsNotNone(result)
        self.assertEqual(''.join(c['text'] for c in result[0]['alignment_chars']),"Don't")

    def test_context_proposes_local_substitutions_without_inserting_missing_words(self):
        guide='eu quero cantar com você nesta noite'
        proposed=guided_candidate(guide,words('eu quero gastar com voce nesta noite')[0]['words'])
        self.assertIsNotNone(proposed)
        self.assertEqual(proposed[2], 'cantar')
        self.assertEqual(len(proposed),7)
        self.assertIsNone(guided_candidate(guide,words('eu quero com voce nesta noite')[0]['words']))
        self.assertEqual(guided_candidate(guide,words('eu quero viver com voce nesta noite')[0]['words']),guide.split())

    def test_unrelated_guide_cannot_supply_a_verse_and_external_times_are_ignored(self):
        self.assertIsNone(guided_candidate('outra letra com palavras diferentes',words('eu quero cantar nesta noite')[0]['words']))
        raw=words('eu quero gastar com voce nesta noite')[0]['words']
        self.assertEqual(guided_candidate('[99:59]eu quero cantar com você nesta noite',raw),
                         guided_candidate('[00:01]eu quero cantar com você nesta noite',raw))

    def test_script_and_number_normalization_never_silently_changes_visible_text(self):
        self.assertEqual(roman_word('Coração!'),'coracao')
        self.assertEqual(roman_word('日本語'),'');self.assertEqual(roman_word('2026'),'')


class QualityTests(unittest.TestCase):
    def test_unsupported_phrase_loop_is_removed_only_when_whole_audio_prefers_single_occurrence(self):
        class Loop(Backend):
            def sequence_score(self, emission, text):
                return -100 if len(text) == 8 else -50
        self.factory = Loop
        result, report = self.refine(words('deixe uma luz acesa deixe uma luz acesa'), 'deixe uma luz acesa')
        self.assertEqual(' '.join(s['text'] for s in result), 'deixe uma luz acesa')
        self.assertEqual(report['repeated_words'], 4)
        self.assertEqual(report['guide_verses'], 1)

    def test_actually_sung_adjacent_repetition_is_kept_even_if_guide_prints_it_once(self):
        class RealRepeat(Backend):
            def sequence_score(self, emission, text):
                return -40 if len(text) == 8 else -90
        self.factory = RealRepeat
        result, report = self.refine(words('deixe uma luz acesa deixe uma luz acesa'), 'deixe uma luz acesa')
        self.assertEqual([s['text'] for s in result], ['deixe uma luz acesa'] * 2)
        self.assertEqual(report['repeated_words'], 0)

    def test_repeated_phrase_across_asr_analysis_chunks_is_still_checked(self):
        line = 'deixe uma luz acesa quando eu voltar para casa nesta noite de chuva e vento'
        class Loop(Backend):
            def sequence_score(self, emission, text):
                return -100 if len(text)>len(line.split()) else -20
        self.factory = Loop
        result, report = self.refine(words(line+' '+line, step=.26), line)
        self.assertEqual(' '.join(s['text'] for s in result), line)
        self.assertEqual(report['repeated_words'], len(line.split()))

    def test_multiple_loop_hypotheses_keep_the_best_explanation_of_all_audio(self):
        line = 'deixe uma luz acesa'
        class Loop(Backend):
            def sequence_score(self, emission, text):
                return {4:-20, 8:-50, 12:-100}[len(text)]
        self.factory = Loop
        result, report = self.refine(words(' '.join([line]*3)), line)
        self.assertEqual(' '.join(s['text'] for s in result), line)
        self.assertEqual(report['repeated_words'], 8)

    def test_alignment_then_cached_result_keep_boundaries_and_character_times(self):
        source = words('deixe uma luz acesa quando eu voltar pra casa')
        guide = 'deixe uma luz acesa\nquando eu voltar pra casa'
        first, report = self.refine(source, guide)
        second, cached_report = self.refine(source, guide)
        self.assertEqual([s['text'] for s in first], guide.splitlines())
        self.assertEqual(first, second)
        self.assertEqual(report, cached_report)
        self.assertTrue(first[1]['words'][0]['alignment_chars'])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.audio=self.root/'source.wav';self.audio.write_bytes(b'fixture')
        self.decode=Mock(return_value=sounding(12,.5,10))
        self.backends=[]
        def factory(progress,cancel):
            backend=Backend(progress,cancel);self.backends.append(backend);return backend
        self.factory=factory

    def refine(self,source,guide='',**options):
        return refine_lyrics(self.audio,source,guide,self.root,decode=self.decode,backend_factory=self.factory,**options)

    def test_guide_changes_require_acoustic_support_and_do_not_overwrite_raw_transcription(self):
        source=words('eu quero gastar com voce nesta noite');before=copy.deepcopy(source)
        class Supported(Backend):
            def sequence_score(self,emission,text):
                return -20 if 'cantar' in text else -60
        def factory(progress,cancel):
            backend=Supported(progress,cancel);self.backends.append(backend);return backend
        self.factory=factory
        raw=self.root/'transcribed_segments.json';raw.write_text(json.dumps(source))
        result,report=self.refine(source,'eu quero cantar com você nesta noite')
        self.assertIn('cantar',result[0]['text'])
        self.assertNotIn('gastar',result[0]['text'])
        self.assertGreater(report['guide_changes'],0);self.assertEqual(report['aligned_words'],7)
        self.assertEqual(source,before);self.assertEqual(json.loads(raw.read_text()),before)
        self.assertTrue(self.backends[0].closed)

    def test_rejected_guide_alignment_keeps_supported_original_instead_of_forcing_guide(self):
        class Reject(Backend):
            def align(self,emission,text):
                result=super().align(emission,text)
                if 'cantar' in text:
                    for word in result:word['alignment_score']=.001
                return result
        self.factory=Reject
        result,report=self.refine(words('eu quero gastar com voce nesta noite'),'eu quero cantar com você nesta noite')
        self.assertIn('gastar',result[0]['text']);self.assertEqual(report['guide_changes'],0)

    def test_ctc_and_voice_detector_reject_unvoiced_hallucination_even_with_background_audio(self):
        class RejectNoise(Backend):
            def align(self,emission,text):
                result=super().align(emission,text)
                for item in result:item['alignment_score']=.01
                return result
        self.factory=RejectNoise
        result,report=self.refine(words('fantasma repetido',6),voice_regions=[(.5,3)])
        self.assertEqual(result,[]);self.assertEqual(report['unsupported_voice_words'],2)

    def test_cache_reuses_alignment_but_guide_or_audio_change_invalidates_it(self):
        source=words('eu quero cantar')
        first=self.refine(source)
        second=self.refine(source)
        self.assertEqual(first,second);self.assertEqual(len(self.backends),1)
        self.refine(source,'eu quero cantar mais');self.assertEqual(len(self.backends),2)
        self.audio.write_bytes(b'changed audio');self.refine(source);self.assertEqual(len(self.backends),3)

    def test_model_failure_is_reported_and_still_removes_silent_tail(self):
        self.factory=Mock(side_effect=RuntimeError('modelo indisponível'))
        result,report=self.refine(words('voz',1)+words('fantasma',11))
        self.assertEqual(result[0]['text'],'voz');self.assertEqual(report['status'],'fallback')
        self.assertIn('modelo indisponível',report['error'])
        self.assertFalse((self.root/'transcribed_segments.json').exists())

    def test_one_failed_chunk_preserves_successful_alignment_and_retries_later(self):
        class Partial(Backend):
            calls=0
            def emission(self,audio):
                self.calls+=1
                if self.calls==2:raise RuntimeError('falha de um trecho')
                return super().emission(audio)
        self.factory=Partial
        source=words('eu quero cantar',1)+words('outra frase aqui',7)
        result,report=self.refine(source)
        self.assertEqual(report['status'],'partial');self.assertEqual(report['aligned_words'],3)
        self.assertTrue(result[0]['words'][0].get('alignment_chars'))
        self.assertEqual(result[-1]['words'],source[-1]['words'])

    def test_alignment_cannot_jump_a_whole_verse(self):
        original=words('eu quero cantar',.1)[0]['words']
        distant=[dict(start=w['start']+4,end=w['end']+4,alignment_score=.95) for w in original]
        self.assertFalse(accept_alignment(distant,original,10,0))

    def test_empty_silence_and_unsupported_script_do_not_download_any_model(self):
        self.factory=Mock(side_effect=AssertionError('must not download'))
        self.decode.return_value=np.zeros(16000*12,np.float32)
        result,report=self.refine(words('fantasma'))
        self.assertEqual(result,[])
        self.decode.return_value=sounding(12,.5,10)
        result,report=self.refine(words('日本語'))
        self.assertEqual(result[0]['text'],'日本語');self.factory.assert_not_called()

    def test_cancel_propagates_and_does_not_publish_partial_cache(self):
        class Cancel(Backend):
            def emission(self,audio):raise InterruptedError('cancelado')
        self.factory=Cancel
        with self.assertRaises(InterruptedError):self.refine(words('eu quero cantar'))
        self.assertFalse((self.root/'aligned_lyrics.json').exists())

    def test_quality_upgrade_invalidates_old_outputs_and_preserves_manual_reviews(self):
        checkpoint=self.root/'stage_checkpoints.json'
        checkpoint.write_text(json.dumps(dict(completed_stages={name:{'saved':True} for name in
            ['transcription_ready','transcription_reviewed','subtitles_generated','video_rendered','subtitle_original_ready']})))
        invalidate_quality_outputs(self.root);saved=json.loads(checkpoint.read_text())
        self.assertEqual(set(saved['completed_stages']),{'transcription_ready','transcription_reviewed'})
        self.assertEqual(saved['lyric_quality_version'],QUALITY_VERSION)
        invalidate_quality_outputs(self.root);self.assertEqual(saved,json.loads(checkpoint.read_text()))

    def test_letters_use_measured_times_and_keep_punctuation_accents_and_spaces(self):
        source=words('Olá mundo',1)
        source[0]['words'][0]['alignment_chars']=[dict(text='O',start=1,end=1.05),dict(text='l',start=1.1,end=1.15),dict(text='á',start=1.2,end=1.3)]
        target=self.root/'quality.ass'
        generate_ass_karaoke(source,str(target),show_instrumental=False,show_next_line_preview=False)
        text=target.read_text()
        self.assertIn(r'\kt0\kf5',text);self.assertIn(r'\kt20\kf10',text)
        import re
        content=' '.join(line.split(',,',1)[-1] for line in text.splitlines() if line.startswith('Dialogue:'))
        content=re.sub(r'\{[^}]*\}','',content)
        self.assertIn('Olá mundo',content)

    def test_impossible_or_low_confidence_alignment_is_never_accepted(self):
        self.assertFalse(accept_alignment([dict(start=1,end=20,alignment_score=.9)],[],2))
        self.assertFalse(accept_alignment([dict(start=0,end=1,alignment_score=.001)],[],2))
