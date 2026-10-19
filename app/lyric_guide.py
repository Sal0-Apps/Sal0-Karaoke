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
from functools import lru_cache

from lyrics_sync import require_acoustic_word_timing

logger = logging.getLogger('karaoke')
GUIDE_POLICY_VERSION = 2


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
                if (similarity >= .5 and context >= 2
                        and _safe_spelling_pair(official[source], words[target].get('word', ''))):
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
                if similarity >= .5 and _safe_spelling_pair(official[start+offset], words[index].get('word', '')):
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


def _strict_source_words(segments, official):
    """Keep acoustic clocks; join only contiguous fragments of a guide token."""
    words, invalid, seen = [], [], set()
    for segment_index, segment in enumerate(segments or []):
        for word in segment.get('words', []):
            source_index = len(words) + len(invalid)
            text = str(word.get('word', '')).strip()
            try:
                start, end = float(word['start']), float(word['end'])
            except (KeyError, TypeError, ValueError):
                start, end = math.nan, math.nan
            identity = (normalize_word(text), start, end, word.get('_strict_span_id'), word.get('_strict_span_part'))
            if (not normalize_word(text) or len(text.split()) != 1
                    or not math.isfinite(start + end) or start < 0 or end <= start
                    or identity in seen):
                invalid.append(dict(source_indices=[source_index], recognized=text,
                                    guide=None, status='invalid', start=word.get('start'), end=word.get('end')))
                continue
            seen.add(identity)
            acoustic_word = copy.deepcopy(word)
            acoustic_word.update(start=start, end=end)
            words.append(dict(word=acoustic_word, segment=segment_index,
                              sources=[source_index], normalized=normalize_word(text)))
    contractions = {normalize_word(token) for token in official
                    if any(mark in token for mark in ("'", '’', '-'))}
    joined, index = [], 0
    while index < len(words):
        unit = words[index]
        for count in (3, 2):
            pieces = words[index:index + count]
            if len(pieces) != count or not contractions:
                continue
            normalized = ''.join(piece['normalized'] for piece in pieces)
            contiguous = all(
                -.03 <= float(right['word']['start']) - float(left['word']['end']) <= .12
                and right['sources'][0] == left['sources'][-1] + 1
                for left, right in zip(pieces, pieces[1:]))
            if normalized not in contractions or not contiguous or any('_strict_span_id' in piece['word'] for piece in pieces):
                continue
            merged = copy.deepcopy(unit)
            merged['sources'] = [source for piece in pieces for source in piece['sources']]
            merged['normalized'] = normalized
            merged['word']['word'] = ''.join(str(piece['word']['word']).strip() for piece in pieces)
            merged['word']['start'] = min(float(piece['word']['start']) for piece in pieces)
            merged['word']['end'] = max(float(piece['word']['end']) for piece in pieces)
            for field in ('probability', 'alignment_score'):
                values = [piece['word'].get(field) for piece in pieces]
                if all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
                    merged['word'][field] = min(values)
            merged['word'].pop('alignment_chars', None)
            unit = merged
            index += count - 1
            break
        joined.append(unit)
        index += 1
    return joined, invalid


def _strict_phrase_candidates(official, units, similarity_score=None):
    """Locally align ordered phrases, allowing omissions but never creating clocks.

    Two exact context anchors are required. A fuzzy word additionally needs two
    nearby anchors. The bounded ASR window keeps this pass small on a CPU server.
    """
    expected = [normalize_word(token) for token in official]
    observed = [unit['normalized'] for unit in units]
    similarity_score = similarity_score or (lambda actual, wanted: difflib.SequenceMatcher(None, actual, wanted).ratio())
    positions = {}
    for index, token in enumerate(expected):
        positions.setdefault(token, []).append(index)
    fuzzy_context = []
    for index in range(len(observed)):
        counts = {}
        for neighbor in range(max(0, index - 3), min(len(observed), index + 4)):
            if neighbor == index:
                continue
            possible = set()
            for anchor in positions.get(observed[neighbor], ()):
                possible.update(range(max(0, anchor - 5), anchor) if neighbor > index
                                else range(anchor + 1, min(len(expected), anchor + 6)))
            for target in possible:
                counts[target] = counts.get(target, 0) + 1
        fuzzy_context.append({target for target, count in counts.items() if count >= 2})

    def pair_similarity(source, target):
        if observed[source] == expected[target]:
            return 1.
        return similarity_score(observed[source], expected[target]) if target in fuzzy_context[source] else 0.

    width = len(expected) + 1
    directions = [bytearray(width) for _ in range(len(observed) + 1)]
    previous = [0.] * width
    candidates = {}
    for row, actual in enumerate(observed, 1):
        current = [0.] * width
        endpoints = []
        for column, wanted in enumerate(expected, 1):
            similarity = pair_similarity(row - 1, column - 1)
            reward = 3. if similarity == 1 else (.2 + similarity if similarity >= .5 else -3.)
            values = (0., previous[column - 1] + reward,
                      previous[column] - 1.5, current[column - 1] - 1.5)
            move = max(range(4), key=values.__getitem__)
            current[column], directions[row][column] = values[move], move
            if move == 1 and values[move] >= 4.:
                endpoints.append((column, values[move]))
        best = max((score for _, score in endpoints), default=0.)
        contexts = set()
        for column, score in endpoints:
            if score < best - 1.5:
                continue
            context = tuple(expected[max(0, column - len(units)):column])
            context_key = (round(score, 4), context)
            if context_key in contexts:
                continue
            contexts.add(context_key)
            source, target, mapping, exact = row, column, {}, set()
            while source and target and directions[source][target]:
                move = directions[source][target]
                if move == 1:
                    similarity = pair_similarity(source - 1, target - 1)
                    if similarity >= .5 and _safe_spelling_pair(official[target - 1], units[source - 1]['word']['word']):
                        mapping[source - 1] = target - 1
                        if observed[source - 1] == expected[target - 1]:
                            exact.add(source - 1)
                    source, target = source - 1, target - 1
                elif move == 2:
                    source -= 1
                else:
                    target -= 1
            if len(exact) < 2 or not mapping:
                continue
            left, right = min(mapping), max(mapping) + 1
            guide_span = max(mapping.values()) - min(mapping.values()) + 1
            if len(mapping) / max(right - left, guide_span) < .55:
                continue
            mapping = {index: guide_index for index, guide_index in mapping.items()
                       if index in exact or sum(abs(anchor - index) <= 3 for anchor in exact) >= 2}
            if not mapping:
                continue
            key = tuple(sorted((index, expected[guide_index]) for index, guide_index in mapping.items()))
            candidate = dict(start=min(mapping), end=max(mapping) + 1, mapping=mapping,
                             score=score + .1 * len(mapping))
            if key not in candidates or candidate['score'] > candidates[key]['score']:
                candidates[key] = candidate
        previous = current
    return list(candidates.values())


def _strict_exact_cover(official, units):
    """Fast path for already canonical/reviewed phrases, including refrains."""
    expected = [normalize_word(token) for token in official]
    observed = [unit['normalized'] for unit in units]
    positions = {}
    for index, token in enumerate(expected):
        positions.setdefault(token, []).append(index)
    mapping, index = {}, 0
    while index < len(observed):
        best_start, best_size = 0, 0
        for start in positions.get(observed[index], ()):
            size = 0
            while (index + size < len(observed) and start + size < len(expected)
                   and observed[index + size] == expected[start + size]):
                size += 1
            if size > best_size:
                best_start, best_size = start, size
        if best_size < 2:
            return None
        mapping.update((index + offset, best_start + offset) for offset in range(best_size))
        index += best_size
    return mapping


def _enforce_guide_tokens(lyrics, segments):
    """Final lexical contract: emit only contextual guide words on local clocks.

    This function does not infer voice activity from text. Callers must retain
    their acoustic checks, including on cache/review/fallback paths. External
    LRC clocks never replace the observed start/end of an emitted word.
    """
    guide = prepare_lyrics_guide(lyrics)
    count = sum(len(segment.get('words', [])) for segment in segments or [])
    report = dict(policy='strict_guide', version=GUIDE_POLICY_VERSION,
                  input_words=count, kept_words=count, removed_words=0,
                  corrected_words=0, merged_words=0, ambiguous_words=0, invalid_words=0, checks=[])
    if not guide:
        report['status'] = 'no_guide'
        return copy.deepcopy(segments), report
    official = [token for token in guide.split() if normalize_word(token)]
    units, invalid = _strict_source_words(segments, official)
    report['invalid_words'] = len(invalid)
    accepted, ambiguous = {}, set()
    if len(official) == 1:
        # A deliberately one-word refrain still requires its own observed event.
        accepted = {index: 0 for index, unit in enumerate(units)
                    if unit['normalized'] == normalize_word(official[0])}
    elif official and len(official) <= 12000:
        @lru_cache(maxsize=65536)
        def similarity_score(actual, wanted):
            return 1. if actual == wanted else difflib.SequenceMatcher(None, actual, wanted).ratio()

        groups, group = [], []
        for index, unit in enumerate(units):
            if group and (float(unit['word']['start']) - float(units[group[-1]]['word']['end']) > 2.5
                          or float(unit['word']['start']) < float(units[group[-1]]['word']['start'])):
                groups.append(group)
                group = []
            group.append(index)
        if group:
            groups.append(group)
        for indices in groups:
            exact = _strict_exact_cover(official, [units[index] for index in indices])
            if exact is not None:
                accepted.update((indices[index], guide_index) for index, guide_index in exact.items())
                continue
            candidates = []
            for offset in range(0, len(indices), 20):
                window = indices[offset:offset + 32]
                if len(window) < 2:
                    continue
                for candidate in _strict_phrase_candidates(official, [units[index] for index in window], similarity_score):
                    candidate['mapping'] = {offset + index: guide_index
                                            for index, guide_index in candidate['mapping'].items()}
                    candidate['start'] += offset
                    candidate['end'] += offset
                    candidates.append(candidate)
            starts = {}
            for candidate in candidates:
                starts.setdefault(candidate['start'], []).append(candidate)
            scores, selected = [0.] * (len(indices) + 1), {}
            for index in range(len(indices) - 1, -1, -1):
                scores[index] = scores[index + 1]
                for candidate in starts.get(index, []):
                    value = candidate['score'] + scores[candidate['end']]
                    if value > scores[index] + 1e-6:
                        scores[index], selected[index] = value, candidate
            index = 0
            while index < len(indices):
                chosen = selected.get(index)
                if chosen is None:
                    index += 1
                    continue
                for local, guide_index in chosen['mapping'].items():
                    alternatives = [other for other in candidates
                                    if local in other['mapping'] and other['score'] >= chosen['score'] - .25
                                    and len(set(other['mapping']) & set(chosen['mapping'])) >= .8 * len(chosen['mapping'])]
                    choices = {normalize_word(official[other['mapping'][local]]) for other in alternatives}
                    actual_index = indices[local]
                    if len(choices) > 1:
                        ambiguous.add(actual_index)
                    else:
                        accepted[actual_index] = guide_index
                index = chosen['end']
    result, by_segment, checks = [], {}, list(invalid)
    retained_sources = 0
    for index, unit in enumerate(units):
        word, source_indices = copy.deepcopy(unit['word']), unit['sources']
        target = accepted.get(index)
        check = dict(source_indices=source_indices, recognized=str(word['word']).strip(),
                     guide=official[target] if target is not None else None,
                     start=word['start'], end=word['end'])
        if target is None:
            check['status'] = 'ambiguous' if index in ambiguous else 'unmatched'
            report['ambiguous_words'] += len(source_indices) if index in ambiguous else 0
        else:
            canonical = official[target]
            changed = str(word['word']).strip() != canonical
            check['status'] = 'corrected' if changed else 'matched'
            word['word'] = ' ' + canonical
            if changed:
                word.pop('alignment_chars', None)
                report['corrected_words'] += 1
            by_segment.setdefault(unit['segment'], []).append(word)
            retained_sources += len(source_indices)
            report['merged_words'] += len(source_indices) - 1
        checks.append(check)
    for index, segment in enumerate(segments or []):
        words = by_segment.get(index, [])
        if not words:
            continue
        cleaned = copy.deepcopy(segment)
        for field in ('synced_line', 'acoustic_animation', 'animation_words'):
            cleaned.pop(field, None)
        cleaned.update(start=words[0]['start'], end=max(word['end'] for word in words),
                       text=''.join(word['word'] for word in words).strip(), words=words)
        result.append(cleaned)
    result, _ = apply_guide_boundaries(guide, result)
    report.update(kept_words=sum(len(segment['words']) for segment in result),
                  removed_words=count - retained_sources, checks=checks,
                  status='unrelated' if not result else ('filtered' if count != retained_sources
                          or report['corrected_words'] or report['merged_words'] else 'verified'))
    return result, report


def enforce_guide_text(lyrics, segments):
    """Enforce canonical guide text, preserving an explicitly timed manual phrase.

    A manually reviewed phrase may have one clock for several words. Virtual
    tokens are used only for comparison: an accepted phrase is returned with
    that one original interval. Partial/ambiguous phrases are withheld whole.
    """
    if not prepare_lyrics_guide(lyrics):
        return _enforce_guide_tokens(lyrics, segments)
    expanded, spans, source_index = copy.deepcopy(segments or []), {}, 0
    for segment in expanded:
        words = []
        for source in segment.get('words', []):
            for key in list(source):
                if key.startswith('_strict_span_'):
                    source.pop(key)
            tokens = str(source.get('word', '')).split()
            if len(tokens) <= 1:
                words.append(source)
                source_index += 1
                continue
            identifier = len(spans)
            spans[identifier] = dict(word=copy.deepcopy(source), tokens=tokens,
                                     source_indices=set(range(source_index, source_index + len(tokens))))
            for part, token in enumerate(tokens):
                word = copy.deepcopy(source)
                word.update(word=' ' + token, _strict_span_id=identifier, _strict_span_part=part)
                words.append(word)
                source_index += 1
        segment['words'] = words
    result, report = _enforce_guide_tokens(lyrics, expanded)
    if not spans:
        return result, report
    official = [normalize_word(token) for token in prepare_lyrics_guide(lyrics).split() if normalize_word(token)]
    observed = {}
    for segment in result:
        for word in segment['words']:
            if '_strict_span_id' in word:
                observed.setdefault(word['_strict_span_id'], []).append(word)
    accepted, rejected_sources = {}, set()
    for identifier, span in spans.items():
        words = observed.get(identifier, [])
        normalized = [normalize_word(word['word']) for word in words]
        complete = (len(words) == len(span['tokens']) and
                    [word['_strict_span_part'] for word in words] == list(range(len(span['tokens']))))
        contiguous = complete and any(official[start:start + len(words)] == normalized
                                      for start in range(len(official) - len(words) + 1))
        if contiguous:
            word = copy.deepcopy(span['word'])
            for field in list(word):
                if field.startswith('lyric_line_'):
                    word.pop(field)
            canonical = ' '.join(item['word'].strip() for item in words)
            word.update(word=' ' + canonical, start=words[0]['start'], end=words[0]['end'])
            if canonical != str(span['word']['word']).strip():
                word.pop('alignment_chars', None)
            accepted[identifier] = word
        else:
            rejected_sources.update(span['source_indices'])
            report['removed_words'] += len(words)
            report['kept_words'] -= len(words)
            report['corrected_words'] -= sum(item['word'].strip() != span['tokens'][item['_strict_span_part']]
                                             for item in words)
    collapsed = []
    for segment in result:
        words, seen = [], set()
        for word in segment['words']:
            identifier = word.get('_strict_span_id')
            if identifier is None:
                words.append(word)
            elif identifier in accepted and identifier not in seen:
                words.append(copy.deepcopy(accepted[identifier]))
                seen.add(identifier)
        if words:
            segment.update(start=words[0]['start'], end=max(word['end'] for word in words),
                           text=''.join(word['word'] for word in words).strip(), words=words)
            collapsed.append(segment)
    for check in report['checks']:
        if rejected_sources.intersection(check['source_indices']):
            check.update(guide=None, status='span_rejected')
    report.update(phrase_spans=len(accepted), rejected_spans=len(spans) - len(accepted))
    if not collapsed:
        report['status'] = 'unrelated'
    elif report['rejected_spans']:
        report['status'] = 'filtered'
    return collapsed, report


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
