import gc
import inspect
import os
import logging
import threading
from faster_whisper import WhisperModel
from runtime_resources import whisper_runtime_options
from whisper_models import get_model_local_dir, resolve_whisper_repo
from whisper_audio import load_whisper_audio
from whisperx_align import stabilize_word_timestamps
from lyric_guide import prepare_lyrics_guide

logger = logging.getLogger("karaoke")

TRANSCRIPTION_CACHE_VERSION = 4
_model_lock = threading.RLock()
_cached_model = None
_cached_model_key = None

TRANSCRIPTION_PRESETS = {
    "karaoke": {
        "label": "Karaokê equilibrado",
        "beam_size": 5,
        "patience": 1.0,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.75,
        "hallucination_silence_threshold": 2.0,
        "vad_parameters": {
            "min_silence_duration_ms": 1200,
            "speech_pad_ms": 800,
            "threshold": 0.25,
        },
    },
    "continuous": {
        "label": "Canto contínuo",
        "beam_size": 7,
        "patience": 1.2,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.85,
        "hallucination_silence_threshold": 3.0,
        "vad_parameters": {
            "min_silence_duration_ms": 1600,
            "speech_pad_ms": 1000,
            "threshold": 0.20,
        },
    },
    "difficult": {
        "label": "Voz difícil",
        "beam_size": 10,
        "patience": 1.5,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.90,
        "hallucination_silence_threshold": 3.0,
        "vad_parameters": {
            "min_silence_duration_ms": 1600,
            "speech_pad_ms": 1000,
            "threshold": 0.20,
        },
    },
    "fast": {
        "label": "Criação rápida",
        "beam_size": 3,
        "patience": 1.0,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.70,
        "hallucination_silence_threshold": 2.0,
        "vad_parameters": {
            "min_silence_duration_ms": 700,
            "speech_pad_ms": 500,
            "threshold": 0.35,
        },
    },
}


def _prepare_lyrics_hint(lyrics: str, max_chars: int = 1200) -> str | None:
    """Converte a letra em vocabulário curto para orientar sem ditar a música."""
    if not lyrics or not lyrics.strip():
        return None

    unique_words = []
    seen = set()
    for token in lyrics.replace("\r", " ").replace("\n", " ").split():
        clean = token.strip()
        key = clean.casefold().strip(".,!?;:()[]{}\"'")
        if not key or key in seen:
            continue
        seen.add(key)
        unique_words.append(clean)
        if len(" ".join(unique_words)) >= max_chars:
            break
    return " ".join(unique_words)[:max_chars] or None

def clear_cached_model():
    """Cede RAM/VRAM ao separador de vocais antes de iniciar a próxima música."""
    global _cached_model, _cached_model_key
    with _model_lock:
        _cached_model = None
        _cached_model_key = None
        gc.collect()


def _device_error(error):
    return any(term in str(error).lower() for term in (
        "cuda", "cublas", "cudnn", "nvidia", "out of memory", "float16", "compute type",
        "memory allocation", "failed to allocate", "not enough memory",
    ))


def _load_selected_model(model_size, runtime):
    global _cached_model, _cached_model_key
    key = (resolve_whisper_repo(model_size), tuple(sorted(runtime.items())))
    with _model_lock:
        if _cached_model is not None and _cached_model_key == key:
            logger.info("Reutilizando o mesmo Whisper %s para a revisão da voz.", model_size)
            return _cached_model
        clear_cached_model()
        save_dir = "/data/output/models/whisper"
        os.makedirs(save_dir, exist_ok=True)
        local_dir = get_model_local_dir(model_size)
        model = None
        if local_dir:
            try:
                model = WhisperModel(local_dir, **runtime)
            except InterruptedError:
                raise
            except Exception as error:
                if _device_error(error):
                    raise
                logger.warning("Cache Whisper não pôde ser carregado em %s: %s", local_dir, error)
        if model is None:
            repo = resolve_whisper_repo(model_size)
            try:
                model = WhisperModel(repo, download_root=save_dir, local_files_only=True, **runtime)
            except InterruptedError:
                raise
            except Exception as error:
                if _device_error(error):
                    raise
                logger.info("Obtendo arquivos ausentes do modelo selecionado %s: %s", repo, error)
                # Preservar a escolha do usuário: uma falha nunca troca para medium.
                model = WhisperModel(repo, download_root=save_dir, local_files_only=False, **runtime)
        _cached_model, _cached_model_key = model, key
        return model


def _fit_guidance(model, phrase_context, lyrics_hint):
    """Reserve tokens para a voz; Faster-Whisper soma prompt e hotwords."""
    tokenizer = getattr(model, "hf_tokenizer", None)
    if tokenizer is None:
        return phrase_context, lyrics_hint
    budget = max(1, int(getattr(model, "max_length", 448)) // 2 - 8)

    def encode(text):
        return tokenizer.encode(" " + text, add_special_tokens=False).ids if text else []

    def bounded(text, limit):
        tokens = encode(text)
        if len(tokens) <= limit:
            return text, len(tokens)
        # Um token pode terminar no meio de um caractere UTF-8. Retirar a
        # substituição e recontar evita dicas corrompidas ou um novo overflow.
        text = tokenizer.decode(tokens[:limit]).strip().rstrip("\ufffd")
        while text and len(encode(text)) > limit:
            text = text[:-1].rstrip()
        return text or None, len(encode(text))

    context_budget = budget // 2 if lyrics_hint else budget
    phrase_context, context_count = bounded(phrase_context, context_budget)
    lyrics_hint, _ = bounded(lyrics_hint, budget - context_count)
    return phrase_context, lyrics_hint


def _compatible_options(model, options):
    # language_detection_segments surgiu após algumas versões ainda aceitas
    # pelo requirements; não remover silenciosamente opções já estabelecidas.
    parameters = inspect.signature(model.transcribe).parameters
    if any(value.kind == inspect.Parameter.VAR_KEYWORD for value in parameters.values()):
        return options
    return {key: value for key, value in options.items()
            if key not in {"language_detection_segments", "language_detection_threshold"} or key in parameters}

def transcribe_vocals(
    vocals_path: str,
    model_size: str = "large-v3-turbo",
    initial_prompt: str = None,
    quality_mode: str = "standard",
    cpu_threads: int = None,
    enable_vad: bool = False,
    transcription_preset: str = "karaoke",
    task: str = "transcribe",
    return_info: bool = False,
    progress_callback=None,
    guidance_retry: bool = False,
    guide_vocabulary: str = None,
) -> list[dict] | tuple[list[dict], dict]:
    """
    Transcrição local de vocais com Faster-Whisper e ajustes próprios para canto.
    - Tenta primeiro carregar por caminho direto local sem chamadas de rede.
    - Se não encontrar no disco, baixa do repositório oficial HuggingFace.
    """
    preset = TRANSCRIPTION_PRESETS.get(transcription_preset, TRANSCRIPTION_PRESETS["karaoke"])
    transcription_preset = transcription_preset if transcription_preset in TRANSCRIPTION_PRESETS else "karaoke"
    is_max_quality = (quality_mode == "max_quality" or "max" in str(quality_mode).lower())
    runtime = whisper_runtime_options(quality_mode=quality_mode, cpu_threads=cpu_threads)
    beam_size = max(preset["beam_size"], 10 if is_max_quality else 0)
    guide = prepare_lyrics_guide(initial_prompt)
    lyrics_hint = _prepare_lyrics_hint(prepare_lyrics_guide(guide_vocabulary) or guide)
    phrase_context = " ".join(guide.split())[:800] or None
    if guidance_retry:
        beam_size = max(beam_size, 15)

    logger.info(
        f"Configuração Faster-Whisper: Modelo={model_size}, Perfil={transcription_preset}, "
        f"Runtime={runtime}, BeamSize={beam_size}, SileroVAD={enable_vad}"
    )

    audio = load_whisper_audio(vocals_path)

    try:
        model = _load_selected_model(model_size, runtime)
    except InterruptedError:
        raise
    except Exception as error:
        if runtime["device"] != "cuda" or not _device_error(error):
            raise
        logger.warning("GPU indisponível (%s); mantendo Whisper %s na CPU.", error, model_size)
        runtime = whisper_runtime_options(quality_mode=quality_mode, cpu_threads=cpu_threads, device="cpu")
        model = _load_selected_model(model_size, runtime)

    phrase_context, lyrics_hint = _fit_guidance(model, phrase_context, lyrics_hint)

    logger.info(f"Iniciando transcrição (Silero VAD={enable_vad}): {vocals_path}")
    transcribe_options = {
        "task": "translate" if task == "translate" else "transcribe",
        "word_timestamps": True,
        "beam_size": beam_size,
        "patience": max(preset["patience"], 2.0) if guidance_retry else preset["patience"],
        "condition_on_previous_text": preset["condition_on_previous_text"],
        "no_speech_threshold": preset["no_speech_threshold"],
        "hallucination_silence_threshold": preset["hallucination_silence_threshold"],
        "initial_prompt": phrase_context,
        "hotwords": lyrics_hint,
        # O início pode ser instrumental. Conferir até três janelas quando o
        # primeiro idioma é incerto, sem impor português à música.
        "language_detection_threshold": 0.7,
        "language_detection_segments": 3,
    }
    if enable_vad:
        transcribe_options.update({
            "vad_filter": True,
            "vad_parameters": dict(preset["vad_parameters"]),
        })
    transcribe_options = _compatible_options(model, transcribe_options)

    def consume_segments(segment_iterator, transcription_info):
        collected = []
        total_duration = float(
            getattr(transcription_info, "duration", 0.0)
            or getattr(transcription_info, "duration_after_vad", 0.0)
            or 0.0
        )
        last_percent = -1
        for segment in segment_iterator:
            collected.append(segment)
            segment_end = float(getattr(segment, "end", 0.0) or 0.0)
            percent = min(99, max(0, int((segment_end / total_duration) * 100))) if total_duration else 0
            if progress_callback and percent != last_percent:
                try:
                    progress_callback(percent, segment_end, total_duration)
                except InterruptedError:
                    raise
                except Exception as callback_error:
                    logger.debug("Falha ao publicar progresso do Whisper: %s", callback_error)
            last_percent = percent
        if progress_callback:
            try:
                progress_callback(100, total_duration, total_duration)
            except InterruptedError:
                raise
            except Exception as callback_error:
                logger.debug("Falha ao publicar conclusão do Whisper: %s", callback_error)
        return collected

    def run_transcription():
        try:
            segments, info = model.transcribe(audio, **transcribe_options)
            segments = consume_segments(segments, info)
            if transcribe_options.get("vad_filter") and not any(segment.words for segment in segments):
                logger.info("VAD sem palavras; conferindo a faixa completa uma vez.")
                transcribe_options.pop("vad_parameters", None)
                transcribe_options["vad_filter"] = False
                segments, info = model.transcribe(audio, **transcribe_options)
                segments = consume_segments(segments, info)
            return segments, info
        except InterruptedError:
            raise
        except Exception as e_vad:
            if not transcribe_options.get("vad_filter") or (runtime["device"] == "cuda" and _device_error(e_vad)):
                raise
            logger.warning(f"Transcrição com Silero VAD retornou aviso ({e_vad}). Transcrevendo sem filtro VAD...")
            transcribe_options["vad_filter"] = False
            transcribe_options.pop("vad_parameters", None)
            segments, info = model.transcribe(audio, **transcribe_options)
            segments = consume_segments(segments, info)
            return segments, info

    try:
        try:
            segments, info = run_transcription()
        except InterruptedError:
            raise
        except Exception as error:
            if runtime["device"] != "cuda" or not _device_error(error):
                raise
            logger.warning("GPU falhou durante inferência (%s); repetindo o mesmo modelo na CPU.", error)
            clear_cached_model()
            model = None
            gc.collect()
            runtime = whisper_runtime_options(quality_mode=quality_mode, cpu_threads=cpu_threads, device="cpu")
            model = _load_selected_model(model_size, runtime)
            segments, info = run_transcription()
    finally:
        del model
        gc.collect()

    logger.info(f"Idioma detectado: {info.language} ({info.language_probability:.2%})")

    structured_segments = []
    for segment in segments:
        segment_words = []
        if segment.words:
            for word in segment.words:
                segment_words.append({
                    "word": word.word,
                    "start": word.start,
                    "end": word.end,
                    **({"probability": word.probability} if getattr(word, "probability", None) is not None else {}),
                })
        if segment_words:
            structured_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": segment_words
            })

    logger.info(f"Transcrição concluída. Segmentos obtidos: {len(structured_segments)}")
    if structured_segments:
        try:
            logger.info("Estabilizando timestamps de palavras sem alterar o alinhamento do áudio...")
            structured_segments = stabilize_word_timestamps(structured_segments, audio_duration=audio.size / 16000)
        except Exception as e_align:
            logger.warning(f"Aviso ao estabilizar timestamps: {e_align}")

    transcription_info = {
        "language": str(getattr(info, "language", "") or "").strip().lower(),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "task": "translate" if task == "translate" else "transcribe",
    }
    if return_info:
        return structured_segments, transcription_info
    return structured_segments
