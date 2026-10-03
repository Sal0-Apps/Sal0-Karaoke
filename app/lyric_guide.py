"""Check lyric spelling against Whisper words, using only acoustic word clocks."""
import difflib
import hashlib
import json
import logging
import math
import os
import re
import unicodedata

from lyrics_sync import require_acoustic_word_timing

logger = logging.getLogger('karaoke')
GUIDE_POLICY_VERSION = 1


def normalize_word(value):
    value = unicodedata.normalize('NFKD', str(value))
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'[^\w]', '', value).casefold()


def prepare_lyrics_guide(value):
    """Discard LRC clocks and annotations; they never order or time the audio."""
    lines = []
    for line in str(value or '').splitlines():
        line = re.sub(r'\[\d+:\d+(?:[.:]\d+)?\]|<\d+:\d+(?:[.:]\d+)?>', '', line).strip()
        if not line or re.fullmatch(r'\[[^\]]+\]', line):
            continue
        lines.append(line)
    return '\n'.join(lines)


def _gap_pairs(expected, recognized):
    """Align small spelling gaps, retaining insertions/deletions as differences."""
    if not expected or not recognized or max(len(expected), len(recognized)) > 64:
        return []
    rows = [[0.0] * (len(recognized) + 1) for _ in range(len(expected) + 1)]
    moves = [[0] * (len(recognized) + 1) for _ in range(len(expected) + 1)]
    for i in range(1, len(expected) + 1):
        rows[i][0], moves[i][0] = i, 1
    for j in range(1, len(recognized) + 1):
        rows[0][j], moves[0][j] = j, 2
    for i, source in enumerate(expected, 1):
        for j, target in enumerate(recognized, 1):
            similarity = difflib.SequenceMatcher(None, source, target).ratio()
            penalty = 0 if source == target else (1.25 - similarity if similarity >= .45 else 2.1)
            values = (rows[i-1][j-1] + penalty, rows[i-1][j] + 1, rows[i][j-1] + 1)
            move = min(range(3), key=values.__getitem__)
            rows[i][j], moves[i][j] = values[move], move
    result, i, j = [], len(expected), len(recognized)
    while i or j:
        move = moves[i][j]
        if move == 0:
            result.append((i-1, j-1))
            i, j = i-1, j-1
        elif move == 1:
            i -= 1
        else:
            j -= 1
    return result[::-1]


def verify_lyrics_guide(lyrics, segments):
    """Check every recognized word; correct trusted spelling without moving time.

    Missing guide words remain differences until Whisper detects them in audio.
    Repeated sung phrases can reuse the same guide phrase. An unrelated guide
    cannot supply replacement verses or their clocks.
    """
    guide = prepare_lyrics_guide(lyrics)
    official, guide_lines = [], []
    for line in guide.splitlines():
        tokens = [token for token in line.split() if normalize_word(token)]
        if tokens:
            guide_lines.append((len(official), tokens))
            official.extend(tokens)
    result, words = [], []
    for segment in segments or []:
        copied = dict(segment)
        for key in ('synced_line', 'acoustic_animation', 'animation_words'):
            copied.pop(key, None)
        copied['words'] = [dict(word) for word in segment.get('words', [])]
        for word in copied['words']:
            word.pop('lyric_line_break', None)
            if normalize_word(word.get('word', '')):
                words.append(word)
        result.append(copied)
    expected = [normalize_word(word) for word in official]
    recognized = [normalize_word(word.get('word', '')) for word in words]
    matcher = difflib.SequenceMatcher(None, expected, recognized, autojunk=False)
    blocks = matcher.get_matching_blocks()
    exact = [(block.a+i, block.b+i) for block in blocks for i in range(block.size)]
    coverage = len(exact) / max(1, len(recognized))
    pairs = {transcript: source for source, transcript in exact}
    if coverage >= .35:
        for tag, a, b, c, d in matcher.get_opcodes():
            if tag != 'replace':
                continue
            for oa, ta in _gap_pairs(expected[a:b], recognized[c:d]):
                source, target = a+oa, c+ta
                similarity = difflib.SequenceMatcher(None, expected[source], recognized[target]).ratio()
                context = sum(index in pairs for index in range(max(0, target-2), min(len(words), target+3)) if index != target)
                if similarity >= .5 and context >= 2:
                    pairs[target] = source

    # A guide often prints its chorus once. Check later occurrences too,
    # without copying missing verses or interpreting provider timestamps.
    normalized_lines = [(start, [normalize_word(token) for token in tokens])
                        for start, tokens in guide_lines if len(tokens) >= 3]
    for target in range(len(words)):
        choices = []
        for start, tokens in normalized_lines:
            window = recognized[target:target+len(tokens)]
            if len(window) != len(tokens) or all(target+i in pairs for i in range(len(tokens))):
                continue
            equal = sum(a == b for a, b in zip(tokens, window))
            if equal / len(tokens) >= .6:
                score = sum(difflib.SequenceMatcher(None, a, b).ratio() for a, b in zip(tokens, window)) / len(tokens)
                if score >= .75:
                    choices.append((score, start, tokens))
        if choices:
            _, start, tokens = max(choices, key=lambda item: item[0])
            for offset, token in enumerate(tokens):
                index = target+offset
                similarity = difflib.SequenceMatcher(None, token, recognized[index]).ratio()
                if similarity >= .5:
                    pairs.setdefault(index, start+offset)

    checks, corrected, similarities = [], 0, []
    for index, word in enumerate(words):
        original = str(word.get('word', ''))
        source = pairs.get(index)
        suggested = official[source] if source is not None else None
        similarity = difflib.SequenceMatcher(None, recognized[index], expected[source]).ratio() if source is not None else 0
        status = 'unmatched'
        if suggested is not None:
            leading = original[:len(original)-len(original.lstrip())]
            trailing = original[len(original.rstrip()):]
            replacement = leading + suggested + trailing
            status = 'matched' if replacement == original else 'corrected'
            corrected += status == 'corrected'
            word['word'] = replacement
        similarities.append(similarity)
        checks.append(dict(index=index, recognized=original.strip(), guide=suggested,
                           similarity=round(similarity, 4), status=status,
                           start=word.get('start'), end=word.get('end')))
    for segment in result:
        if segment.get('words'):
            segment['text'] = ''.join(str(word.get('word', '')) for word in segment['words']).strip()
    present = set(pairs.values())
    missing = [index for index in range(len(official)) if index not in present]
    unmatched = len(words)-len(pairs)
    retry_words = [official[index] for index in missing]
    report = dict(policy='whisper_guide', version=GUIDE_POLICY_VERSION,
        status='no_guide' if not official else ('unrelated' if len(pairs)/max(1, len(words)) < .35 else ('differences' if missing or unmatched else 'verified')),
        guide_words=len(official), whisper_words=len(words), checked_words=len(checks),
        verified_words=len(pairs), corrected_words=corrected, unmatched_words=unmatched,
        missing_guide_words=len(missing), matching_ratio=round(len(pairs)/max(1, len(words)), 4),
        comparison_score=sum(similarities)/max(1, len(words)+len(missing)),
        retry_vocabulary=' '.join(dict.fromkeys(retry_words)), checks=checks)
    return result, report


def _mean_probability(segments):
    values = [float(word['probability']) for segment in segments for word in segment.get('words', [])
              if isinstance(word.get('probability'), (int, float))
              and math.isfinite(word['probability']) and 0 <= word['probability'] <= 1]
    return sum(values)/len(values) if values else None


def review_lyrics_with_whisper(lyrics, segments, cache_dir, context=None, retry=None, cancel=None):
    """Compare, optionally decode again, and cache a checked acoustic result."""
    require_acoustic_word_timing(segments)
    if any(s.get('synced_line') or s.get('animation_words') or s.get('acoustic_animation') for s in segments):
        raise ValueError('A conferência exige palavras e tempos acústicos do Whisper.')
    guide = prepare_lyrics_guide(lyrics)
    signature = hashlib.sha256(json.dumps(dict(version=GUIDE_POLICY_VERSION, guide=guide,
        segments=segments, context=context or {}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    cache_file = os.path.join(cache_dir, 'lyrics_guide_cache.json')
    try:
        with open(cache_file, encoding='utf-8') as file:
            saved = json.load(file)
        if saved.get('signature') == signature and not saved['report'].get('retry_error'):
            require_acoustic_word_timing(saved['segments'])
            if not any(segment.get('synced_line') or segment.get('animation_words') or segment.get('acoustic_animation') for segment in saved['segments']):
                return saved['segments'], saved['report']
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    if cancel:
        cancel()
    result, report = verify_lyrics_guide(guide, segments)
    report['retry_attempted'], report['retry_selected'] = False, False
    if retry and report['status'] == 'differences':
        report['retry_attempted'] = True
        try:
            if cancel:
                cancel()
            candidate = retry(report)
            require_acoustic_word_timing(candidate)
            if any(segment.get('synced_line') or segment.get('animation_words') or segment.get('acoustic_animation') for segment in candidate):
                raise ValueError('A reanálise deve fornecer somente palavras e tempos do Whisper.')
            checked, candidate_report = verify_lyrics_guide(guide, candidate)
            first_probability, retry_probability = _mean_probability(segments), _mean_probability(candidate)
            confident = (first_probability is None or retry_probability is None
                         or retry_probability >= first_probability - .15)
            if (candidate_report['comparison_score'] > report['comparison_score'] + .01
                    and candidate_report['whisper_words'] >= .6 * report['whisper_words'] and confident):
                result, report = checked, {**candidate_report, 'retry_attempted': True, 'retry_selected': True}
        except InterruptedError:
            raise
        except Exception as exc:
            logger.warning('Reanálise da letra-guia não concluiu; mantendo os tempos válidos do Whisper: %s', exc)
            report['retry_error'] = True
    if cancel:
        cancel()
    temporary = cache_file + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as file:
        json.dump(dict(signature=signature, segments=result, report=report), file, ensure_ascii=False)
    os.replace(temporary, cache_file)
    return result, report
