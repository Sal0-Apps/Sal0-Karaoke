import os
import subprocess
import logging
import re
import sys
from collections import deque
from pathlib import Path

logger = logging.getLogger("karaoke")

def get_file_duration(file_path: str) -> float:
    """Retorna a duração do arquivo de áudio/vídeo em segundos usando ffprobe."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.error(f"Erro ao obter duração do arquivo {file_path}: {e}")
        return 0.0

def extract_audio(input_path: str, output_wav_path: str) -> str:
    """Extrai ou converte o áudio do arquivo de entrada para um WAV estéreo de 44.1kHz 16-bit."""
    logger.info(f"Iniciando extração/conversão de áudio do arquivo: {input_path}")
    
    # Comando FFmpeg para extrair apenas áudio e converter para WAV 16-bit 44.1kHz estéreo
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vn",                   # Sem vídeo
        "-acodec", "pcm_s16le",  # PCM 16-bit
        "-ar", "44100",          # Taxa de amostragem 44.1kHz
        "-ac", "2",              # Estéreo
        output_wav_path
    ]
    
    import process_manager as pm
    pm.check_cancelled()
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        pm.set_active_process(process)
        stdout, stderr = process.communicate()
        pm.clear_active_process()
        pm.check_cancelled()
        
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg falhou: {stderr}")
            
        logger.info("Extração de áudio concluída com sucesso via FFmpeg.")
        return output_wav_path
    except Exception as e:
        pm.clear_active_process()
        logger.error(f"Erro no FFmpeg ao extrair áudio: {e}")
        raise


def extract_audio_mp3(input_path: str, output_mp3_path: str) -> str:
    """Normaliza a primeira faixa de áudio de qualquer mídia compatível para MP3."""
    logger.info("Normalizando mídia para MP3: %s", input_path)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-map", "0:a:0",
        "-vn",
        "-codec:a", "libmp3lame",
        "-q:a", "2",
        "-ar", "44100",
        "-ac", "2",
        output_mp3_path,
    ]

    import process_manager as pm
    pm.check_cancelled()
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        pm.set_active_process(process)
        _, stderr = process.communicate()
        pm.clear_active_process()
        pm.check_cancelled()
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg não encontrou uma faixa de áudio utilizável: {stderr}")
        logger.info("Mídia normalizada para MP3 com sucesso: %s", output_mp3_path)
        return output_mp3_path
    except Exception:
        pm.clear_active_process()
        logger.exception("Falha ao normalizar mídia para MP3.")
        raise

def combine_demucs_stems(input_paths: list[Path], output_path: Path) -> None:
    """Soma stems float em blocos e grava PCM sem manter a faixa inteira na memória."""
    import numpy as np
    import soundfile as sf

    if not input_paths:
        raise ValueError("Nenhum stem foi informado para combinação.")

    readers = [sf.SoundFile(str(path), mode="r") for path in input_paths]
    try:
        reference = readers[0]
        for reader in readers[1:]:
            if (
                reader.samplerate != reference.samplerate
                or reader.channels != reference.channels
                or reader.frames != reference.frames
            ):
                raise RuntimeError("Os stems especializados do Demucs são incompatíveis entre si.")

        block_size = 262144
        peak = 0.0
        while True:
            blocks = [reader.read(block_size, dtype="float32", always_2d=True) for reader in readers]
            if not len(blocks[0]):
                break
            mixed = np.sum(blocks, axis=0, dtype=np.float32)
            peak = max(peak, float(np.max(np.abs(mixed), initial=0.0)))

        scale = 0.99 / peak if peak > 0.99 else 1.0
        for reader in readers:
            reader.seek(0)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with sf.SoundFile(
            str(output_path),
            mode="w",
            samplerate=reference.samplerate,
            channels=reference.channels,
            subtype="PCM_16",
        ) as writer:
            while True:
                blocks = [reader.read(block_size, dtype="float32", always_2d=True) for reader in readers]
                if not len(blocks[0]):
                    break
                mixed = np.sum(blocks, axis=0, dtype=np.float32)
                writer.write(mixed * scale)
    finally:
        for reader in readers:
            reader.close()


def separate_vocals(audio_path: str, temp_output_dir: str, update_callback=None) -> tuple[str, str]:
    """Executa sequencialmente os quatro modelos especializados do htdemucs_ft."""
    logger.info("Iniciando a separação de vocais com Demucs para: %s", audio_path)
    audio_stem = Path(audio_path).stem
    import process_manager as pm
    pm.check_cancelled()

    env = os.environ.copy()
    env["TORCH_HOME"] = "/data/output/models/torch"
    env["HF_HOME"] = "/data/output/models/huggingface"
    env["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
    specialized_models = [
        ("f7e0c4bc", "drums"),
        ("d12395a8", "bass"),
        ("92cfc3b6", "other"),
        ("04573f0d", "vocals"),
    ]
    failure_summaries = []

    try:
        completed_stems = {}
        for model_index, (model_name, target_stem) in enumerate(specialized_models):
            runner_path = Path(__file__).with_name("demucs_runner.py")
            if update_callback:
                update_callback(
                    "processing",
                    "Separando vocais do áudio",
                    20 + round((model_index / len(specialized_models)) * 35),
                    stage_progress=0,
                    stage_detail=(
                        f"Análise especializada {model_index + 1} de {len(specialized_models)} · "
                        f"preparando {target_stem}"
                    ),
                )

            model_succeeded = False
            for segment in (None, "5"):
                cmd = [
                    sys.executable,
                    str(runner_path),
                    audio_path,
                    "--output", temp_output_dir,
                    "--model", model_name,
                    "--target-stem", target_stem,
                ]
                if segment:
                    cmd.extend(["--segment", segment])
                    if update_callback:
                        update_callback(
                            "processing",
                            "Repetindo análise especializada",
                            20 + round((model_index / len(specialized_models)) * 35),
                            stage_progress=round((model_index / len(specialized_models)) * 100),
                            stage_detail=(
                                f"Análise {model_index + 1} de {len(specialized_models)} · "
                                "nova tentativa em blocos menores"
                            ),
                        )

                logger.info("Executando Demucs (%s/%s): %s", model_name, target_stem, " ".join(cmd))
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
                pm.set_active_process(process)
                recent_output = deque(maxlen=18)

                for line in process.stdout:
                    if pm.cancel_event.is_set():
                        process.terminate()
                        break
                    line_str = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", line.strip())
                    if not line_str:
                        continue
                    recent_output.append(line_str)
                    logger.info("[Demucs:%s/%s] %s", model_name, target_stem, line_str)
                    progress_match = re.search(r"DEMUCS_PROGRESS\s+(100|[1-9]?\d)%", line_str)
                    if not progress_match or not update_callback:
                        continue
                    raw_pct = int(progress_match.group(1))
                    aggregate_pct = min(
                        99,
                        round(((model_index + (raw_pct / 100)) / len(specialized_models)) * 100),
                    )
                    update_callback(
                        "processing",
                        "Separando vocais do áudio",
                        20 + round(aggregate_pct * 0.35),
                        stage_progress=aggregate_pct,
                        stage_detail=(
                            f"Análise especializada {model_index + 1} de {len(specialized_models)} · "
                            f"{raw_pct}% desta análise"
                        ),
                    )

                process.wait()
                pm.clear_active_process()
                pm.check_cancelled()
                target_path = Path(temp_output_dir) / model_name / audio_stem / f"{target_stem}.wav"
                if process.returncode == 0 and target_path.exists():
                    completed_stems[target_stem] = target_path
                    model_succeeded = True
                    break

                detail = " | ".join(recent_output) or "nenhuma saída de diagnóstico"
                failure_summaries.append(
                    f"{model_name}/{target_stem} (código {process.returncode}): {detail[-1200:]}"
                )
                logger.warning("Análise Demucs %s/%s falhou. %s", model_name, target_stem, detail)

            if not model_succeeded:
                raise RuntimeError(
                    f"A análise especializada de {target_stem} falhou. " + " || ".join(failure_summaries)
                )

        output_folder = Path(temp_output_dir) / "htdemucs_ft" / audio_stem
        vocals_path = output_folder / "vocals.wav"
        instrumental_path = output_folder / "no_vocals.wav"
        combine_demucs_stems([completed_stems["vocals"]], vocals_path)
        combine_demucs_stems(
            [completed_stems["drums"], completed_stems["bass"], completed_stems["other"]],
            instrumental_path,
        )
        if update_callback:
            update_callback(
                "processing",
                "Vocais separados com sucesso",
                55,
                stage_progress=100,
                stage_detail="Quatro análises especializadas de alta precisão concluídas",
            )
        return str(vocals_path), str(instrumental_path)
    except InterruptedError:
        pm.clear_active_process()
        raise
    except Exception as e:
        pm.clear_active_process()
        logger.exception("Erro ao executar o Demucs.")
        raise RuntimeError(f"Demucs falhou: {e}") from e
