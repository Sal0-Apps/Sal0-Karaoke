"""Real CPU regression on CC BY singing with independent word-onset annotations.

Cortez, Feel (Stripped), via JamendoLyrics (f90/jamendolyrics). Only validation
fetches this recording; no recording or copyrighted lyric is shipped in the app.
The controlled input shifts reference clocks and corrupts one word, then adds
three words in appended digital silence. This measures alignment, not ASR WER.
"""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import time

import numpy as np
import requests

from lyric_alignment import refine_lyrics, MMSAligner, supports_deletion
from full_guide_alignment import align_guide_with_whisper
from whisper_audio import load_whisper_audio

DATASET='https://raw.githubusercontent.com/f90/jamendolyrics/f093b7a74e034deac21eb5ea3fc40769b29c35b0/'
STEM='Cortez_-_Feel__Stripped_'


def get(path):
    response=requests.get(DATASET+path,timeout=(15,90));response.raise_for_status()
    return response


def validate_guide_recovery(source, text, rows, whole, root):
    """Real singing with a whole omitted line and a later sung repetition."""
    first, last = 2, 40
    left = float(rows[first]['word_start'])-.7
    right = float(rows[last-1]['word_end'])+.7
    clip = whole[int(left*16000):int(right*16000)]
    phrase_left, phrase_right = float(rows[2]['word_start'])-.3, float(rows[6]['word_end'])+.3
    phrase = whole[int(phrase_left*16000):int(phrase_right*16000)]
    repeat_start = len(clip)/16000+7.
    audio = np.concatenate((clip, np.zeros(7*16000, np.float32), phrase, np.zeros(3*16000, np.float32)))
    lines, line, truth, baseline = [], [], [], []
    for index in range(first, last):
        start, end = float(rows[index]['word_start'])-left, float(rows[index]['word_end'])-left
        truth.append(start); line.append(text[index])
        if rows[index]['line_end'] != 'nan':
            lines.append(' '.join(line)); line = []
        if index not in set(range(7, 14)) | {17, 25}:
            baseline.append(dict(word=' '+text[index], start=start, end=end, probability=.9))
    lines.append(' '.join(text[2:7]))
    for index in range(2, 7):
        start, end = repeat_start+float(rows[index]['word_start'])-phrase_left, repeat_start+float(rows[index]['word_end'])-phrase_left
        truth.append(start)
        if index in (2, 6):
            baseline.append(dict(word=' '+text[index], start=start, end=end, probability=.9))
    folder = root/'complete-guide'; folder.mkdir()
    guide = '\n'.join(lines)
    segments = [dict(start=baseline[0]['start'], end=baseline[-1]['end'], words=baseline)]
    guided, guide_report = align_guide_with_whisper(source, segments, guide, folder,
        os.getenv('KARAOKE_SMOKE_WHISPER_MODEL', 'medium'), decode=lambda _: audio,
        progress=lambda percent, detail: print(f'guide {percent}% {detail}', flush=True))
    assert guide_report['status'] == 'aligned', guide_report
    result, report = refine_lyrics(source, guided, guide, folder, decode=lambda _: audio)
    output = [word for segment in result for word in segment['words']]
    assert len(output) == len(truth), (len(output), len(truth), report)
    assert [word['word'].strip() for word in output] == ' '.join(lines).split()
    errors = [abs(word['start']-target) for word, target in zip(output, truth)]
    assert float(np.median(errors)) < .35, errors
    assert output[-5]['start'] >= repeat_start-.3, 'A sung repeat cannot begin in the preceding silence'
    assert not any(len(clip)/16000+.3 < word['start'] < repeat_start-.3 for word in output)
    assert guide_report['recovered_words'] >= 7, guide_report
    return dict(complete_guide_words=len(output), whole_omitted_line_recovered=True,
        repeated_phrase_recovered=True, long_silence_preserved=True,
        complete_guide_median_seconds=round(float(np.median(errors)), 4))


def main():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);source=root/'singing.mp3'
        source.write_bytes(get('mp3/'+STEM+'.mp3').content)
        text=get('lyrics/'+STEM+'.words.txt').text.split()
        rows=list(csv.DictReader(io.StringIO(get('annotations/words/'+STEM+'.csv').text)))
        assert len(rows)==len(text)
        selected=list(range(2,19));start=float(rows[selected[0]]['word_start'])-.7
        end=float(rows[selected[-1]]['word_end'])+.7
        whole=load_whisper_audio(source);clip=whole[int(start*16000):int(end*16000)]
        audio=np.pad(clip,(0,4*16000));duration=len(clip)/16000
        original=[];truth=[]
        for index in selected:
            left=float(rows[index]['word_start'])-start;right=float(rows[index]['word_end'])-start
            original.append(dict(word=' '+text[index],start=left+.4,end=right+.4));truth.append(left)
        original[6]['word']=' banana'
        original.extend(dict(word=' fantasma',start=duration+1+i*.4,end=duration+1.3+i*.4) for i in range(3))
        segments=[dict(start=original[0]['start'],end=original[-1]['end'],text=''.join(w['word'] for w in original),words=original)]
        started=time.monotonic()
        result,report=refine_lyrics(source,segments,' '.join(text),root,decode=lambda _:audio,
            progress=lambda percent,detail:print(f'{percent}% {detail}',flush=True))
        output=[word for segment in result for word in segment['words']]
        assert report['status']=='aligned',report
        assert len(output)==len(selected),(len(output),report)
        assert all(word['word'].strip() not in {'banana','fantasma'} for word in output)
        assert all(word['start']<duration for word in output)
        errors=[abs(word['start']-target) for word,target in zip(output,truth)]
        assert float(np.median(errors))<.30,errors
        assert report['guide_changes']>=1 and report['silent_or_invalid_words']>=3,report
        assert all(word.get('alignment_chars') for word in output)
        # Reuse must not reload a 1.2 GB model for a render-only revision.
        def unavailable(*args):raise AssertionError('Cached alignment must not reload its model')
        cached=refine_lyrics(source,segments,' '.join(text),root,decode=lambda _:audio,backend_factory=unavailable)
        assert cached[0]==result
        # One recorded phrase versus an actual repeat of the same sung audio.
        # A guide printed once must never delete the second sung occurrence.
        phrase_indices=list(range(2,8))
        left=float(rows[phrase_indices[0]]['word_start'])-.3
        right=float(rows[phrase_indices[-1]]['word_end'])+.3
        phrase_audio=whole[int(left*16000):int(right*16000)]
        phrase=text[2:8]
        aligner=MMSAligner(lambda *args:None,lambda:None)
        try:
            single=aligner.emission(phrase_audio)
            repeated=aligner.emission(np.concatenate((phrase_audio,np.zeros(3200,np.float32),phrase_audio)))
            single_prefers_deletion=supports_deletion(aligner,single,phrase*2,phrase)
            repeat_prefers_deletion=supports_deletion(aligner,repeated,phrase*2,phrase)
            assert single_prefers_deletion, 'Duplicated text must lose against one sung occurrence'
            assert not repeat_prefers_deletion, 'An actually sung repeat must remain'
        finally:
            aligner.close()
        complete_guide = validate_guide_recovery(source, text, rows, whole, root)
        print(json.dumps(dict(engine='MMS CTC CPU',recording='Cortez - Feel (Stripped), CC BY',
            words=len(output),controlled_before_median_seconds=.4,after_median_seconds=round(float(np.median(errors)),4),
            corrected_guide_changes=report['guide_changes'],silent_words_removed=report['silent_or_invalid_words'],
            unsupported_repeat_rejected=single_prefers_deletion,real_sung_repeat_preserved=not repeat_prefers_deletion,
            elapsed_seconds=round(time.monotonic()-started,2), **complete_guide)),flush=True)


if __name__=='__main__':main()
