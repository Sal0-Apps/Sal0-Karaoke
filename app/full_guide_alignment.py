"""Recover omitted guide words from whole-song acoustic evidence.

The guide retains its order and every printed repetition. It supplies text;
the acoustic backend supplies all clocks. Unrelated/unsupported lines are
rejected together, rather than reduced to misleading fragments. ASR remains
available for audio not represented in the guide and for uncertain lines.
"""
import copy
import difflib
import math
import hashlib
import json
import os
from pathlib import Path

import numpy as np

from lyric_guide import normalize_word, prepare_lyrics_guide

WHISPER_GUIDE_VERSION = 5


def ordered_anchors(expected, observed):
    """Minimum-edit monotonic matching keeps incomplete identical refrains distinct."""
    n, m = len(expected), len(observed)
    if n*m > 8_000_000:
        matcher = difflib.SequenceMatcher(None, expected, observed, autojunk=False)
        anchors = {i+k: j+k for i, j, size in matcher.get_matching_blocks() for k in range(size)}
        return anchors, max(0, n-m)
    trace = np.zeros((n+1, m+1), dtype=np.uint8)
    trace[1:, 0] = 2; trace[0, 1:] = 3
    previous = list(range(m+1))
    for i, wanted in enumerate(expected, 1):
        current = [i]+[0]*m
        for j, actual in enumerate(observed, 1):
            diagonal = previous[j-1]+(wanted != actual)
            deletion, insertion = previous[j]+1, current[j-1]+1
            value = min(diagonal, deletion, insertion)
            current[j] = value
            trace[i, j] = 1 if diagonal == value else 2 if deletion == value else 3
        previous = current
    anchors, missing = {}, 0
    i, j = n, m
    while i or j:
        direction = trace[i, j]
        if direction == 1:
            if expected[i-1] == observed[j-1]: anchors[i-1] = j-1
            i -= 1; j -= 1
        elif direction == 2:
            missing += 1; i -= 1
        else:
            j -= 1
    return anchors, missing


def trim_source_silence(audio, words):
    """Remove only digital silence from clocks on the actual ASR source.

    This never uses the energy of a later separated stem. A measured leading
    silence boundary also prevents CTC from moving the onset back into it.
    """
    output=copy.deepcopy(words)
    for word in output:
        if not math.isfinite(word['start']+word['end']) or word['end'] <= word['start']:return None
        first=max(0,int(word['start']*16000));last=min(len(audio),math.ceil(word['end']*16000))
        active=np.flatnonzero(np.abs(audio[first:last]) > 1e-8)
        if not len(active):return None
        start=max(word['start'],(first+int(active[0]))/16000)
        end=min(word['end'],(first+int(active[-1])+1)/16000)
        if start >= end:return None
        if start-word['start'] >= .05:word['guide_source_start_bound']=start
        word.update(start=start,end=end)
    return output


class WhisperGuideBackend:
    def __init__(self, model_size, audio, start, cancel):
        from transcriber import _load_selected_model
        from runtime_resources import whisper_runtime_options
        from faster_whisper.tokenizer import Tokenizer
        cancel()
        self.model = _load_selected_model(model_size, whisper_runtime_options('max_quality'))
        language = self.model.detect_language(audio=audio[int(start*16000):int((start+30)*16000)])[0]
        self.tokenizer = Tokenizer(self.model.hf_tokenizer, self.model.model.is_multilingual,
                                   task='transcribe', language=language)
        self.language = language
        self.cancel = cancel

    def align(self, audio, left, right, words):
        clip = audio[int(left*16000):int(right*16000)]
        text = ' '+' '.join(word.replace('’', "'").replace('‘', "'") for word in words)
        tokens = self.tokenizer.encode(text)
        if len(tokens) > 220 or len(clip) < 1600 or len(clip) > 30*16000:
            return None
        self.cancel()
        features = self.model.feature_extractor(clip, padding=0)
        encoded = self.model.encode(features)
        aligned = self.model.find_alignment(self.tokenizer, [tokens], encoded, round(len(clip)/160))[0]
        self.cancel()
        result, cursor = [], 0
        for word in words:
            expected = normalize_word(word); selected = []; observed = ''
            while cursor < len(aligned) and (not selected or len(observed) < len(expected)):
                selected.append(aligned[cursor]); cursor += 1
                observed += normalize_word(selected[-1]['word'])
            if not selected or observed != expected:
                return None
            while cursor < len(aligned) and not normalize_word(aligned[cursor]['word']):
                selected.append(aligned[cursor]); cursor += 1
            result.append(dict(word=' '+word, start=left+float(selected[0]['start']),
                end=left+float(selected[-1]['end']),
                probability=float(np.mean([item['probability'] for item in selected]))))
        if any(normalize_word(item['word']) for item in aligned[cursor:]):
            return None
        return result

    def recover_line(self, audio, left, right, words, earliest=0.):
        """Decode an uncertain verse independently, with no guide in its prompt.

        Only an actually recognized complete phrase can repair the failed
        alignment. All clocks come from this clip plus its source sample offset.
        """
        self.cancel()
        start_sample = max(0, int(left*16000))
        clip = audio[start_sample:min(len(audio),int(right*16000))]
        origin = start_sample/16000
        if len(clip) < 1600 or len(clip) > 29*16000:
            return None
        iterator, _ = self.model.transcribe(clip, language=self.language, task='transcribe',
            word_timestamps=True, beam_size=10, temperature=0,
            condition_on_previous_text=False, vad_filter=False,
            initial_prompt=None, hotwords=None, no_speech_threshold=.8,
            hallucination_silence_threshold=None)
        observed=[]
        for segment in iterator:
            self.cancel()
            for word in segment.words or []:
                if (not math.isfinite(word.start+word.end+float(getattr(word,'probability',0.) or 0.))
                        or not 0 <= word.start < word.end <= len(clip)/16000+.03
                        or not normalize_word(word.word)):
                    continue
                if not np.any(np.abs(clip[int(word.start*16000):math.ceil(word.end*16000)]) > 1e-8):
                    continue
                observed.append(dict(word=word.word,start=origin+float(word.start),end=origin+float(word.end),
                                     probability=float(getattr(word,'probability',0.) or 0.)))
        for first in range(len(observed)):
            cursor=first; selected=[]
            for text in words:
                wanted=normalize_word(text); heard=''; group=[]
                while cursor < len(observed) and len(heard) < len(wanted):
                    group.append(observed[cursor]);cursor+=1
                    heard += normalize_word(group[-1]['word'])
                if heard != wanted or not group:
                    break
                selected.append(dict(word=' '+text,start=group[0]['start'],end=group[-1]['end'],
                    probability=float(np.mean([word['probability'] for word in group]))))
            if (len(selected)==len(words) and selected[0]['start'] >= earliest-.04
                    and all(a['end'] <= b['start']+.04 for a,b in zip(selected,selected[1:]))
                    and float(np.mean([word['probability'] for word in selected])) >= .55):
                return trim_source_silence(audio,selected)
        return None


def guide_search_windows(offset, count, total, starts, ends, anchors, actual, duration, frontier):
    """Search with context, then recheck the local recording beyond ASR tails.

    Estimates only select audio. They never become output word clocks. A long
    instrumental or a missed suffix must not make the next window unalignable.
    """
    seen = set()
    def window(first, last, left, right):
        left, right = max(0., float(left)), min(duration, float(right))
        key = (first, last, round(left, 3), round(right, 3))
        if right-left < .1 or right-left > 29.01 or key in seen:
            return None
        seen.add(key)
        return first, last, left, right
    for context, padding in ((3, .35), (5, .7), (1, 2.), (5, 3.)):
        first, last = max(0, offset-context), min(total, offset+count+context)
        left, right = starts[first]-padding, ends[last-1]+padding
        if right-left > 29:
            first, last = offset, offset+count
            left, right = starts[first]-.5, ends[last-1]+.5
        candidate = window(first, last, left, right)
        if candidate:
            yield candidate
    local = [actual[anchors[i]] for i in range(offset, offset+count) if i in anchors
             and actual[anchors[i]]['end'] > frontier+.02]
    if local:
        left = max(frontier-.04, min(w['start'] for w in local)-5.)
        right = min(duration, max(w['end'] for w in local)+8.)
        if right-left > 29:
            center = (min(w['start'] for w in local)+max(w['end'] for w in local))/2
            left, right = max(frontier-.04, center-14.5), min(duration, center+14.5)
        candidate = window(offset, offset+count, left, right)
        if candidate:
            yield candidate
        return
    # Sparse recognition can miss a complete verse. Search forward in bounded,
    # overlapping clips up to the next measured anchor, with no clock guessing.
    following = [actual[anchors[i]]['start'] for i in anchors if i >= offset+count
                 and actual[anchors[i]]['start'] > frontier+.1]
    limit = min(duration, min(following)+1. if following else duration)
    left = max(0., frontier-.04)
    while left < limit-.1:
        right = min(limit, left+29.)
        candidate = window(offset, offset+count, left, right)
        if candidate:
            yield candidate
        if right >= limit:
            break
        left += 21.


def merge_confirmed_guide(segments, actual, anchors):
    """Replace only confirmed events; keep ASR for unconfirmed/missing verses."""
    covered = {anchors[word['guide_token_index']] for segment in segments
               for word in segment['words'] if word['guide_token_index'] in anchors}
    intervals = [(segment['start']-.08, segment['end']+.08) for segment in segments]
    rest = [copy.deepcopy(word) for index, word in enumerate(actual) if index not in covered
            and not any(left <= (word['start']+word['end'])/2 <= right for left,right in intervals)]
    output = copy.deepcopy(segments)
    group = []
    for word in rest:
        if group and word['start']-group[-1]['end'] > 1.:
            output.append(dict(start=group[0]['start'],end=group[-1]['end'],
                               text=''.join(w['word'] for w in group).strip(),words=group))
            group=[]
        group.append(word)
    if group:
        output.append(dict(start=group[0]['start'],end=group[-1]['end'],
                           text=''.join(w['word'] for w in group).strip(),words=group))
    return sorted(output, key=lambda segment:segment['start'])


def align_guide_with_whisper(audio_path, segments, guide, cache_dir, model_size,
                            context=None, progress=None, cancel=None, decode=None, backend_factory=None):
    """Use known text as the alignment target, rather than an ASR prompt.

    Recognized anchors only select bounded search windows. Every output clock
    comes from Whisper's audio/text alignment. Three context words on either
    side prevent each verse from being forced against the start of its window.
    """
    progress = progress or (lambda *_: None); cancel = cancel or (lambda: None)
    guide = prepare_lyrics_guide(guide)
    lines = [[word for word in line.split() if normalize_word(word)] for line in guide.splitlines()]
    lines = [line for line in lines if line]
    expected = [word for line in lines for word in line]
    report = dict(status='unconfirmed', engine='whisper_known_text', guide_total_words=len(expected),
                  guide_aligned_words=0, recovered_words=0, guide_rejected_lines=0)
    if not expected:
        return segments, report
    info = os.stat(audio_path)
    signature = hashlib.sha256(json.dumps(dict(version=WHISPER_GUIDE_VERSION, guide=guide,
        segments=segments, model=model_size, context=context or {}, source=[info.st_size, info.st_mtime_ns],
        runtime={key: os.getenv(key) for key in ('WHISPER_DEVICE', 'WHISPER_COMPUTE_TYPE')}),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    target = Path(cache_dir)/'guided_whisper_lyrics.json'
    try:
        cached = json.loads(target.read_text())
        if cached['signature'] == signature and cached['report']['status'] == 'aligned':
            cancel(); return cached['segments'], cached['report']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    from whisper_audio import load_whisper_audio
    audio = (decode or load_whisper_audio)(audio_path)
    duration = len(audio)/16000
    actual = [word for segment in segments for word in segment.get('words', [])]
    wanted = [normalize_word(word) for word in expected]
    recognized = [normalize_word(word['word']) for word in actual]
    anchors, missing = ordered_anchors(wanted, recognized)
    report['guide_anchor_words'] = len(anchors)
    if len(anchors) < len(expected)*.5 and duration > 29:
        run = strongest = 0; previous = (-2, -2)
        for expected_index, actual_index in sorted(anchors.items()):
            run = run+1 if (expected_index-1, actual_index-1) == previous else 1
            strongest = max(strongest, run); previous = expected_index, actual_index
        if strongest < min(4, len(expected)):
            return segments, report
    if anchors:
        positions = sorted(anchors)
        # These estimates select audio for the model; they are never output clocks.
        starts = np.interp(np.arange(len(expected)), positions, [actual[anchors[i]]['start'] for i in positions])
        ends = np.interp(np.arange(len(expected)), positions, [actual[anchors[i]]['end'] for i in positions])
    else:
        starts = np.zeros(len(expected)); ends = np.full(len(expected), duration)
    cancel(); progress(0, 'Alinhando a letra completa com o modelo Whisper escolhido…')
    backend = (backend_factory or WhisperGuideBackend)(model_size, audio, float(starts[0]), cancel)
    output, offset, frontier = [], 0, 0.
    for index, line in enumerate(lines):
        cancel()
        anchored = sum(token in anchors for token in range(offset, offset+len(line))) >= len(line)*.5
        selected, valid, attempt, best, alternatives = [], False, 0, None, []
        for attempt, (first,last,left,right) in enumerate(guide_search_windows(offset,len(line),len(expected),
                starts,ends,anchors,actual,duration,frontier),1):
            cancel()
            aligned = backend.align(audio, left, right, expected[first:last])
            selected = aligned[offset-first:offset-first+len(line)] if aligned else []
            trimmed=trim_source_silence(audio,selected)
            hypothesis=trimmed if trimmed is not None else selected
            selected=trimmed or []
            if len(hypothesis)==len(line) and all(normalize_word(word['word'])==normalize_word(text)
                    and math.isfinite(word['start']+word['end']+word.get('probability',0.)) for word,text in zip(hypothesis,line)):
                confidence=float(np.mean([word.get('probability',0.) for word in hypothesis]))
                if confidence >= .20:
                    alternatives.append(copy.deepcopy(hypothesis))
                if best is None or confidence > best[0]:
                    best=confidence,copy.deepcopy(hypothesis)
            valid = (len(selected) == len(line) and
                all(math.isfinite(word['start']+word['end']+word.get('probability', 0.))
                    and left-.03 <= word['start'] < word['end'] <= right+.03 for word in selected)
                and selected[0]['start'] >= frontier-.04
                and all(a['end'] <= b['start']+.04 for a,b in zip(selected,selected[1:]))
                and all(normalize_word(word['word']) == normalize_word(text) for word,text in zip(selected,line))
                and float(np.mean([word.get('probability', 0.) for word in selected])) >= (.20 if anchored else .40))
            if valid:
                break
        if not valid and callable(getattr(backend,'recover_line',None)):
            hint=best[1] if best else []
            left=max(0.,frontier-.2,(hint[0]['start'] if hint else float(starts[offset]))-.8)
            right=min(duration,left+29.,max((hint[-1]['end'] if hint else float(ends[offset+len(line)-1]))+.8,
                                          left+min(12.,max(5.,len(line)*.6+2))))
            decoded=backend.recover_line(audio,left,right,line,earliest=frontier)
            if (len(decoded or []) == len(line)
                    and all(normalize_word(word['word']) == normalize_word(text)
                        and math.isfinite(word['start']+word['end']+word.get('probability',0.))
                        and left-.03 <= word['start'] < word['end'] <= right+.03
                        for word,text in zip(decoded,line))
                    and decoded[0]['start'] >= frontier-.04
                    and all(a['end'] <= b['start']+.04 for a,b in zip(decoded,decoded[1:]))
                    and float(np.mean([word.get('probability',0.) for word in decoded])) >= .55):
                selected=decoded;valid=True
                report['guide_independent_recoveries']=report.get('guide_independent_recoveries',0)+1
        report.setdefault('guide_line_checks', []).append(dict(line=index, confirmed=bool(valid),
            attempts=attempt, words=len(selected), mean_probability=round(float(np.mean([word.get('probability', 0.) for word in selected])), 4)
            if selected else 0., minimum_probability=round(min((word.get('probability',0.) for word in selected),default=0.),5),
            before_previous_verse=bool(selected and selected[0]['start'] < frontier-.04),
            invalid_clocks=sum(word['end'] <= word['start'] for word in selected)))
        if not valid:
            report['guide_rejected_lines'] += 1
            if alternatives:
                report.setdefault('guide_line_candidates',[]).append(dict(line=index,offset=offset,
                    unanchored_words=sum(token not in anchors for token in range(offset,offset+len(line))),
                    alternatives=alternatives))
        else:
            selected = copy.deepcopy(selected)
            for token_index, word in enumerate(selected, offset):
                word['guide_token_index'] = token_index
                word['guide_audio_confirmed'] = True
            output.append(dict(start=selected[0]['start'], end=selected[-1]['end'],
                text=''.join(word['word'] for word in selected).strip(), words=selected,
                guide_audio_confirmed=True))
            frontier = selected[-1]['end']
        offset += len(line)
        progress(round((index+1)/len(lines)*100), f'Conferindo verso {index+1} de {len(lines)} com a voz…')
    report['guide_aligned_words'] = sum(len(segment['words']) for segment in output)
    report['recovered_words'] = sum(word['guide_token_index'] not in anchors
                                  for segment in output for word in segment['words'])
    # One uncertain ending cannot undo every other independently confirmed verse.
    if report['guide_rejected_lines']:
        report['status'] = 'partial'
        result = merge_confirmed_guide(output,actual,anchors) if output else segments
        report['guide_unconfirmed_asr_words'] = sum(not bool(word.get('guide_audio_confirmed'))
            for segment in result for word in segment.get('words', []))
        return result, report
    matched_asr = set(anchors.values())
    extra = []
    for position, word in enumerate(actual):
        middle = (word['start']+word['end'])/2
        represented = any(line['start']-.6 <= middle <= line['end']+.6 for line in output)
        if (position not in matched_asr and not represented
                and word.get('probability', 0.) >= .55):
            if extra and word['start']-extra[-1]['end'] > 1.:
                extra = []
            extra.append(word)
            if len(extra) >= 3 and float(np.mean([item['probability'] for item in extra])) >= .65:
                # A partial printed guide cannot establish the repeat count.
                # Keep the recording's ASR/repetition analysis for that case.
                report['status'] = 'incomplete_guide'
                result = merge_confirmed_guide(output,actual,anchors)
                report['guide_unconfirmed_asr_words'] = sum(not bool(word.get('guide_audio_confirmed'))
                    for segment in result for word in segment['words'])
                return result, report
        else:
            extra = []
    report.update(status='aligned', guide_aligned_words=len(expected))
    temporary = target.with_suffix('.json.tmp')
    try:
        temporary.write_text(json.dumps(dict(signature=signature, segments=output, report=report), ensure_ascii=False))
        cancel(); os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return output, report


def local_candidate_alignments(backend, emission, segments, lines, candidates, audio=None, tail_margin=5.):
    """Re-use measured posteriors inside the neighboring confirmed verses.

    Whole-song CTC may match a short final phrase to instruments much later.
    Local windows are bounded by Whisper evidence, never the global CTC guess.
    """
    values,edges=emission;result={};clocks=[None]*sum(map(len,lines))
    offsets=np.cumsum([0]+[len(line) for line in lines])
    confirmed=[word for segment in segments for word in segment['words'] if word.get('guide_audio_confirmed')]
    for candidate in candidates or []:
        index=candidate['line']
        if not 0 <= index < len(lines):continue
        first,last=max(0,index-2),min(len(lines),index+2)
        context=[word for word in confirmed if offsets[first] <= word.get('guide_token_index',-1) < offsets[last]]
        hints=[word for alternative in candidate['alternatives'] for word in alternative]
        if not context or not hints:continue
        left=max(0.,min(word['start'] for word in context+hints)-(6. if audio is not None else 2.))
        right=min(float(edges[-1]),max(word['end'] for word in context+hints)+(tail_margin if audio is not None else 2.))
        if audio is not None:
            left=math.floor(left)
            right=min(float(edges[-1]),math.ceil(right))
        if not .1 <= right-left <= 29.:continue
        if audio is None:
            start=max(0,int(np.searchsorted(edges,left,side='right'))-1)
            end=min(len(values),int(np.searchsorted(edges,right,side='left')))
            local=values[start:end],edges[start:end+1]
        else:
            sample=int(left*16000)
            fresh,local_edges=backend.full_emission(audio[sample:int(right*16000)],lambda *_:None)
            local=fresh,local_edges+sample/16000
        aligned=backend.align_guide(local,lines[first:last])
        offset=int(offsets[index]-offsets[first])
        if aligned:
            result[index]=aligned[offset:offset+len(lines[index])]
            clocks[int(offsets[first]):int(offsets[last])]=aligned
    return result,clocks


def recover_unconfirmed_lines(segments, lines, local_alignments, candidates, evidence):
    """Require both models to support a failed verse before replacing its ASR.

    Whisper supplies an independently bounded phrase hypothesis; MMS supplies
    every positive-duration word clock. Weak/absent phones, disagreement,
    an earlier refrain, or lack of adjacent confirmed context cannot repair it.
    """
    output=copy.deepcopy(segments); recovered=[]
    expected=[word for line in lines for word in line]
    for candidate in candidates or []:
        line_index=candidate['line'];offset=candidate['offset']
        if not 0 <= line_index < len(lines) or offset != sum(map(len,lines[:line_index])):continue
        line=lines[line_index];selected=copy.deepcopy(local_alignments.get(line_index,[]))
        confirmed=[word for segment in output for word in segment['words'] if word.get('guide_audio_confirmed')]
        present={word.get('guide_token_index') for word in confirmed}
        if any(index in present for index in range(offset,offset+len(line))):continue
        previous=max((word['end'] for word in confirmed if word.get('guide_token_index',len(expected)) < offset),default=None)
        following=min((word['start'] for word in confirmed if word.get('guide_token_index',-1) >= offset+len(line)),default=None)
        if (len(line)<3 or len(selected)!=len(line)
                or any(normalize_word(word['word']) != normalize_word(text)
                    or not math.isfinite(word['start']+word['end']+word.get('alignment_score',0.))
                    or not 0 <= word['start'] < word['end'] <= evidence.duration
                    or word['end']-word['start'] > max(4.,len(normalize_word(text))*.8)
                    or word.get('alignment_score',0.) < .002
                    or evidence.bounds(word['start'],word['end']) is None for word,text in zip(selected,line))
                or any(a['end'] > b['start']+.02 for a,b in zip(selected,selected[1:]))
                or (previous is not None and selected[0]['start'] < previous-.04)
                or (following is not None and selected[-1]['end'] > following+.04)
                or not ((previous is not None and selected[0]['start']-previous <= 6.)
                        or (following is not None and following-selected[-1]['end'] <= 6.))
                or float(np.mean([word.get('alignment_score',0.) for word in selected])) < .02
                or sum(word.get('alignment_score',0.) >= .015 for word in selected) < math.ceil(len(line)/2)):
            continue
        agreement=None
        for hypothesis in candidate['alternatives']:
            if (len(hypothesis)!=len(line) or any(normalize_word(word['word']) != normalize_word(text)
                    or not math.isfinite(word['start']+word['end']+word.get('probability',0.))
                    or not 0 <= word['start'] <= word['end'] <= evidence.duration for word,text in zip(hypothesis,line))
                    or float(np.mean([word.get('probability',0.) for word in hypothesis])) < .20):continue
            movements=[abs(word['start']-hint['start']) for word,hint in zip(selected,hypothesis)]
            if max(movements) <= 3. and float(np.median(movements)) <= 2.:
                agreement=hypothesis;break
        if agreement is None:continue
        for index,(word,hint) in enumerate(zip(selected,agreement),offset):
            word.update(word=' '+expected[index],guide_token_index=index,guide_audio_confirmed=True,
                        probability=hint.get('probability',0.))
        left,right=selected[0]['start']-.08,selected[-1]['end']+.08
        kept=[]
        for segment in output:
            words=[word for word in segment['words'] if word.get('guide_audio_confirmed')
                   or not left <= (word['start']+word['end'])/2 <= right]
            if words:kept.append({**segment,'words':words,'start':words[0]['start'],'end':words[-1]['end'],
                                 'text':''.join(word['word'] for word in words).strip()})
        kept.append(dict(start=selected[0]['start'],end=selected[-1]['end'],words=selected,
            text=''.join(word['word'] for word in selected).strip(),guide_audio_confirmed=True))
        output=sorted(kept,key=lambda segment:segment['start']);recovered.append(candidate)
    return output,dict(guide_ctc_recovered_lines=len(recovered),
        guide_ctc_recovered_line_indexes=[item['line'] for item in recovered],
        guide_ctc_recovered_words=sum(len(lines[item['line']]) for item in recovered),
        guide_ctc_recovered_unanchored_words=sum(item.get('unanchored_words',0) for item in recovered))


def refine_confirmed_clocks(segments, aligned):
    """Keep all confirmed text; use CTC clocks only inside its measured verse."""
    output = copy.deepcopy(segments)
    changed = set()
    words = [word for segment in output for word in segment['words']]
    limits = [(segment['start']-.5, segment['end']+.7)
              for segment in output for _ in segment['words']]
    # A later onset may need its following word to move first. Recheck in
    # reverse after the forward pass; every replacement still respects both
    # current neighbors, so the repair cannot reorder words or overlap them.
    for positions in (range(len(words)),reversed(range(len(words)))):
        for position in positions:
            word=words[position]
            lower, upper = limits[position]
            if position+1 < len(words):
                upper=max(upper,words[position+1]['start']+.02)
            index = word.get('guide_token_index', -1)
            if not aligned or not 0 <= index < len(aligned):
                continue
            candidate = aligned[index]
            if (not candidate or normalize_word(candidate['word']) != normalize_word(word['word'])
                    or candidate.get('alignment_score', 0.) < .002
                    or not lower <= candidate['start'] < candidate['end'] <= upper
                    or candidate['end']-candidate['start'] > max(4., len(normalize_word(word['word']))*.8)
                    or not word['start']-.6 <= candidate['start'] <= word['end']+.6
                    or candidate['start'] < word.get('guide_source_start_bound',-math.inf)
                    or (position and candidate['start'] < words[position-1]['end']-.02)
                    or (position+1 < len(words) and candidate['end'] > words[position+1]['start']+.02)):
                continue
            word.update({key: copy.deepcopy(candidate[key]) for key in
                         ('start', 'end', 'alignment_score', 'alignment_chars') if key in candidate})
            changed.add(position)
    for segment in output:
        segment['start'] = segment['words'][0]['start']; segment['end'] = segment['words'][-1]['end']
    return output, len(changed)


def mark_confirmed_lines(segments):
    """Keep the complete guide's exact verse boundaries through CTC regrouping."""
    result = copy.deepcopy(segments)
    for index, segment in enumerate(result):
        words = segment.get('words', [])
        if not segment.get('guide_audio_confirmed') and not all(word.get('guide_audio_confirmed') for word in words):
            continue
        for word in words:
            if segment.get('guide_audio_confirmed'):
                word['guide_audio_confirmed'] = True
            word.pop('lyric_line_start', None); word.pop('lyric_line_break', None)
            word['lyric_line_id'] = f'known-guide:{index}'
        if words:
            words[0]['lyric_line_start'] = True; words[-1]['lyric_line_break'] = True
    return result


def singing_activity(emission, evidence, segments):
    """Support instrumental decisions with quiet sung phones, including held notes.

    MMS can favor blank while retaining a small nonblank posterior throughout a
    sung vowel. Speech VAD often misses those frames. This supporting map never
    supplies text or word clocks, and is bounded around confirmed sung verses.
    Instrumental leakage with an all-blank posterior is not vocal evidence.
    """
    values, edges = emission
    centers = (edges[:-1]+edges[1:])/2
    mass = -np.expm1(np.asarray(values[:, 0], dtype=np.float64))
    indices = np.minimum((centers*evidence.rate/evidence.hop).astype(int), len(evidence.rms)-1)
    supported = np.zeros(len(centers), dtype=bool)
    for segment in segments:
        supported |= (centers >= segment['start']-.2) & (centers <= segment['end']+5.)
    active = (supported & (mass >= .01)
              & (evidence.rms[indices] > max(1e-8, evidence.reference*.03)))
    selected = np.flatnonzero(active)
    regions = []
    for index in selected:
        left, right = float(edges[index]), float(edges[index+1])
        if regions and left-regions[-1][1] <= .16:
            regions[-1][1] = right
        else:
            regions.append([left, right])
    return [(max(0., left-.08), min(evidence.duration, right+.08))
            for left, right in regions if right-left >= .08]


def alignment_lines(guide, roman):
    lines = [[word for word in line.split() if normalize_word(word)]
             for line in prepare_lyrics_guide(guide).splitlines()]
    lines = [line for line in lines if line]
    if not lines or any(not roman(word) for line in lines for word in line):
        return []
    return lines

