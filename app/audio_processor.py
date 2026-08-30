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

def separate_vocals(audio_path: str, temp_output_dir: str, update_callback=None) -> tuple[str, str]:
    """Separa vocais com o htdemucs_ft e repete em blocos menores se necessário."""
    logger.info("Iniciando a separação de vocais com Demucs para: %s", audio_path)
    audio_stem = Path(audio_path).stem
    import process_manager as pm
    pm.check_cancelled()

    env = os.environ.copy()
    env["TORCH_HOME"] = "/data/output/models/torch"
    env["HF_HOME"] = "/data/output/models/huggingface"
    env["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
    attempts = [
        {"model": "htdemucs_ft", "segment": None},
        {"model": "htdemucs_ft", "segment": "5"},
    ]
    failure_summaries = []

    try:
        for attempt_index, attempt in enumerate(attempts):
            model_name = attempt["model"]
            total_passes = 1
            runner_path = Path(__file__).with_name("demucs_runner.py")
            cmd = [
                sys.executable,
                str(runner_path),
                audio_path,
                "--output", temp_output_dir,
                "--model", model_name,
            ]
            if attempt["segment"]:
                cmd.extend(["--segment", attempt["segment"]])

            if attempt_index and update_callback:
                update_callback(
                    "processing",
                    "Repetindo separação de vocais",
                    20,
                    stage_progress=0,
                    stage_detail="Repetindo o mesmo modelo de alta precisão em blocos menores",
                )

            logger.info("Executando Demucs (%s): %s", model_name, " ".join(cmd))
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            pm.set_active_process(process)
            recent_output = deque(maxlen=18)
            current_pass = 0
            last_raw_pct = None
            best_stage_pct = 0

            for line in process.stdout:
                if pm.cancel_event.is_set():
                    process.terminate()
                    break
                line_str = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", line.strip())
                if not line_str:
                    continue
                recent_output.append(line_str)
                logger.info("[Demucs:%s] %s", model_name, line_str)
                if not update_callback:
                    continue
                if "downloading" in line_str.lower() or "download" in line_str.lower():
                    update_callback(
                        "processing",
                        "Preparando separador de vocais",
                        20,
                        stage_progress=0,
                        stage_detail="Baixando o modelo local do Demucs (somente na primeira vez)",
                    )
                percentages = re.findall(r"(?<!\d)(100|[1-9]?\d)%", line_str)
                if not percentages:
                    continue
                raw_pct = int(percentages[-1])
                if (
                    last_raw_pct is not None
                    and last_raw_pct >= 90
                    and raw_pct <= 15
                    and current_pass < total_passes - 1
                ):
                    current_pass += 1
                aggregate_pct = round(((current_pass + (raw_pct / 100)) / total_passes) * 100)
                aggregate_pct = max(best_stage_pct, min(99, aggregate_pct))
                best_stage_pct = aggregate_pct
                update_callback(
                    "processing",
                    "Separando vocais do áudio",
                    20 + round(aggregate_pct * 0.35),
                    stage_progress=aggregate_pct,
                    stage_detail=(
                        f"Modelo de alta precisão · {raw_pct}% da separação"
                    ),
                )
                last_raw_pct = raw_pct

            process.wait()
            pm.clear_active_process()
            pm.check_cancelled()

            output_folder = Path(temp_output_dir) / model_name / audio_stem
            vocals_path = output_folder / "vocals.wav"
            instrumental_path = output_folder / "no_vocals.wav"
            if process.returncode == 0 and vocals_path.exists() and instrumental_path.exists():
                if update_callback:
                    update_callback(
                        "processing",
                        "Vocais separados com sucesso",
                        55,
                        stage_progress=100,
                        stage_detail=f"Separação concluída com {model_name}",
                    )
                logger.info("Separação do Demucs concluída com sucesso usando %s.", model_name)
                return str(vocals_path), str(instrumental_path)

            detail = " | ".join(recent_output) or "nenhuma saída de diagnóstico"
            detail = detail[-1200:]
            failure_summaries.append(f"{model_name} (código {process.returncode}): {detail}")
            logger.warning("Demucs %s falhou; preparando tentativa alternativa. %s", model_name, detail)

        raise RuntimeError(
            "A separação de vocais falhou nos dois modelos. "
            + " || ".join(failure_summaries)
        )
    except InterruptedError:
        pm.clear_active_process()
        raise
    except Exception as e:
        pm.clear_active_process()
        logger.exception("Erro ao executar o Demucs.")
        raise RuntimeError(f"Demucs falhou: {e}") from e
