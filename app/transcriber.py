import gc
import os
import logging
from faster_whisper import WhisperModel
from whisperx_align import align_words_whisperx

logger = logging.getLogger("karaoke")

def resolve_whisper_repo(model_size: str) -> str:
    """Retorna o repositório oficial do HuggingFace para o modelo Whisper desejado."""
    m = model_size.lower().strip()
    if m == "large-v3-turbo":
        return "deepdml/faster-whisper-large-v3-turbo"
    elif m == "large-v3":
        return "Systran/faster-whisper-large-v3"
    elif m == "medium":
        return "Systran/faster-whisper-medium"
    elif m == "small":
        return "Systran/faster-whisper-small"
    elif m == "tiny":
        return "Systran/faster-whisper-tiny"
    return m

def get_model_local_dir(model_size: str) -> str:
    """Localiza o diretório local exato com os pesos do modelo Whisper."""
    key = model_size.lower().strip()
    min_size_bytes = 300 * 1024 * 1024  # 300 MB
    if "tiny" in key:
        min_size_bytes = 30 * 1024 * 1024
    elif "small" in key:
        min_size_bytes = 150 * 1024 * 1024

    if key == "large-v3-turbo":
        match_fn = lambda name: "turbo" in name or "large-v3-turbo" in name
    elif key == "large-v3":
        match_fn = lambda name: "large-v3" in name and "turbo" not in name
    elif key == "medium":
        match_fn = lambda name: "medium" in name
    elif key == "small":
        match_fn = lambda name: "small" in name
    elif key == "tiny" or key == "base":
        match_fn = lambda name: "tiny" in name or "base" in name
    else:
        match_fn = lambda name: key in name

    search_roots = [
        "/data/output/models/whisper",
        "/root/.cache/huggingface/hub",
        "/root/.cache/whisper",
        os.path.expanduser("~/.cache/huggingface/hub"),
        os.path.expanduser("~/.cache/whisper")
    ]

    for root in search_roots:
        if not os.path.exists(root):
            continue
        try:
            for entry in os.listdir(root):
                entry_path = os.path.join(root, entry)
                if os.path.isdir(entry_path) and match_fn(entry.lower()):
                    for r, dirs, files in os.walk(entry_path):
                        for f in files:
                            if f in ["model.bin", "model.safetensors", "pytorch_model.bin", "model.pt"]:
                                fpath = os.path.join(r, f)
                                try:
                                    if os.path.getsize(fpath) >= min_size_bytes:
                                        return r
                                except Exception:
                                    pass
        except Exception as e:
            logger.warning(f"Erro ao pesquisar diretório {root}: {e}")
    return None

def transcribe_vocals(
    vocals_path: str,
    model_size: str = "large-v3-turbo",
    initial_prompt: str = None,
    quality_mode: str = "standard",
    cpu_threads: int = None,
    enable_vad: bool = True
) -> list[dict]:
    """
    Sal0 Karaoke v4.3.0 - Transcrição de vocais com Faster-Whisper, Silero VAD e WhisperX.
    - Tenta primeiro carregar por caminho direto local sem chamadas de rede.
    - Se não encontrar no disco, baixa do repositório oficial HuggingFace.
    """
    if not cpu_threads or cpu_threads <= 0:
        total_cpus = os.cpu_count() or 4
        cpu_threads = max(1, total_cpus - 1)

    is_max_quality = (quality_mode == "max_quality" or "max" in str(quality_mode).lower())
    compute_type = "float32" if is_max_quality else "int8"
    beam_size = 10 if is_max_quality else 5

    logger.info(
        f"Configuração Faster-Whisper v4.3.0: Modelo={model_size}, "
        f"Threads={cpu_threads}, Compute={compute_type}, BeamSize={beam_size}, SileroVAD={enable_vad}"
    )

    repo_id = resolve_whisper_repo(model_size)
    save_dir = "/data/output/models/whisper"
    os.makedirs(save_dir, exist_ok=True)

    model = None

    # Etapa 1: Tentar carregar pelo caminho direto da pasta local contendo os pesos
    local_dir = get_model_local_dir(model_size)
    if local_dir:
        try:
            logger.info(f"Carregando modelo Whisper '{model_size}' do diretório local: {local_dir}")
            model = WhisperModel(
                local_dir,
                device="cpu",
                compute_type=compute_type,
                cpu_threads=cpu_threads
            )
        except Exception as e_local:
            logger.warning(f"Falha ao carregar diretamente do diretório {local_dir}: {e_local}")
            model = None

    # Etapa 2: Se não carregou do diretório local direto, tentar pelo repositório estrito local
    if model is None:
        try:
            logger.info(f"Tentando carregar '{repo_id}' via HuggingFace local...")
            model = WhisperModel(
                repo_id,
                device="cpu",
                compute_type=compute_type,
                cpu_threads=cpu_threads,
                download_root=save_dir,
                local_files_only=True
            )
        except Exception as ex_local_repo:
            logger.warning(f"O modelo '{repo_id}' não está completamente snapshot-cacheado no servidor ({ex_local_repo}). Baixando repositório oficial...")
            # Etapa 3: Baixar arquivos ausentes do repositório oficial do HuggingFace (local_files_only=False)
            try:
                model = WhisperModel(
                    repo_id,
                    device="cpu",
                    compute_type=compute_type,
                    cpu_threads=cpu_threads,
                    download_root=save_dir,
                    local_files_only=False
                )
                logger.info(f"Download do modelo '{repo_id}' concluído com sucesso e salvo em {save_dir}!")
            except Exception as ex_online:
                logger.error(f"Erro no download oficial de '{repo_id}': {ex_online}")
                # Etapa 4: Fallback final para medium
                if model_size != "medium":
                    logger.warning("Tentando fallback de emergência para o modelo 'medium'...")
                    med_dir = get_model_local_dir("medium")
                    if med_dir:
                        model = WhisperModel(med_dir, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
                    else:
                        model = WhisperModel("Systran/faster-whisper-medium", device="cpu", compute_type="int8", cpu_threads=cpu_threads, download_root=save_dir, local_files_only=False)
                else:
                    raise RuntimeError(f"Erro fatal ao baixar e carregar o modelo Whisper '{model_size}': {ex_online}")

    logger.info(f"Iniciando transcrição (Silero VAD={enable_vad}): {vocals_path}")
    try:
        if enable_vad:
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
        else:
            segments, info = model.transcribe(
                vocals_path,
                word_timestamps=True,
                beam_size=beam_size,
                initial_prompt=initial_prompt
            )
    except Exception as e_vad:
        logger.warning(f"Transcrição com Silero VAD retornou aviso ({e_vad}). Transcrevendo sem filtro VAD...")
        segments, info = model.transcribe(
            vocals_path,
            word_timestamps=True,
            beam_size=beam_size,
            initial_prompt=initial_prompt
        )

    logger.info(f"Idioma detectado: {info.language} ({info.language_probability:.2%})")

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
