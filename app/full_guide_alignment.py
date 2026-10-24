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

WHISPER_GUIDE_VERSION = 4


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
    output, offset = [], 0
    for index, line in enumerate(lines):
        cancel()
        anchored = sum(token in anchors for token in range(offset, offset+len(line))) >= len(line)*.5
        for attempt, (context_words, padding) in enumerate(((3, .35), (5, .7), (1, .7)), 1):
            first, last = max(0, offset-context_words), min(len(expected), offset+len(line)+context_words)
            left, right = max(0., float(starts[first])-padding), min(duration, float(ends[last-1])+padding)
            if right-left > 29:
                first, last = offset, offset+len(line)
                left, right = max(0., float(starts[first])-.5), min(duration, float(ends[last-1])+.5)
            aligned = backend.align(audio, left, right, expected[first:last])
            selected = aligned[offset-first:offset-first+len(line)] if aligned else []
            valid = (len(selected) == len(line) and
                all(math.isfinite(word['start']+word['end']+word.get('probability', 0.))
                    and 0 <= word['start'] < word['end'] <= duration+.02 for word in selected)
                and float(np.mean([word.get('probability', 0.) for word in selected])) >= (.20 if anchored else .40))
            if valid:
                break
        report.setdefault('guide_line_checks', []).append(dict(line=index, confirmed=bool(valid),
            attempts=attempt, words=len(selected), mean_probability=round(float(np.mean([word.get('probability', 0.) for word in selected])), 4)
            if selected else 0., invalid_clocks=sum(word['end'] <= word['start'] for word in selected)))
        if not valid:
            report['guide_rejected_lines'] += 1
        else:
            selected = copy.deepcopy(selected)
            for token_index, word in enumerate(selected, offset):
                word['guide_token_index'] = token_index
                word['guide_audio_confirmed'] = True
            output.append(dict(start=selected[0]['start'], end=selected[-1]['end'],
                text=''.join(word['word'] for word in selected).strip(), words=selected,
                guide_audio_confirmed=True))
        offset += len(line)
        progress(round((index+1)/len(lines)*100), f'Conferindo verso {index+1} de {len(lines)} com a voz…')
    # A partial known-text pass must not replace a complete ASR recording.
    if report['guide_rejected_lines']:
        report['status'] = 'partial'
        return segments, report
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
                return segments, report
        else:
            extra = []
    report.update(status='aligned', guide_aligned_words=len(expected),
                  recovered_words=missing)
    temporary = target.with_suffix('.json.tmp')
    try:
        temporary.write_text(json.dumps(dict(signature=signature, segments=output, report=report), ensure_ascii=False))
        cancel(); os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return output, report


def refine_confirmed_clocks(segments, aligned):
    """Keep all confirmed text; use CTC clocks only inside its measured verse."""
    output = copy.deepcopy(segments)
    changed = 0
    for segment in output:
        lower, upper = segment['start']-.5, segment['end']+.7
        for word in segment['words']:
            index = word.get('guide_token_index', -1)
            if not aligned or not 0 <= index < len(aligned):
                continue
            candidate = aligned[index]
            if (normalize_word(candidate['word']) != normalize_word(word['word'])
                    or candidate.get('alignment_score', 0.) < .002
                    or not lower <= candidate['start'] < candidate['end'] <= upper
                    or candidate['end']-candidate['start'] > max(4., len(normalize_word(word['word']))*.8)
                    or not word['start']-.6 <= candidate['start'] <= word['end']+.6):
                continue
            word.update({key: copy.deepcopy(candidate[key]) for key in
                         ('start', 'end', 'alignment_score', 'alignment_chars') if key in candidate})
            changed += 1
        segment['start'] = segment['words'][0]['start']; segment['end'] = segment['words'][-1]['end']
    return output, changed


def alignment_lines(guide, roman):
    lines = [[word for word in line.split() if normalize_word(word)]
             for line in prepare_lyrics_guide(guide).splitlines()]
    lines = [line for line in lines if line]
    if not lines or any(not roman(word) for line in lines for word in line):
        return []
    return lines

