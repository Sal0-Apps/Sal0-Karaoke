import gc
import os
import logging
from faster_whisper import WhisperModel
from whisperx_align import align_words_whisperx

logger = logging.getLogger("karaoke")

def transcribe_vocals(
    vocals_path: str,
    model_size: str = "large-v3-turbo",
    initial_prompt: str = None,
    quality_mode: str = "standard",
    cpu_threads: int = None
) -> list[dict]:
    """
    Sal0 Karaoke v4.0.0 - Transcrição de vocais com Faster-Whisper, Silero VAD e WhisperX.
    - CPU Threads: Auto-calculado max(1, os.cpu_count() - 1)
    - Compute Type: 'int8' (padrão) ou 'float32' (máxima qualidade)
    - Beam Size: 5 (padrão) ou 10 (máxima qualidade)
    - Silero VAD: Ativado via vad_filter=True
    - WhisperX Alignment: Refinamento por palavra 100% offline
    """
    if not cpu_threads or cpu_threads <= 0:
        total_cpus = os.cpu_count() or 4
        cpu_threads = max(1, total_cpus - 1)

    is_max_quality = (quality_mode == "max_quality" or "max" in str(quality_mode).lower())
    compute_type = "float32" if is_max_quality else "int8"
    beam_size = 10 if is_max_quality else 5

    logger.info(
        f"Configuração Faster-Whisper v4.0.0: Modelo={model_size}, "
        f"Threads={cpu_threads}, Compute={compute_type}, BeamSize={beam_size}"
    )

    repo_id = model_size
    if model_size == "large-v3-turbo":
        repo_id = "deepdml/faster-whisper-large-v3-turbo"
    elif model_size == "large-v3":
        repo_id = "Systran/faster-whisper-large-v3"
    elif model_size == "medium":
        repo_id = "Systran/faster-whisper-medium"
    elif model_size == "small":
        repo_id = "Systran/faster-whisper-small"
    elif model_size == "tiny":
        repo_id = "Systran/faster-whisper-tiny"

    save_dir = "/data/output/models/whisper"

    try:
        model = WhisperModel(
            repo_id,
            device="cpu",
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            download_root=save_dir,
            local_files_only=True
        )
    except Exception as ex:
        logger.warning(f"Aviso ao carregar '{repo_id}' ({ex}). Tentando fallback para modelo 'medium'...")
        try:
            model = WhisperModel(
                "medium",
                device="cpu",
                compute_type="int8",
                cpu_threads=cpu_threads,
                download_root=save_dir,
                local_files_only=True
            )
        except Exception as ex2:
            logger.error(f"Erro ao carregar o modelo Whisper {model_size}: {ex2}")
            raise RuntimeError(
                f"O modelo Whisper '{model_size}' não está baixado no servidor. "
                "Por favor, acesse o painel 'Configurações Avançadas' -> 'Gerenciador de Modelos de IA' e baixe o modelo antes de prosseguir."
            )

    logger.info(f"Iniciando transcrição com Silero VAD: {vocals_path}")
    try:
        segments, info = model.transcribe(
            vocals_path,
            word_timestamps=True,
            beam_size=beam_size,
            initial_prompt=initial_prompt,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=400,
                threshold=0.5
            )
        )
    except Exception as e_vad:
        logger.warning(f"Silero VAD retornou aviso ({e_vad}). Transcrevendo sem filtro VAD...")
        segments, info = model.transcribe(
            vocals_path,
            word_timestamps=True,
            beam_size=beam_size,
            initial_prompt=initial_prompt
        )

    logger.info(f"Idioma: {info.language} ({info.language_probability:.2%})")

    structured_segments = []
    for segment in segments:
        segment_words = []
        if segment.words:
            for word in segment.words:
                segment_words.append({
                    "word": word.word,
                    "start": word.start,
                    "end": word.end
                })
        if segment_words:
            structured_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": segment_words
            })

    logger.info(f"Transcrição concluída. Segmentos obtidos: {len(structured_segments)}")
    del model
    gc.collect()

    if structured_segments:
        try:
            logger.info("Aplicando alinhamento WhisperX por palavra...")
            structured_segments = align_words_whisperx(vocals_path, structured_segments)
        except Exception as e_align:
            logger.warning(f"Aviso no alinhamento WhisperX: {e_align}")

    return structured_segments
