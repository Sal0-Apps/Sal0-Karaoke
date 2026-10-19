"""Check lyric spelling against Whisper words, using only acoustic word clocks."""
import difflib
import copy
import hashlib
import json
import logging
import math
import os
import re
import unicodedata

from lyrics_sync import require_acoustic_word_timing

logger = logging.getLogger('karaoke')
GUIDE_POLICY_VERSION = 3


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


def apply_guide_boundaries(lyrics, segments):
    """Recover confirmed guide verses after CTC, without replacing text or clocks.

    Whole-line matches have anchored edges. Small internal recognition mistakes
    are tolerated, but a word from the following verse cannot extend a match.
    Interval selection prevents overlapping guide lines from sharing a word.
    Repeated sung occurrences can reuse a guide line printed only once.
    """
    result = copy.deepcopy(segments)
    words = [word for segment in result for word in segment.get('words', [])]
    for word in words:
        for key in ('lyric_line_start', 'lyric_line_break', 'lyric_line_id'):
            word.pop(key, None)
    observed = [normalize_word(word.get('word', '')) for word in words]
    positions = {}
    for index, token in enumerate(observed):
        if token:
            positions.setdefault(token, []).append(index)
    candidates = {}
    for line_index, line in enumerate(prepare_lyrics_guide(lyrics).splitlines()):
        expected = [normalize_word(token) for token in line.split() if normalize_word(token)]
        size = len(expected)
        if not 2 <= size <= 64:
            continue
        for start in positions.get(expected[0], []):
            for length in (size, size - 1, size + 1) if size >= 5 else (size,):
                end = start + length
                if end > len(words) or observed[end - 1] != expected[-1]:
                    continue
                if words[end - 1]['end'] - words[start]['start'] > 35:
                    continue
                actual = observed[start:end]
                matches = sum(block.size for block in difflib.SequenceMatcher(
                    None, expected, actual, autojunk=False).get_matching_blocks())
                if (size < 5 and actual != expected) or matches / max(size, length) < .8:
                    continue
                weight = matches - (max(size, length) - matches) * .6 + .05
                candidates.setdefault(start, []).append((end, weight, line_index))
    # Maximize confirmed coverage instead of greedily accepting overlapping lines.
    best = [0.] * (len(words) + 1)
    selected = {}
    for start in range(len(words) - 1, -1, -1):
        best[start] = best[start + 1]
        for end, weight, line_index in candidates.get(start, []):
            if weight + best[end] > best[start] + 1e-6:
                best[start] = weight + best[end]
                selected[start] = (end, line_index)
    count = 0
    index = 0
    while index < len(words):
        if index not in selected:
            index += 1
            continue
        end, line_index = selected[index]
        identifier = f'{line_index}:{index}'
        for word in words[index:end]:
            word['lyric_line_id'] = identifier
        words[index]['lyric_line_start'] = True
        words[end - 1]['lyric_line_break'] = True
        count += 1
        index = end
    return result, count


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


def _safe_spelling_pair(guide, recognized):
    """Do not replace a timed word fragment with an entire contraction."""
    source, target = normalize_word(guide), normalize_word(recognized)
    if source == target:
        return True
    if any(mark in guide for mark in ("'", '’', '-')) and (source in target or target in source):
        return False
    if any(mark in recognized for mark in ("'", '’')) and target in {'s', 't', 'nt', 've', 'd', 'll', 're', 'm'}:
        return False
    return True


def _contextual_guide_matches(official, words, allow_distant=False):
    """Suggest one-for-one corrections; uncertainty never removes ASR words.

    Exact neighboring words locate a candidate in the guide. Two anchors allow
    a spelling variation; a short phrase with one adjacent anchor needs a much
    closer, unique spelling. Candidate positions stay ordered with their local
    anchors, so a missing word cannot shift corrections onto its neighbor.
    """
    expected = [normalize_word(token) for token in official]
    observed = [normalize_word(word.get('word', '')) for word in words]
    positions, contexts = {}, set()
    for index, token in enumerate(expected):
        # Identical printed choruses offer the same local evidence. Index one
        # occurrence per context instead of comparing every repetition again.
        context = tuple(expected[max(0, index - 6):index + 7])
        context = (min(index, 6), min(len(expected) - index - 1, 6), context)
        if context in contexts:
            continue
        contexts.add(context)
        positions.setdefault(token, []).append(index)
    matches, ambiguous, proposals = {}, set(), []

    def near(left, right):
        try:
            gap = float(right['start']) - float(left['end'])
        except (KeyError, TypeError, ValueError):
            return True  # This is a text proposal; the acoustic caller validates clocks.
        return math.isfinite(gap) and gap <= 4.

    for index, actual in enumerate(observed):
        if not actual or len(str(words[index].get('word', '')).split()) != 1:
            continue
        candidates = {}
        for neighbor in range(max(0, index - 3), min(len(words), index + 4)):
            if neighbor == index or not near(words[min(index, neighbor)], words[max(index, neighbor)]):
                continue
            for anchor in positions.get(observed[neighbor], ()):
                candidate = anchor + index - neighbor
                if 0 <= candidate < len(official):
                    candidates.setdefault(candidate, set()).add(neighbor)
        choices = {}
        for source, anchors in candidates.items():
            wanted = expected[source]
            similarity = difflib.SequenceMatcher(None, actual, wanted).ratio()
            adjacent = any(abs(anchor - index) == 1 for anchor in anchors)
            exact = actual == wanted
            trusted = (exact or (len(anchors) >= 2 and similarity >= .6)
                       or (adjacent and similarity >= .82 and min(len(actual), len(wanted)) >= 3)
                       or (allow_distant and adjacent and len(anchors) >= 2))
            if not trusted or not _safe_spelling_pair(official[source], words[index].get('word', '')):
                continue
            # Do not turn an extra recognition into a second copy of the next
            # correctly recognized word unless the guide also repeats it there.
            collision = any(0 <= index + step < len(words)
                            and observed[index + step] == wanted
                            and (not 0 <= source + step < len(expected) or expected[source + step] != wanted)
                            for step in (-1, 1))
            if not exact and collision:
                continue
            score = len(anchors) + similarity
            previous = choices.get(wanted)
            if previous is None or score > previous['score']:
                choices[wanted] = dict(source=source, score=score, similarity=similarity,
                                       anchors=len(anchors))
        ranked = sorted(choices.values(), key=lambda item: item['score'], reverse=True)
        if not ranked:
            continue
        if actual in choices:
            # A deletion in the guide/recognition can give the shifted window
            # more votes. Never sacrifice an already anchored exact word to it.
            matches[index] = choices[actual]['source']
            continue
        best = ranked[0]
        ambiguous_distant = (allow_distant and best['similarity'] < .6 and len(ranked) > 1
                             and best['anchors'] == ranked[1]['anchors'])
        if len(ranked) > 1 and (best['score'] - ranked[1]['score'] < .2 or ambiguous_distant):
            ambiguous.add(index)
            proposals.append(dict(index=index, recognized=words[index].get('word', '').strip(),
                                  guide=None, status='ambiguous', candidates=[official[item['source']] for item in ranked[:3]]))
            continue
        matches[index] = best['source']
        if observed[index] != expected[best['source']]:
            proposals.append(dict(index=index, recognized=str(words[index].get('word', '')).strip(),
                                  guide=official[best['source']], guide_index=best['source'],
                                  similarity=round(best['similarity'], 4), anchors=best['anchors'],
                                  status='proposed'))
    return matches, ambiguous, proposals


def guide_correction_candidate(lyrics, words, *, allow_distant=False):
    """Return a same-size lexical hypothesis for CTC, or None when unnecessary.

    Original tokens fill every uncertain position. No guide-only word, phrase,
    timestamp or repetition is inserted into this acoustic hypothesis. Distant
    alternatives are only for a caller that compares both complete sequences
    against the audio; they still require unique, neighboring exact context.
    """
    official = [token for token in prepare_lyrics_guide(lyrics).split() if normalize_word(token)]
    if not official or not words or len(official) > 12000:
        return None
    matches, _, _ = _contextual_guide_matches(official, words, allow_distant=allow_distant)
    original = [str(word.get('word', '')).strip() for word in words]
    candidate = [official[matches[index]] if index in matches else token
                 for index, token in enumerate(original)]
    return candidate if any(normalize_word(a) != normalize_word(b) for a, b in zip(candidate, original)) else None


def verify_lyrics_guide(lyrics, segments):
    """Check every recognized word; correct trusted spelling without moving time.

    Missing guide words remain differences until Whisper detects them in audio.
    Repeated sung phrases can reuse the same guide phrase. An unrelated guide
    cannot supply replacement verses or their clocks.
    """
    guide = prepare_lyrics_guide(lyrics)
    official = []
    for line in guide.splitlines():
        tokens = [token for token in line.split() if normalize_word(token)]
        if tokens:
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
    pairs = {transcript: source for source, transcript in exact}
    contextual, ambiguous, proposals = _contextual_guide_matches(official, words)
    for target, source in contextual.items():
        pairs.setdefault(target, source)

    checks, corrected, similarities = [], 0, []
    for index, word in enumerate(words):
        original = str(word.get('word', ''))
        source = pairs.get(index)
        suggested = official[source] if source is not None else None
        similarity = difflib.SequenceMatcher(None, recognized[index], expected[source]).ratio() if source is not None else 0
        status = 'ambiguous' if index in ambiguous else 'unmatched'
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
        retry_vocabulary=' '.join(dict.fromkeys(retry_words)), checks=checks,
        ambiguous_words=len(ambiguous), correction_proposals=proposals)
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
