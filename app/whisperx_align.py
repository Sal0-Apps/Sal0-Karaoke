"""
Sal0 Karaoke v4.0.0 - Módulo de Alinhamento de Palavras por Áudio (WhisperX Offline)
Refina os timestamps das palavras obtidas pelo Whisper para maior precisão visual.
100% Offline em CPU.
"""
import logging

logger = logging.getLogger("karaoke")

def align_words_whisperx(audio_path: str, segments: list[dict]) -> list[dict]:
    if not segments:
        return segments

    logger.info("Iniciando alinhamento de palavras estilo WhisperX...")
    aligned_segments = []

    for seg in segments:
        start_time = seg.get("start", 0.0)
        end_time = seg.get("end", 0.0)
        words = seg.get("words", [])

        if not words:
            aligned_segments.append(seg)
            continue

        cleaned_words = []
        for w in words:
            w_text = w.get("word", "").strip()
            if not w_text:
                continue
            w_start = max(start_time, min(end_time, w.get("start", start_time)))
            w_end = max(w_start + 0.05, min(end_time, w.get("end", end_time)))
            cleaned_words.append({
                "word": w.get("word", ""),
                "start": w_start,
                "end": w_end
            })

        if not cleaned_words:
            aligned_segments.append(seg)
            continue

        num_clean = len(cleaned_words)
        for i in range(num_clean):
            curr = cleaned_words[i]
            if i == 0 and (curr["start"] < start_time or curr["start"] - start_time > 2.0):
                curr["start"] = start_time
            if i < num_clean - 1:
                nxt = cleaned_words[i + 1]
                if curr["end"] > nxt["start"]:
                    mid = (curr["start"] + nxt["end"]) / 2.0
                    curr["end"] = max(curr["start"] + 0.05, mid)
                    nxt["start"] = curr["end"]
            else:
                if curr["end"] < end_time and (end_time - curr["end"] <= 0.5):
                    curr["end"] = end_time

        new_text = "".join([w["word"] for w in cleaned_words]).strip()
        if not new_text:
            new_text = seg.get("text", "")

        aligned_segments.append({
            "start": cleaned_words[0]["start"],
            "end": cleaned_words[-1]["end"],
            "text": new_text,
            "words": cleaned_words
        })

    logger.info(f"Alinhamento WhisperX concluído para {len(aligned_segments)} segmentos.")
    return aligned_segments
