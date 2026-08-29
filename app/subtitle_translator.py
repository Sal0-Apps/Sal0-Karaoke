import gc
import logging
import os


logger = logging.getLogger("karaoke")

TRANSLATION_MODEL = "facebook/m2m100_418M"
TRANSLATION_MODEL_REVISION = "791dc1c6d300846c9a747d4bd11fcc7f369b750e"
TRANSLATION_MODEL_DIR = "/data/output/models/translation"
SUPPORTED_TARGET_LANGUAGES = {"original", "pt", "en", "es"}


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
    source_language: str,
    target_language: str,
    progress_callback=None,
) -> list[dict]:
    """Traduz textos localmente e preserva os intervalos originais da legenda."""
    source_language = (source_language or "").split("-")[0].lower()
    target_language = (target_language or "original").split("-")[0].lower()
    if target_language not in SUPPORTED_TARGET_LANGUAGES:
        raise ValueError("Idioma de tradução não suportado.")
    if target_language == "original" or target_language == source_language:
        return [dict(segment) for segment in segments]
    if not source_language:
        raise ValueError("O Whisper não conseguiu identificar o idioma do vídeo.")

    try:
        import torch
        from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
    except ImportError as exc:
        raise RuntimeError("Os componentes locais de tradução não estão instalados na imagem.") from exc

    os.makedirs(TRANSLATION_MODEL_DIR, exist_ok=True)
    logger.info(
        "Carregando tradução local %s (%s → %s).",
        TRANSLATION_MODEL,
        source_language,
        target_language,
    )
    tokenizer = M2M100Tokenizer.from_pretrained(
        TRANSLATION_MODEL,
        revision=TRANSLATION_MODEL_REVISION,
        cache_dir=TRANSLATION_MODEL_DIR,
    )
    if source_language not in tokenizer.lang_code_to_id:
        raise ValueError(f"O idioma detectado ({source_language}) não é suportado pelo tradutor local.")
    if target_language not in tokenizer.lang_code_to_id:
        raise ValueError(f"O idioma de destino ({target_language}) não é suportado pelo tradutor local.")
    tokenizer.src_lang = source_language

    model = M2M100ForConditionalGeneration.from_pretrained(
        TRANSLATION_MODEL,
        revision=TRANSLATION_MODEL_REVISION,
        cache_dir=TRANSLATION_MODEL_DIR,
        use_safetensors=True,
    )
    model.eval()
    translated_segments = []
    batch_size = 8
    try:
        for offset in range(0, len(segments), batch_size):
            batch = segments[offset:offset + batch_size]
            texts = [str(segment.get("text") or "").strip() for segment in batch]
            encoded = tokenizer(
                texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            with torch.inference_mode():
                generated = model.generate(
                    **encoded,
                    forced_bos_token_id=tokenizer.get_lang_id(target_language),
                    max_length=512,
                    num_beams=4,
                )
            translations = tokenizer.batch_decode(generated, skip_special_tokens=True)
            for segment, translated_text in zip(batch, translations):
                translated = dict(segment)
                translated["text"] = translated_text.strip()
                translated["words"] = rebuild_segment_words(
                    translated["text"],
                    float(segment.get("start", 0.0)),
                    float(segment.get("end", 0.0)),
                )
                translated_segments.append(translated)
            if progress_callback:
                completed = min(offset + len(batch), len(segments))
                progress_callback(completed, len(segments))
    finally:
        del model
        del tokenizer
        gc.collect()

    return translated_segments


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
