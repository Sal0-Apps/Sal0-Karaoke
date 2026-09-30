"""Use provider timestamps only for a confidently matched recording.

LRC timestamps describe lines, not words. Never fabricate word timings from
them; word highlighting remains the responsibility of the acoustic pipeline.
"""
import math
import re
import unicodedata
from difflib import SequenceMatcher


def normalize_identity(value):
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\b(?:official|oficial|music|video|audio|lyrics|hd|4k)\b", " ", text)
    return " ".join(re.findall(r"\w+", text))


def recording_matches(query, record, duration):
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
    try:
        actual, expected = float(duration), float(record.get("duration"))
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(v) and v > 0 for v in (actual, expected)):
        return False
    return (
        abs(actual - expected) <= 2
        and SequenceMatcher(None, artist, candidate_artist).ratio() >= 0.85
        and SequenceMatcher(None, title, candidate_title).ratio() >= 0.85
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
            segments.append({"start": start, "end": end, "text": lyric, "words": []})
    return segments if len(segments) >= 2 else []
