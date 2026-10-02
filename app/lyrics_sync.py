"""Use provider timestamps only for a confidently matched recording.

LRC timestamps describe lines, not words. Production animation obtains word
clocks from the recording instead of dividing the provider verse interval.
"""
import math
import re
import unicodedata
from statistics import median
from difflib import SequenceMatcher


def normalize_identity(value):
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\b(?:official|oficial|music|video|audio|lyrics|hd|4k)\b", " ", text)
    return " ".join(re.findall(r"\w+", text))


def recording_matches(query, record, duration, check_duration=True):
    """Require artist, title, version and duration before trusting LRC clocks."""
    parts = re.split(r"\s+[-–—|]\s+", str(query or ""), maxsplit=1)
    if len(parts) != 2:
        return False
    artist, title = map(normalize_identity, parts)
    candidate_artist = normalize_identity(record.get("artist_name"))
    candidate_title = normalize_identity(record.get("track_name"))
    if not all((artist, title, candidate_artist, candidate_title)):
        return False
    # These versions commonly have different intros, cuts and arrangements.
    versions = {"live", "vivo", "remix", "cover", "acoustic", "acustico", "karaoke", "sped", "slowed"}
    if (set(title.split()) & versions) != (set(candidate_title.split()) & versions):
        return False
    identity_matches = (
        SequenceMatcher(None, artist, candidate_artist).ratio() >= 0.85
        and SequenceMatcher(None, title, candidate_title).ratio() >= 0.85
    )
    if not check_duration:
        return identity_matches
    try:
        actual, expected = float(duration), float(record.get("duration"))
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(v) and v > 0 for v in (actual, expected)):
        return False
    return (
        abs(actual - expected) <= 2
        and identity_matches
    )


def parse_lrc(text, duration):
    """Parse repeated timestamps, offsets and blank instrumental boundaries."""
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        return []
    if not math.isfinite(duration) or duration <= 0 or not isinstance(text, str):
        return []
    offset_match = re.search(r"\[offset:([+-]?\d+)\]", text, re.I)
    offset = int(offset_match[1]) / 1000 if offset_match else 0
    stamp = re.compile(r"\[(\d{1,3}):([0-5]\d)(?:[.:](\d{1,3}))?\]")
    entries = {}
    for line in text.splitlines():
        times = list(stamp.finditer(line))
        if not times:
            continue
        lyric = stamp.sub("", line).strip()
        # Enhanced LRC includes word clocks; this parser intentionally uses lines.
        lyric = re.sub(r"<\d+:\d+(?:\.\d+)?>", "", lyric).strip()
        for match in times:
            start = int(match[1]) * 60 + int(match[2]) + float("0." + (match[3] or "0")) + offset
            if 0 <= start < duration:
                if start in entries and entries[start] != lyric:
                    return []  # Ambiguous simultaneous lines: use acoustic fallback.
                entries[start] = lyric
    ordered = sorted(entries.items())
    segments = []
    for index, (start, lyric) in enumerate(ordered):
        end = ordered[index + 1][0] if index + 1 < len(ordered) else duration
        # LRC has no reliable sung end. Cap display to preserve long instrumental gaps.
        end = min(end, start + 12)
        if lyric and end > start:
            segments.append({"start": start, "end": end, "text": lyric, "words": [], "synced_line": True})
    return segments if len(segments) >= 2 else []


def require_acoustic_word_timing(segments):
    """Reject stale verse-only results rather than render an artificial sweep."""
    if not segments:
        raise ValueError("Não foi possível medir os tempos das palavras cantadas.")
    for segment in segments:
        words = segment.get("words") or []
        if not words:
            raise ValueError("A letra não tem tempos de palavras medidos na voz. Tente outro modelo Whisper ou revise a gravação.")
        for word in words:
            try:
                start, end = float(word["start"]), float(word["end"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("Tempos de palavras inválidos na sincronização da animação.") from None
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError("Tempos de palavras inválidos na sincronização da animação.")
    return segments


def assess_synced_timing(synced_segments, acoustic_segments):
    """Detect a wrong recording clock without moving any provider timestamps.

    Metadata and total duration do not prove that a video has the same intro
    as the lyric recording. Compare locally repeated, exact phrase prefixes
    with measured word clocks. Several agreeing verses are required; a single
    recognition error or an unrecognized verse cannot reject the whole lyric.
    """
    def key(text):
        value = unicodedata.normalize('NFKD', str(text)).casefold()
        return ''.join(re.findall(r'\w+', ''.join(c for c in value if not unicodedata.combining(c))))

    words = []
    for segment in acoustic_segments:
        for word in segment.get('words', []):
            try:
                start, end = float(word['start']), float(word['end'])
            except (KeyError, TypeError, ValueError):
                continue
            token = key(word.get('word', ''))
            if token and math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
                words.append((token, start, end))
    words.sort(key=lambda word: word[1])
    offsets = []
    for verse in synced_segments:
        prefix = [key(token) for token in str(verse['text']).split() if key(token)][:3]
        if len(prefix) < 2:
            continue
        start = float(verse['start'])
        candidates = []
        for index in range(len(words) - len(prefix) + 1):
            phrase = words[index:index + len(prefix)]
            if abs(phrase[0][1] - start) > 12:
                continue
            if [word[0] for word in phrase] != prefix:
                continue
            if any(phrase[i + 1][1] - phrase[i][2] > .75 for i in range(len(phrase) - 1)):
                continue
            candidates.append(phrase[0][1] - start)
        if candidates:
            # Repeated choruses must stay near their own occurrence.
            offsets.append(min(candidates, key=abs))

    result = dict(status='inconclusive', checked_verses=len(offsets),
                  total_verses=len(synced_segments), median_offset_seconds=None)
    if len(offsets) < max(3, math.ceil(len(synced_segments) * .15)):
        return result
    center = median(offsets)
    result['median_offset_seconds'] = round(center, 3)
    later = sum(offset > 1 for offset in offsets) / len(offsets)
    earlier = sum(offset < -1 for offset in offsets) / len(offsets)
    far = sum(abs(offset) > 2 for offset in offsets) / len(offsets)
    if (abs(center) > 1.5 and max(later, earlier) >= .75) or far >= .75:
        result['status'] = 'incompatible'
    elif abs(center) <= 1.5 and far <= .25:
        result['status'] = 'consistent'
    return result


def anchor_synced_animation(synced_segments, acoustic_segments):
    """Keep every provider verse/text intact; match animation clocks only in its window."""
    acoustic_words = [word for segment in acoustic_segments for word in segment.get('words', [])]
    result = []
    def key(text):
        value = unicodedata.normalize('NFKD', str(text)).casefold()
        value = ''.join(char for char in value if not unicodedata.combining(char))
        return ''.join(re.findall(r'\w+', value))
    for verse in synced_segments:
        start, end = float(verse['start']), float(verse['end'])
        tokens = str(verse['text']).split()
        candidates = []
        for word in acoustic_words:
            try:
                w_start, w_end = float(word['start']), float(word['end'])
            except (KeyError, TypeError, ValueError):
                continue
            if (math.isfinite(w_start) and math.isfinite(w_end) and w_end > w_start
                    and start <= (w_start + w_end) / 2 < end and key(word.get('word', ''))):
                candidates.append(word)
        matcher = SequenceMatcher(None, [key(token) for token in tokens],
                                  [key(word['word']) for word in candidates], autojunk=False)
        clocks = {}
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                index = block.a + offset
                word = candidates[block.b + offset]
                clocks[index] = (max(start, float(word['start'])), min(end, float(word['end'])))
        animation_words, matched_words = [], []
        for index, token in enumerate(tokens):
            word = {'word': token + (' ' if index < len(tokens) - 1 else '')}
            if index in clocks:
                word['start'], word['end'] = clocks[index]
                matched_words.append(dict(word))
            animation_words.append(word)
        result.append({**verse, 'words': matched_words, 'animation_words': animation_words,
                       'synced_line': True, 'acoustic_animation': True})
    return result


def retime_synced_verses(synced_segments, acoustic_segments):
    """Use locally measured verse clocks while retaining all provider text.

    Global sequence matching keeps repeated choruses in occurrence order. A
    verse without sufficient recognized words retains its provider clock; it
    never gets replaced with the recognized text or removed from the lyrics.
    """
    def key(value):
        value = unicodedata.normalize('NFKD', str(value)).casefold()
        return ''.join(re.findall(r'\w+', ''.join(c for c in value if not unicodedata.combining(c))))

    lyric_tokens = []
    ranges = []
    for verse in synced_segments:
        begin = len(lyric_tokens)
        lyric_tokens.extend(key(token) for token in str(verse['text']).split())
        ranges.append((begin, len(lyric_tokens)))
    acoustic = []
    for segment in acoustic_segments:
        for word in segment.get('words', []):
            try:
                start, end = float(word['start']), float(word['end'])
            except (KeyError, TypeError, ValueError):
                continue
            token = key(word.get('word', ''))
            if token and math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
                acoustic.append((token, start, end))
    acoustic.sort(key=lambda word: word[1])
    matcher = SequenceMatcher(None, lyric_tokens, [word[0] for word in acoustic], autojunk=False)
    clocks = {block.a + i: acoustic[block.b + i][1:]
              for block in matcher.get_matching_blocks() for i in range(block.size)}
    result = []
    for verse, (begin, end) in zip(synced_segments, ranges):
        measured = [clocks[i] for i in range(begin, end) if i in clocks]
        updated = dict(verse)
        if len(measured) >= max(2, math.ceil((end - begin) * .35)):
            updated.update(start=measured[0][0], end=measured[-1][1], local_verse_timing=True)
        result.append(updated)
    return result
