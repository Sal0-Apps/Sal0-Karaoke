"""Normalização local e conservadora dos timestamps produzidos pelo Whisper.

Este módulo não executa o alinhamento acústico do projeto WhisperX. Ele apenas
remove valores inválidos e pequenos cruzamentos entre palavras, sem inventar
tempos ou redistribuir a letra ao longo da música.
"""
import logging
import math

logger = logging.getLogger("karaoke")

MIN_WORD_DURATION = 0.05


def _safe_time(value, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def stabilize_word_timestamps(segments: list[dict]) -> list[dict]:
    """Mantém palavras em ordem temporal sem deslocar trechos inteiros."""
    if not segments:
        return segments

    stabilized = []
    previous_word = None
    adjusted = 0

    for source_segment in segments:
        segment_start = max(0.0, _safe_time(source_segment.get("start"), 0.0))
        segment_end = max(segment_start, _safe_time(source_segment.get("end"), segment_start))
        words = []

        for source_word in source_segment.get("words", []):
            text = str(source_word.get("word", ""))
            if not text.strip():
                continue

            start = max(0.0, _safe_time(source_word.get("start"), segment_start))
            end = _safe_time(source_word.get("end"), max(start + MIN_WORD_DURATION, segment_end))
            end = max(start + MIN_WORD_DURATION, end)

            current = {"word": text, "start": start, "end": end}
            if previous_word is not None and current["start"] < previous_word["end"]:
                # Divide apenas a pequena região sobreposta. Não usa o tamanho da
                # palavra seguinte para recalcular o restante da frase.
                boundary = (previous_word["end"] + current["start"]) / 2.0
                boundary = max(previous_word["start"] + MIN_WORD_DURATION, boundary)
                if boundary >= current["end"]:
                    boundary = min(
                        previous_word["end"],
                        max(previous_word["start"] + MIN_WORD_DURATION, current["end"] - MIN_WORD_DURATION),
                    )
                previous_word["end"] = max(previous_word["start"] + MIN_WORD_DURATION, boundary)
                current["start"] = previous_word["end"]
                current["end"] = max(current["start"] + MIN_WORD_DURATION, current["end"])
                adjusted += 1

            words.append(current)
            previous_word = current

        if not words:
            continue

        stabilized.append({
            **source_segment,
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": "".join(word["word"] for word in words).strip(),
            "words": words,
        })

    logger.info(
        "Timestamps estabilizados em %s segmentos; %s pequenas sobreposições corrigidas.",
        len(stabilized),
        adjusted,
    )
    return stabilized


def align_words_whisperx(audio_path: str, segments: list[dict]) -> list[dict]:
    """Alias mantido para compatibilidade com versões anteriores."""
    del audio_path
    return stabilize_word_timestamps(segments)
