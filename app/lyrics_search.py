"""Validate provider results before displaying or automatically using a guide."""
import re
import unicodedata
from difflib import SequenceMatcher

from lyric_guide import prepare_lyrics_guide

AUTO_LYRICS_POLICY_VERSION = 2


def normalize_search(value):
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'\.(?:mp3|mp4|wav|m4a|webm|flac|ogg)$', '', text)
    text = re.sub(r'\b(?:official|oficial|music|video|audio|lyrics|lyric|mv|hd|4k|ver|version)\b', ' ', text)
    return ' '.join(re.findall(r'\w+', text))


def split_search_identity(query):
    parts = re.split(r'\s+[-–—:/|]\s+', str(query or '').strip(), maxsplit=1)
    return tuple(parts) if len(parts) == 2 and all(part.strip() for part in parts) else None


def _contains(text, phrase):
    return bool(phrase and (' ' + phrase + ' ') in (' ' + text + ' '))


def _identity_similarity(query, candidate):
    if not query or not candidate:
        return 0.0
    return SequenceMatcher(None, query, candidate).ratio()


def _automatic_title(value):
    # Parenthetical video labels, language versions and alternate CJK titles
    # can decorate the same title. Other qualifiers (e.g. Part 2) stay intact.
    def decoration(match):
        content = match.group()[1:-1]
        if not normalize_search(content) or _versions(content) or re.search(r'[\u3040-\u30ff\u3400-\u9fff]', content):
            return ' '
        return match.group()
    title = re.sub(r'\([^)]*\)|\[[^]]*\]|【[^】]*】', decoration, str(value or ''))
    versions = _versions(value)
    return ' '.join(word for word in normalize_search(title).split() if word not in versions)


def _versions(value):
    return set(normalize_search(value).split()) & {
        'live', 'vivo', 'remix', 'cover', 'acoustic', 'acustico', 'karaoke',
        'sped', 'slowed', 'english', 'japanese', 'portuguese', 'instrumental',
    }


def lyrics_match_score(query, record, automatic=False):
    if not isinstance(record, dict):
        return 0.0
    query_text = normalize_search(query)
    title = normalize_search(record.get('track_name'))
    artist = normalize_search(record.get('artist_name'))
    if not query_text or not title or not artist:
        return 0.0
    if automatic:
        # Automatic choices require both identities; a broad title-only search
        # remains available for the user to review manually.
        if _versions(query) != _versions(record.get('track_name')):
            return 0.0
        title = _automatic_title(record.get('track_name'))
        parts = split_search_identity(query)
        if parts:
            pairs = (parts, parts[::-1])
            scores = [min(_identity_similarity(normalize_search(a), artist), _identity_similarity(_automatic_title(t), title))
                      for a, t in pairs]
            score = max(scores)
            return score if score >= .85 else 0.0
        return 1.0 if _contains(query_text, title) and _contains(query_text, artist) else 0.0

    # Manual queries can contain only an artist/title, a partial phrase, or a
    # typo. Unrelated chart/default responses still have no place in the list.
    if _contains(title, query_text) or _contains(artist, query_text):
        return 1.0
    identity = title + ' ' + artist
    words = query_text.split()
    covered = sum(len(word) for word in words if _contains(identity, word))
    coverage = covered / max(1, sum(map(len, words)))
    similarity = max(SequenceMatcher(None, query_text, title).ratio(),
                     SequenceMatcher(None, query_text, artist).ratio(),
                     SequenceMatcher(None, query_text, identity).ratio())
    score = max(coverage, similarity)
    return score if score >= .7 else 0.0


def relevant_lyrics_results(query, records):
    ranked = [(lyrics_match_score(query, item), index, item) for index, item in enumerate(records)]
    return [item for score, _, item in sorted(ranked, key=lambda row: (-row[0], row[1])) if score > 0]


def select_automatic_lyrics(query, records):
    candidates = []
    for item in records:
        score = lyrics_match_score(query, item, automatic=True)
        if not score or item.get('instrumental') or not item.get('has_lyrics'):
            continue
        text = prepare_lyrics_guide(item.get('lyrics_text') or item.get('synced_lyrics'))
        if text:
            candidates.append((score + (.25 if item.get('synced_lyrics') else 0), {**item, 'lyrics_text': text}))
    return max(candidates, key=lambda row: row[0])[1] if candidates else None
