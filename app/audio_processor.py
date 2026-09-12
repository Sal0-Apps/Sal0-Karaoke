import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("karaoke")


def get_effective_cpu_count() -> int:
    """Retorna a quantidade de CPUs realmente disponível para o processo.

    Em containers, ``os.cpu_count()`` pode informar os CPUs do host mesmo
    quando o processo recebeu uma cota menor. Consideramos afinidade e cotas
    do cgroup para evitar tanto subutilização quanto excesso de threads.
    """
    candidates = []

    if hasattr(os, "sched_getaffinity"):
        try:
            affinity_count = len(os.sched_getaffinity(0))
            if affinity_count > 0:
                candidates.append(affinity_count)
        except (OSError, AttributeError):
            pass

    host_count = os.cpu_count()
    if host_count:
        candidates.append(host_count)

    cgroup_limits = (
        ("/sys/fs/cgroup/cpu.max", None),
        ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "/sys/fs/cgroup/cpu/cpu.cfs_period_us"),
    )
    for quota_path, period_path in cgroup_limits:
        try:
            quota_parts = Path(quota_path).read_text(encoding="utf-8").strip().split()
            if not quota_parts or quota_parts[0] == "max":
                continue
            quota = int(quota_parts[0])
            if period_path:
                period = int(Path(period_path).read_text(encoding="utf-8").strip())
            else:
                period = int(quota_parts[1])
            if quota > 0 and period > 0:
                candidates.append((quota + period - 1) // period)
                break
        except (OSError, IndexError, ValueError):
            continue

    return max(1, min(candidates)) if candidates else 1

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
        stdout, stderr = process.communicate()
        pm.clear_active_process()
        pm.check_cancelled()
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg não encontrou uma faixa de áudio utilizável: {stderr}")
        logger.info("Mídia normalizada para MP3 com sucesso: %s", output_mp3_path)
        return output_mp3_path
    except Exception as e:
        pm.clear_active_process()
        logger.error(f"Erro no FFmpeg ao extrair MP3: {e}")
        raise

def separate_vocals(audio_path: str, temp_output_dir: str, update_callback=None) -> tuple[str, str]:
    """Usa Demucs em modo CPU para separar o áudio em vocais e instrumental (no_vocals)."""
    logger.info(f"Iniciando a separação de vocais com Demucs para: {audio_path}")
    
    # Nome base do arquivo de áudio para localizar o diretório de saída do Demucs
    audio_stem = Path(audio_path).stem
    
    # Modelo htdemucs_ft de máxima precisão (conjunto de 4 modelos)
    model_name = "htdemucs_ft"
    
    cmd = [
        "demucs",
        "-d", "cpu",
        "-n", "htdemucs_ft",
        "--two-stems", "vocals",
        # Um único arquivo não precisa de vários workers de segmentos. O
        # padrão 0 mantém o caminho de alta precisão e deixa o PyTorch usar
        # as threads de CPU configuradas abaixo, como no CLI original.
        "--jobs", "0",
        "-o", temp_output_dir,
        audio_path
    ]
    
    import process_manager as pm
    pm.check_cancelled()
    try:
        # Configurar variáveis de ambiente para salvar modelos do PyTorch/Demucs no disco persistente
        env = os.environ.copy()
        env["TORCH_HOME"] = "/data/output/models/torch"
        env["HF_HOME"] = "/data/output/models/huggingface"
        env["TORCHAUDIO_BACKEND"] = "soundfile"
        env["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"

        cpu_count = get_effective_cpu_count()
        configured_threads = os.environ.get("DEMUCS_CPU_THREADS", "").strip()
        try:
            cpu_threads = int(configured_threads) if configured_threads else cpu_count
        except ValueError:
            cpu_threads = cpu_count
        cpu_threads = max(1, min(cpu_threads, cpu_count))
        # --jobs controla workers internos do Demucs, não a quantidade de
        # threads de CPU. Para uma única entrada, jobs=0 evita o caminho que
        # dividia o trabalho e acabava deixando a CPU quase ociosa.
        cmd[cmd.index("--jobs") + 1] = "0"
        env["OMP_NUM_THREADS"] = str(cpu_threads)
        env["MKL_NUM_THREADS"] = str(cpu_threads)
        env["OPENBLAS_NUM_THREADS"] = str(cpu_threads)
        env["NUMEXPR_NUM_THREADS"] = str(cpu_threads)
        env["OMP_DYNAMIC"] = "FALSE"
        env["MKL_DYNAMIC"] = "FALSE"
        logger.info(
            "Demucs CPU configurado com %s thread(s) disponível(is); jobs internos: 0",
            cpu_threads,
        )
        
        # Executar o Demucs com streaming de logs em tempo real
        logger.info(f"Executando Demucs: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        pm.set_active_process(process)
        cancelled_during_demucs = False

        # O htdemucs_ft é um conjunto de quatro análises. Cada uma informa
        # 0–100%, portanto o valor bruto reinicia várias vezes. Agregamos os
        # ciclos para que o progresso geral nunca volte para trás.
        total_passes = 4
        current_pass = 0
        last_raw_pct = None
        best_stage_pct = 0

        import re
        for line in process.stdout:
            if pm.cancel_event.is_set():
                process.terminate()
                cancelled_during_demucs = True
                break
            line_str = line.strip()
            if line_str:
                logger.info(f"[Demucs] {line_str}")
                if update_callback:
                    if "downloading" in line_str.lower() or "download" in line_str.lower():
                        update_callback(
                            "processing",
                            "Preparando separador de vocais",
                            20,
                            stage_detail="Baixando o modelo local do Demucs (somente na primeira vez)"
                        )
                    percentages = re.findall(r'(?<!\d)(100|[1-9]?\d)%', line_str)
                    if percentages:
                        raw_pct = int(percentages[-1])
                        if (
                            last_raw_pct is not None
                            and last_raw_pct >= 90
                            and raw_pct <= 15
                            and current_pass < total_passes - 1
                        ):
                            current_pass += 1

                        aggregate_pct = round(
                            ((current_pass + (raw_pct / 100)) / total_passes) * 100
                        )
                        aggregate_pct = max(best_stage_pct, min(99, aggregate_pct))
                        best_stage_pct = aggregate_pct
                        overall_pct = 20 + round(aggregate_pct * 0.35)
                        update_callback(
                            "processing",
                            "Separando vocais do áudio",
                            overall_pct,
                            stage_progress=aggregate_pct,
                            stage_detail=(
                                f"Análise {current_pass + 1} de {total_passes} · "
                                f"{raw_pct}% desta análise"
                            )
                        )
                        last_raw_pct = raw_pct
                
        process.wait()
        pm.clear_active_process()

        if cancelled_during_demucs:
            pm.check_cancelled()
        if process.returncode != 0:
            raise RuntimeError(f"Demucs falhou com código de retorno {process.returncode}")

        output_folder = Path(temp_output_dir) / model_name / audio_stem
        vocals_path = output_folder / "vocals.wav"
        instrumental_path = output_folder / "no_vocals.wav"
        if not vocals_path.exists() or not instrumental_path.exists():
            raise FileNotFoundError(
                f"Arquivos gerados pelo Demucs não foram encontrados. Esperado em: {output_folder}"
            )

        if update_callback:
            update_callback(
                "processing",
                "Vocais separados com sucesso",
                55,
                stage_progress=100,
                stage_detail=f"{total_passes} análises locais concluídas"
            )

        logger.info("Separação do Demucs concluída com sucesso.")
        
        return str(vocals_path), str(instrumental_path)
        
    except Exception as e:
        logger.error(f"Erro ao executar o Demucs: {e}")
        raise RuntimeError(f"Demucs falhou: {e}")
