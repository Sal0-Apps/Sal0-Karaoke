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


def stabilize_word_timestamps(segments: list[dict], audio_duration: float = None) -> list[dict]:
    """Mantém palavras em ordem temporal sem deslocar trechos inteiros."""
    if not segments:
        return segments

    stabilized = []
    previous_word = None
    adjusted = 0
    duration = _safe_time(audio_duration, 0.0)

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
            # Uma sílaba válida de 20 ms deve preservar seu relógio acústico.
            # Duração mínima serve apenas para tempos nulos/invertidos.
            if end <= start:
                end = start + MIN_WORD_DURATION
            if duration > 0:
                if start >= duration:
                    continue
                end = min(end, duration)

            current = {**source_word, "word": text, "start": start, "end": end}
            if previous_word is not None and current["start"] < previous_word["end"]:
                # Divide apenas a pequena região sobreposta. Não usa o tamanho da
                # palavra seguinte para recalcular o restante da frase.
                boundary = (previous_word["end"] + current["start"]) / 2.0
                previous_minimum = min(MIN_WORD_DURATION, previous_word["end"] - previous_word["start"])
                current_minimum = min(MIN_WORD_DURATION, current["end"] - current["start"])
                boundary = max(previous_word["start"] + previous_minimum, boundary)
                if boundary >= current["end"]:
                    boundary = min(
                        previous_word["end"],
                        max(previous_word["start"] + previous_minimum, current["end"] - current_minimum),
                    )
                previous_word["end"] = max(previous_word["start"] + previous_minimum, boundary)
                current["start"] = previous_word["end"]
                if duration > 0 and current["start"] >= duration:
                    adjusted += 1
                    continue
                current["end"] = max(current["start"] + current_minimum, current["end"])
                if duration > 0:
                    current["end"] = min(current["end"], duration)
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

    # A próxima frase pode corrigir a última palavra da anterior. Atualizar
    # limites depois de todas as correções evita segmentos sobrepostos no ASS.
    for segment in stabilized:
        segment["start"] = segment["words"][0]["start"]
        segment["end"] = segment["words"][-1]["end"]

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
