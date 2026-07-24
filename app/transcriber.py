import gc
import os
import logging
from faster_whisper import WhisperModel
from whisperx_align import stabilize_word_timestamps

logger = logging.getLogger("karaoke")

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
    enable_vad: bool = False,
    transcription_preset: str = "karaoke",
) -> list[dict]:
    """
    Transcrição local de vocais com Faster-Whisper e ajustes próprios para canto.
    - Tenta primeiro carregar por caminho direto local sem chamadas de rede.
    - Se não encontrar no disco, baixa do repositório oficial HuggingFace.
    """
    if not cpu_threads or cpu_threads <= 0:
        total_cpus = os.cpu_count() or 4
        cpu_threads = max(1, total_cpus - 1)

    preset = TRANSCRIPTION_PRESETS.get(transcription_preset, TRANSCRIPTION_PRESETS["karaoke"])
    transcription_preset = transcription_preset if transcription_preset in TRANSCRIPTION_PRESETS else "karaoke"
    is_max_quality = (quality_mode == "max_quality" or "max" in str(quality_mode).lower())
    compute_type = "float32" if is_max_quality else "int8"
    beam_size = max(preset["beam_size"], 10 if is_max_quality else 0)
    lyrics_hint = _prepare_lyrics_hint(initial_prompt)

    logger.info(
        f"Configuração Faster-Whisper: Modelo={model_size}, Perfil={transcription_preset}, "
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
    transcribe_options = {
        "word_timestamps": True,
        "beam_size": beam_size,
        "patience": preset["patience"],
        "condition_on_previous_text": preset["condition_on_previous_text"],
        "no_speech_threshold": preset["no_speech_threshold"],
        "hallucination_silence_threshold": preset["hallucination_silence_threshold"],
        "hotwords": lyrics_hint,
    }
    if enable_vad:
        transcribe_options.update({
            "vad_filter": True,
            "vad_parameters": dict(preset["vad_parameters"]),
        })

    try:
        segments, info = model.transcribe(vocals_path, **transcribe_options)
        segments = list(segments)
    except Exception as e_vad:
        if not enable_vad:
            raise
        logger.warning(f"Transcrição com Silero VAD retornou aviso ({e_vad}). Transcrevendo sem filtro VAD...")
        transcribe_options.pop("vad_filter", None)
        transcribe_options.pop("vad_parameters", None)
        segments, info = model.transcribe(vocals_path, **transcribe_options)
        segments = list(segments)

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
            logger.info("Estabilizando timestamps de palavras sem alterar o alinhamento do áudio...")
            structured_segments = stabilize_word_timestamps(structured_segments)
        except Exception as e_align:
            logger.warning(f"Aviso ao estabilizar timestamps: {e_align}")

    return structured_segments
