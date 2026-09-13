import os
import re
import tempfile
from pathlib import Path


SUPPORTED_TARGET_LANGUAGES = {"original", "pt-BR", "pt", "en", "es"}


def normalize_translation_language(value):
    language = (value or "pt-BR").strip().replace("_", "-").lower()
    return "pt-BR" if language == "pt-br" else language


def cover_full_media_timeline(segments: list[dict], duration: float) -> list[dict]:
    """Ajusta os intervalos para o SRT cobrir a mídia inteira, sem lacunas."""
    normalized = [dict(segment) for segment in segments if str(segment.get("text") or "").strip()]
    normalized.sort(key=lambda segment: float(segment.get("start", 0.0)))
    if not normalized:
        return []

    media_end = max(float(duration or 0.0), float(normalized[-1].get("end", 0.0)))
    normalized[0]["start"] = 0.0
    for index in range(len(normalized) - 1):
        current = normalized[index]
        following = normalized[index + 1]
        current_start = float(current.get("start", 0.0))
        current_end = max(current_start, float(current.get("end", current_start)))
        following_start = max(current_start, float(following.get("start", current_end)))
        boundary = max(current_start, min(media_end, (current_end + following_start) / 2.0))
        current["end"] = boundary
        following["start"] = boundary

    normalized[-1]["end"] = max(float(normalized[-1].get("start", 0.0)), media_end)
    return normalized


def rebuild_segment_words(text: str, start: float, end: float) -> list[dict]:
    words = [word for word in (text or "").split() if word]
    if not words:
        return []
    duration = max(float(end) - float(start), 0.05)
    slice_duration = duration / len(words)
    return [
        {
            "word": (" " if index else "") + word,
            "start": float(start) + (slice_duration * index),
            "end": float(start) + (slice_duration * (index + 1)),
        }
        for index, word in enumerate(words)
    ]


def translate_subtitle_segments(
    segments: list[dict],
    source_language: str = "auto",
    target_language: str = "pt-BR",
    progress_callback=None,
) -> list[dict]:
    """Traduz exclusivamente via LibreTranslate, preservando os tempos."""
    target_language = normalize_translation_language(target_language)
    if target_language not in SUPPORTED_TARGET_LANGUAGES:
        raise ValueError("Idioma de tradução não suportado.")
    if target_language == "original" or not segments:
        return [dict(segment) for segment in segments]
    from libretranslate_client import LibreTranslateClient
    import process_manager as pm
    client = LibreTranslateClient(cancel_event=pm.cancel_event)
    try:
        with tempfile.TemporaryDirectory() as directory:
            original = str(Path(directory) / "original.srt")
            translated = str(Path(directory) / "translated.srt")
            write_srt(segments, original)
            return client.translate_srt_file(original, translated, target_language, progress_callback)
    finally:
        client.close()


def translate_subtitle_file(source_path, destination, target_language="pt-BR", progress_callback=None):
    from libretranslate_client import LibreTranslateClient
    import process_manager as pm
    target_language = normalize_translation_language(target_language)
    if target_language not in SUPPORTED_TARGET_LANGUAGES - {"original"}:
        raise ValueError("Idioma de tradução não suportado.")
    client = LibreTranslateClient(cancel_event=pm.cancel_event)
    try:
        return client.translate_srt_file(source_path, destination, target_language, progress_callback)
    finally:
        client.close()


def parse_srt(text):
    """Valida a estrutura do SRT antes de publicar o arquivo traduzido."""
    stamp = r"(\d{2,}):(\d{2}):(\d{2}),(\d{3})"
    pattern = re.compile(r"^" + stamp + r"\s*-->\s*" + stamp + r"(?:\s+.*)?$")
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise ValueError("Bloco SRT inválido.")
        match = pattern.fullmatch(lines[1].strip())
        if not match:
            raise ValueError("Tempos SRT inválidos.")
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        body = "\n".join(lines[2:]).strip()
        if not body or end < start or max(m1, m2, s1, s2) >= 60:
            raise ValueError("Conteúdo SRT inválido.")
        segments.append({"start": start, "end": end, "text": body})
    return segments


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def write_srt(segments: list[dict], destination: str):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    blocks = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        index = len(blocks) + 1
        blocks.append(
            f"{index}\n{srt_timestamp(segment.get('start', 0.0))} --> "
            f"{srt_timestamp(segment.get('end', 0.0))}\n{text}"
        )
    with open(destination, "w", encoding="utf-8-sig", newline="\n") as subtitle_file:
        subtitle_file.write("\n\n".join(blocks) + ("\n" if blocks else ""))
