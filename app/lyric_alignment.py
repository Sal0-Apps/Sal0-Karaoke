"""Audio-supported lyric correction and local CTC alignment, on the original timeline.

Raw Whisper results and manual reviews are never overwritten. Model weights use
Meta's separate MMS license; see THIRD_PARTY_MODELS.md. Torch is imported lazily.
"""
import copy
import difflib
import gc
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import time
import unicodedata

import numpy as np

from lyric_guide import normalize_word, prepare_lyrics_guide, apply_guide_boundaries
from karaoke_generator import split_and_wrap_segments
from whisper_audio import load_whisper_audio
import process_manager as pm
from runtime_resources import available_cpu_threads, release_cached_whisper

logger = logging.getLogger('karaoke')
QUALITY_VERSION = 3
SAMPLE_RATE = 16000
MODEL_URL = 'https://dl.fbaipublicfiles.com/mms/torchaudio/ctc_alignment_mling_uroman/model.pt'
MODEL_DIR = '/data/output/models/lyric_alignment'


def roman_word(text):
    normalized = unicodedata.normalize('NFKD', str(text).replace('’', "'"))
    normalized = ''.join(char for char in normalized if not unicodedata.combining(char)).lower()
    # Do not silently transliterate unknown scripts or invent a pronunciation for digits.
    if any(char.isalpha() and char not in 'abcdefghijklmnopqrstuvwxyz' for char in normalized) or any(char.isdigit() for char in normalized):
        return ''
    result = re.sub("[^a-z']", '', normalized)
    return result if any(char.isalpha() for char in result) else ''


def guided_candidate(guide, words):
    """Find an ordered, strongly anchored local phrase; CTC must still verify it."""
    observed = [normalize_word(word['word']) for word in words]
    tokens = prepare_lyrics_guide(guide).split()
    expected = [normalize_word(token) for token in tokens]
    if len(observed) < 3 or not expected or len(expected) > 12000:
        return None
    # Smith-Waterman: local context permits a chorus printed once to match again,
    # while a missing guide verse cannot shift the rest of the recording.
    rows = np.zeros((len(observed)+1, len(expected)+1), dtype=np.float32)
    moves = np.zeros(rows.shape, dtype=np.uint8)
    best = (0., 0, 0)
    for i, actual in enumerate(observed, 1):
        for j, wanted in enumerate(expected, 1):
            reward = 2.5 if actual == wanted else -1.4
            choices = (0., rows[i-1,j-1]+reward, rows[i-1,j]-1.5, rows[i,j-1]-1.5)
            move = max(range(4), key=choices.__getitem__)
            rows[i,j], moves[i,j] = choices[move], move
            if choices[move] > best[0]:
                best = (choices[move], i, j)
    _, end_i, end_j = best
    i, j = end_i, end_j
    exact = 0
    while i and j and moves[i,j]:
        move = moves[i,j]
        if move == 1:
            exact += observed[i-1] == expected[j-1]
            i, j = i-1, j-1
        elif move == 2:
            i -= 1
        else:
            j -= 1
    if (end_i-i < .7*len(observed) or exact < max(2, math.ceil(.5*len(observed)))
            or i > 1 or end_i < len(observed)-1 or end_j-j > 1.6*(end_i-i)+3):
        return None
    candidate = [str(word['word']).strip() for word in words[:i]] + tokens[j:end_j] + [str(word['word']).strip() for word in words[end_i:]]
    if [normalize_word(token) for token in candidate] == observed:
        return None
    if not candidate or any(not roman_word(token) for token in candidate):
        return None
    return candidate


def acoustic_baseline(segments, checks):
    """Keep harmless guide spelling; require CTC to validate lexical substitutions."""
    result=copy.deepcopy(segments);index=0
    for segment in result:
        for word in segment.get('words',[]):
            if not normalize_word(word.get('word','')):continue
            if index>=len(checks):return copy.deepcopy(segments)
            check=checks[index];index+=1
            recognized=str(check.get('recognized',''))
            current=str(word.get('word',''))
            if recognized and normalize_word(recognized)!=normalize_word(current):
                prefix=current[:len(current)-len(current.lstrip())]
                suffix=current[len(current.rstrip()):]
                word['word']=prefix+recognized.strip()+suffix
        segment['text']=''.join(str(word.get('word','')) for word in segment.get('words',[])).strip()
    return result


class AudioEvidence:
    """Read-only activity map. Silence is measured, never cut from the audio."""
    def __init__(self, audio, sample_rate=SAMPLE_RATE):
        self.audio = np.asarray(audio, dtype=np.float32)
        self.rate = sample_rate
        self.duration = len(self.audio)/sample_rate
        self.hop = max(1, int(sample_rate*.02))
        padding = (-len(self.audio)) % self.hop
        samples = np.pad(self.audio, (0,padding)) if padding else self.audio
        frames = samples.reshape(-1,self.hop)
        # Accumulate in float64 without allocating two full-length float64 tracks.
        self.rms = np.sqrt(np.einsum('ij,ij->i', frames, frames, dtype=np.float64) / self.hop) if len(frames) else np.array([])
        self.reference = float(np.quantile(self.rms,.98)) if len(self.rms) else 0.
        self.threshold = max(1e-8,self.reference*.005)
        self.active = self.rms > self.threshold

    def bounds(self, start, end, margin=.08):
        first=max(0,int((start-margin)*self.rate/self.hop))
        last=min(len(self.active),math.ceil((end+margin)*self.rate/self.hop))
        indices=np.flatnonzero(self.active[first:last])
        if not len(indices):
            return None
        return ((first+int(indices[0]))*self.hop/self.rate,
                min(self.duration,(first+int(indices[-1])+1)*self.hop/self.rate))


def remove_overlapping_phrases(words):
    """Two near-identical clocks describe one event, not two sung refrains."""
    normalized = [normalize_word(word['word']) for word in words]
    kept = [True] * len(words)
    previous = {}

    def same_event(left, right):
        overlap = min(left['end'], right['end']) - max(left['start'], right['start'])
        shortest = min(left['end'] - left['start'], right['end'] - right['start'])
        return (abs(left['start'] - right['start']) <= .25
                and abs(left['end'] - right['end']) <= .35
                and overlap >= shortest * .6)

    for index in range(len(words) - 2):
        if not all(kept[index:index+3]):
            continue
        key = tuple(normalized[index:index+3])
        if not all(key):
            continue
        duplicate = False
        for before in reversed(previous.get(key, [])[-8:]):
            if before + 3 > index or not all(kept[before:before+3]):
                continue
            length = 0
            while (index + length < len(words) and before + length < index
                   and kept[before+length] and kept[index+length]
                   and normalized[before+length] == normalized[index+length]
                   and same_event(words[before+length], words[index+length])):
                length += 1
            if length >= 3:
                kept[index:index+length] = [False] * length
                duplicate = True
                break
        if not duplicate:
            previous.setdefault(key, []).append(index)
    return [word for word, keep in zip(words, kept) if keep], kept.count(False)


def repetition_candidates(words, guide):
    """Propose adjacent ASR loops; acoustic likelihood must approve a deletion."""
    texts = [str(word['word']).strip() for word in words]
    observed = [normalize_word(text) for text in texts]
    expected = [normalize_word(text) for text in prepare_lyrics_guide(guide).split()]
    proposals = []
    seen = set()
    for length in range(min(24, len(words)//2), 2, -1):
        for start in range(len(words) - 2*length + 1):
            phrase = observed[start:start+length]
            if not all(phrase) or phrase != observed[start+length:start+2*length]:
                continue
            if words[start+length]['start'] - words[start+length-1]['end'] > .8:
                continue
            copies = 2
            while observed[start+copies*length:start+(copies+1)*length] == phrase:
                copies += 1
            requested = 1
            for index in range(len(expected)-length+1):
                count = 0
                while expected[index+count*length:index+(count+1)*length] == phrase:
                    count += 1
                requested = max(requested, count)
            for keep in range(requested, copies):
                candidate = texts[:start+keep*length] + texts[start+copies*length:]
                key = tuple(candidate)
                if key not in seen:
                    proposals.append(candidate)
                    seen.add(key)
    return proposals[:3]


def coalesce_repetition_windows(segments, guide):
    """A short ASR chunk boundary must not hide a loop from acoustic comparison."""
    result = []
    for segment in segments:
        if result:
            previous = result[-1]
            combined = previous['words'] + segment['words']
            if (segment['end'] - previous['start'] <= 19.1
                    and repetition_candidates(combined, guide)):
                result[-1] = dict(start=previous['start'], end=segment['end'],
                    text=''.join(word['word'] for word in combined).strip(), words=combined)
                continue
        result.append(segment)
    return result


def supports_deletion(backend, emission, original, candidate):
    """Compare hypotheses against every audio frame, including the removed span.

    A good mean score on the surviving words alone can hide an actually sung
    repetition. CTC sequence likelihood penalizes that unexplained vocal audio.
    """
    score = getattr(backend, 'sequence_score', None)
    if not callable(score):
        return False
    full, reduced = score(emission, original), score(emission, candidate)
    return math.isfinite(reduced) and reduced > full + 5.


def clean_segments(segments, evidence, voice_regions=None):
    """Remove words outside media/sound and invalid overlapping ASR loops."""
    words=[]; removed=0; trimmed=0
    for segment in segments or []:
        for source in segment.get('words',[]):
            try:
                start,end=float(source['start']),float(source['end'])
            except (KeyError,TypeError,ValueError):
                removed+=1;continue
            if not math.isfinite(start+end) or end<=start or end<=0 or start>=evidence.duration or not str(source.get('word','')).strip():
                removed+=1;continue
            start,end=max(0.,start),min(evidence.duration,end)
            if voice_regions:
                supported = [max(start, left) for left, right in voice_regions
                             if min(end, right) > max(start, left)]
                if supported and min(supported) - start > .25:
                    onset = min(supported)
                    lead = evidence.rms[int(start*evidence.rate/evidence.hop):int(onset*evidence.rate/evidence.hop)]
                    voice = evidence.rms[int(onset*evidence.rate/evidence.hop):math.ceil(end*evidence.rate/evidence.hop)]
                    # A faint Demucs instrumental leak is not the sung onset.
                    # Strong/quiet actual singing remains supported by its own
                    # energy; a missed VAD region alone never deletes a word.
                    if len(lead) and len(voice) and np.quantile(lead,.9) < np.quantile(voice,.75)*.1:
                        start = onset
            bounds=evidence.bounds(start,end,margin=0)
            if bounds is None:
                removed+=1;continue
            # Long unsupported tails must not keep a completed verse on screen.
            # Do not add a visual lead-in before the first supported sound.
            corrected_start=max(start,bounds[0]) if bounds[0]-start>.03 else start
            corrected_end=min(end,bounds[1]+.08) if end-bounds[1]>.18 else end
            if corrected_end<=corrected_start:
                removed+=1;continue
            item=copy.deepcopy(source)
            item.update(start=corrected_start,end=corrected_end)
            if corrected_start!=source['start'] or corrected_end!=source['end']:
                item.pop('alignment_chars',None);trimmed+=1
            # Exact same-time duplicates are decoder artifacts, not a sung chorus.
            duplicate=next((previous for previous in reversed(words[-12:])
                if normalize_word(previous['word'])==normalize_word(item['word'])
                and abs(previous['start']-item['start'])<.035
                and abs(previous['end']-item['end'])<.035),None)
            if duplicate:
                removed+=1;continue
            words.append(item)
    words, overlap_removed = remove_overlapping_phrases(words)
    removed += overlap_removed
    words.sort(key=lambda word:(word['start'],word['end']))
    return regroup(words),dict(silent_or_invalid_words=removed,trimmed_words=trimmed)


def regroup(words):
    groups=[];current=[]
    for word in words:
        if current and (word['start']-current[-1]['end']>=.65 or word['end']-current[0]['start']>11 or len(current)>=24):
            groups.append(current);current=[]
        current.append(word)
    if current:groups.append(current)
    return [dict(start=group[0]['start'],end=max(w['end'] for w in group),
                 text=''.join(w['word'] for w in group).strip(),words=group) for group in groups]


def _download_model(directory, progress, cancel):
    """Atomic, cancellable first use; do not leave a partial checkpoint as a model."""
    import requests
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/'model.pt'
    if target.is_file() and target.stat().st_size>100_000_000:
        return
    temporary=directory/'model.pt.downloading'
    try:
        with requests.get(MODEL_URL,stream=True,timeout=(15,30)) as response:
            response.raise_for_status();total=int(response.headers.get('Content-Length') or 0);received=0;last=0.
            with temporary.open('wb') as output:
                for chunk in response.iter_content(1024*1024):
                    cancel()
                    if not chunk:continue
                    output.write(chunk);received+=len(chunk)
                    if time.monotonic()-last>=1:
                        last=time.monotonic()
                        progress(round(received/total*100) if total else 0,f'Baixando alinhador: {received//1048576} MB'+(f' de {total//1048576} MB' if total else ''))
            if (total and received!=total) or received<100_000_000:
                raise RuntimeError('O modelo de alinhamento não foi baixado por completo.')
        cancel();os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)


class MMSAligner:
    def __init__(self, progress, cancel):
        import torch
        from torchaudio.pipelines import MMS_FA
        self.torch=torch;self.cancel=cancel
        self.old_threads=torch.get_num_threads()
        release_cached_whisper()
        torch.set_num_threads(available_cpu_threads())
        try:
            directory=os.getenv('KARAOKE_ALIGNMENT_MODEL_DIR',MODEL_DIR)
            _download_model(directory,progress,cancel)
            progress(0,'Carregando o modelo de alinhamento acústico na CPU…')
            self.model=MMS_FA.get_model(with_star=False,dl_kwargs=dict(model_dir=directory,progress=False)).eval().to('cpu')
            self.tokenizer=MMS_FA.get_tokenizer();self.aligner=MMS_FA.get_aligner()
        except BaseException:
            torch.set_num_threads(self.old_threads)
            raise

    def emission(self,audio):
        self.cancel()
        with self.torch.inference_mode():
            emission,_=self.model(self.torch.from_numpy(np.asarray(audio,dtype=np.float32).copy()).unsqueeze(0))
        self.cancel()
        return emission[0].cpu(),len(audio)/SAMPLE_RATE

    def align(self, emission, words):
        values,duration=emission
        normalized=[roman_word(word) for word in words]
        if any(not word for word in normalized):
            return None
        spans=self.aligner(values,self.tokenizer(normalized))
        ratio=duration/values.size(0);aligned=[]
        for text,tokens in zip(words,spans):
            if not tokens:return None
            score=sum(float(t.score)*len(t) for t in tokens)/sum(len(t) for t in tokens)
            chars=[];cursor=0
            for char in str(text).strip():
                encoded="'" if char in {"'",'’'} else roman_word(char)
                # Punctuation has no independent sound and remains attached to its word.
                if not encoded:
                    chars.append(dict(text=char));continue
                count=len(encoded);selected=tokens[cursor:cursor+count];cursor+=count
                if len(selected)!=count:return None
                chars.append(dict(text=char,start=selected[0].start*ratio,end=selected[-1].end*ratio))
            if cursor!=len(tokens):return None
            aligned.append(dict(word=' '+str(text).strip(),start=tokens[0].start*ratio,
                                end=tokens[-1].end*ratio,alignment_score=score,alignment_chars=chars))
        return aligned

    def sequence_score(self, emission, words):
        values, _ = emission
        normalized = [roman_word(word) for word in words]
        if not normalized or any(not word for word in normalized):
            return -math.inf
        targets = [token for word in self.tokenizer(normalized) for token in word]
        self.cancel()
        with self.torch.inference_mode():
            loss = self.torch.nn.functional.ctc_loss(
                values.log_softmax(-1).unsqueeze(1),
                self.torch.tensor(targets, dtype=self.torch.long),
                [values.size(0)], [len(targets)], blank=0, reduction='sum')
        self.cancel()
        return -float(loss)

    def close(self):
        if hasattr(self,'model'):del self.model
        self.torch.set_num_threads(self.old_threads)
        gc.collect()


def _mean_score(words):
    return sum(word.get('alignment_score',0.) for word in words)/max(1,len(words))


def detect_voice_regions(audio):
    """Silero only supplies supporting evidence; the waveform stays intact."""
    try:
        from faster_whisper.vad import get_speech_timestamps, VadOptions
        options=VadOptions(threshold=.25,min_speech_duration_ms=100,min_silence_duration_ms=250,speech_pad_ms=0)
        return [(item['start']/SAMPLE_RATE,item['end']/SAMPLE_RATE)
                for item in get_speech_timestamps(audio,options)]
    except InterruptedError:raise
    except Exception:
        logger.warning('Detector auxiliar de voz indisponível; mantendo decisões conservadoras.')
        return None


def has_voice(start,end,regions):
    if regions is None:return True  # Unknown is not evidence of silence.
    return any(min(end+.12,right)-max(start-.12,left)>=min(.04,(end-start)*.2) for left,right in regions)


def invalidate_quality_outputs(cache_dir):
    """Old rendered results cannot hide the new timing; preserve every human review."""
    path=Path(cache_dir)/'stage_checkpoints.json'
    try: saved=json.loads(path.read_text())
    except (OSError,ValueError): saved={'completed_stages':{}}
    if saved.get('lyric_quality_version')==QUALITY_VERSION:return
    completed=saved.setdefault('completed_stages',{})
    for stage in ('subtitles_generated','video_rendered','subtitle_original_ready',
                  'subtitle_translation_finished','subtitle_video_rendered'):
        completed.pop(stage,None)
    saved['lyric_quality_version']=QUALITY_VERSION
    temporary=path.with_suffix('.json.quality.tmp')
    temporary.write_text(json.dumps(saved,ensure_ascii=False))
    os.replace(temporary,path)


def accept_alignment(aligned, original, window_duration, window_start=None):
    if not aligned or len(aligned)>max(2,window_duration*8):return False
    previous=0.
    for word in aligned:
        start,end=word['start'],word['end']
        if not math.isfinite(start+end) or start<previous-.02 or end<=start or end>window_duration+.02:return False
        if word.get('alignment_score',0)<.045:return False
        previous=end
    if window_start is not None and len(aligned)==len(original):
        movements=[abs(word['start']+window_start-source['start']) for word,source in zip(aligned,original)]
        if max(movements,default=0)>3 or float(np.median(movements))>1.5:return False
    return _mean_score(aligned)>=.12


def refine_lyrics(audio_path, segments, guide, cache_dir, context=None, progress=None,
                  cancel=None, backend_factory=None, decode=None, voice_regions=None):
    """A second pass: use guide text only when supported by acoustic alignment."""
    cancel=cancel or pm.check_cancelled;progress=progress or (lambda percent,detail:None)
    cancel()
    info=os.stat(audio_path)
    signature=hashlib.sha256(json.dumps(dict(version=QUALITY_VERSION,segments=segments,
        guide=prepare_lyrics_guide(guide),source=dict(size=info.st_size,mtime=info.st_mtime_ns),
        context=context or {},engine=os.getenv('KARAOKE_ALIGNMENT','mms')),
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    target=Path(cache_dir)/'aligned_lyrics.json'
    try:
        saved=json.loads(target.read_text())
        if saved['signature']==signature and saved['report'].get('status')=='aligned':
            cancel();invalidate_quality_outputs(cache_dir);progress(100,'Alinhamento acústico recuperado do cache.')
            return saved['segments'],saved['report']
    except (OSError,ValueError,KeyError,TypeError):pass
    progress(0,'Verificando voz e silêncio sem cortar a linha do tempo…')
    audio=(decode or load_whisper_audio)(audio_path)
    evidence=AudioEvidence(audio)
    cleaned,report=clean_segments(segments,evidence)
    cleaned=coalesce_repetition_windows(cleaned, guide)
    report.update(version=QUALITY_VERSION,status='cleaned',aligned_words=0,guide_changes=0,unsupported_voice_words=0,
                  repeated_words=0,guide_verses=0,
                  rejected_groups=0,source=os.path.basename(str(audio_path)))
    backend=None;result=[]
    try:
        eligible=any(segment['end']-segment['start']<=19.1 and all(roman_word(w['word']) for w in segment['words']) for segment in cleaned)
        if eligible and os.getenv('KARAOKE_ALIGNMENT','mms').lower() not in {'off','0','false'}:
            backend=(backend_factory or MMSAligner)(progress,cancel)
            if voice_regions is None and backend_factory is None:
                voice_regions=detect_voice_regions(audio)
        for index,segment in enumerate(cleaned):
            cancel();original=segment['words'];selected=copy.deepcopy(original)
            start=max(0.,segment['start']-.45);end=min(evidence.duration,segment['end']+.45)
            try:
                if backend and end-start<=20 and all(roman_word(w['word']) for w in original):
                    progress(round(index/max(1,len(cleaned))*100),f'Alinhando trecho {index+1} de {len(cleaned)} com a voz…')
                    emission=backend.emission(audio[int(start*SAMPLE_RATE):math.ceil(end*SAMPLE_RATE)])
                    texts=[str(w['word']).strip() for w in original]
                    baseline=backend.align(emission,texts)
                    candidate=guided_candidate(guide,original)
                    chosen=baseline
                    if candidate:
                        guided=backend.align(emission,candidate)
                        if (accept_alignment(guided,original,end-start,start)
                                and (len(candidate) >= len(texts)
                                     or supports_deletion(backend, emission, texts, candidate))
                                and _mean_score(guided)>=_mean_score(baseline or [])*.8-.015):
                            chosen=guided
                            report['guide_changes']+=sum(tag!='equal' for tag,*_ in difflib.SequenceMatcher(None,texts,candidate,autojunk=False).get_opcodes())
                    # A complete duplicated phrase can defeat local guide matching.
                    # Test a bounded set of loop hypotheses on the same emissions.
                    if chosen is baseline:
                        best_loop = None
                        best_score = -math.inf
                        for reduced in repetition_candidates(original, guide):
                            aligned = backend.align(emission, reduced)
                            if (accept_alignment(aligned, original, end-start, start)
                                    and _mean_score(aligned) >= _mean_score(baseline or [])*.8-.015
                                    and supports_deletion(backend, emission, texts, reduced)):
                                score = backend.sequence_score(emission, reduced)
                                if score > best_score:
                                    best_loop = aligned
                                    best_score = score
                        if best_loop:
                            chosen = best_loop
                            report['repeated_words'] += len(texts) - len(best_loop)
                    if chosen is baseline and baseline and len(baseline)==len(original):
                        unsupported={i for i,word in enumerate(baseline)
                            if word.get('alignment_score',1.)<.08
                            and not has_voice(word['start']+start,word['end']+start,voice_regions)
                            and not has_voice(original[i]['start'],original[i]['end'],voice_regions)}
                        if unsupported:
                            selected=[word for i,word in enumerate(selected) if i not in unsupported]
                            report['unsupported_voice_words']+=len(unsupported)
                            result.extend(selected)
                            continue
                    if accept_alignment(chosen,original,end-start,start):
                        selected=copy.deepcopy(chosen)
                        for word in selected:
                            word['start']+=start;word['end']+=start
                            for char in word.get('alignment_chars',[]):
                                if 'start' in char:char['start']+=start;char['end']+=start
                        report['aligned_words']+=len(selected)
                    else:
                        report['rejected_groups']+=1
            except InterruptedError:
                raise
            except Exception:
                logger.exception('Não foi possível alinhar um trecho; preservando apenas esse trecho original.')
                selected=copy.deepcopy(original)
                report['retryable_failures']=report.get('retryable_failures',0)+1

            result.extend(selected)
        report['status']='partial' if report.get('retryable_failures') else ('aligned' if report['aligned_words'] else 'cleaned')
    except InterruptedError:
        raise
    except Exception as error:
        logger.exception('Alinhamento indisponível; preservando transcrição e limpeza de silêncio.')
        result=[word for segment in cleaned for word in segment['words']]
        report.update(status='fallback',aligned_words=0,guide_changes=0,error=str(error)[:300])
    finally:
        if backend is not None:backend.close()
    cancel()
    final,extra=clean_segments(regroup(result),evidence,voice_regions)
    report['silent_or_invalid_words']+=extra['silent_or_invalid_words'];report['trimmed_words']+=extra['trimmed_words']
    # Missing/quiet voice can yield an empty result; never restore hallucinated text.
    report['discarded_words']=report['silent_or_invalid_words']+report['unsupported_voice_words']+report['repeated_words']
    if guide:
        final, report['guide_verses'] = apply_guide_boundaries(guide, final)
        final = split_and_wrap_segments(final)
    temporary=target.with_suffix('.json.tmp')
    try:
        temporary.write_text(json.dumps(dict(signature=signature,segments=final,report=report),ensure_ascii=False))
        cancel();os.replace(temporary,target)
    finally:
        temporary.unlink(missing_ok=True)
    invalidate_quality_outputs(cache_dir)
    progress(100,f"{report['aligned_words']} palavras alinhadas · {report['discarded_words']} sem apoio no áudio removidas")
    return final,report
