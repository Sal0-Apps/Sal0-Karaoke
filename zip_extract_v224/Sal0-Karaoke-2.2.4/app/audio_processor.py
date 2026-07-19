import os
import subprocess
import logging
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

def separate_vocals(audio_path: str, temp_output_dir: str, update_callback=None) -> tuple[str, str]:
    """Usa Demucs em modo CPU para separar o áudio em vocais e instrumental (no_vocals)."""
    logger.info(f"Iniciando a separação de vocais com Demucs para: {audio_path}")
    
    # Nome base do arquivo de áudio para localizar o diretório de saída do Demucs
    audio_stem = Path(audio_path).stem
    
    # Demucs salva em: <temp_output_dir>/<model_name>/<audio_stem>/
    # O modelo padrão que usamos é o "htdemucs"
    model_name = "htdemucs_ft"
    
    # Montar comando do Demucs
    # Usando o modelo padrão htdemucs, rodando apenas na CPU, e separando apenas vocals + instrumental
    cmd = [
        "demucs",
        "-d", "cpu",
        "-n", "htdemucs_ft",
        "--two-stems", "vocals",
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
        
        # Executar o Demucs com streaming de logs em tempo real
        logger.info(f"Executando Demucs: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        pm.set_active_process(process)
        
        import re
        for line in process.stdout:
            if pm.cancel_event.is_set():
                process.terminate()
                break
            line_str = line.strip()
            if line_str:
                logger.info(f"[Demucs] {line_str}")
                if update_callback:
                    if "downloading" in line_str.lower() or "download" in line_str.lower():
                        update_callback("processing", "Baixando Modelo de IA Demucs (Aguarde a 1ª vez)...", 25)
                    match = re.search(r'(\d+)%', line_str)
                    if match:
                        pct = int(match.group(1))
                        scaled_pct = 25 + int(pct * 0.30)
                        update_callback("processing", f"Separando vocais do áudio (Demucs {pct}%)", scaled_pct)
                
        process.wait()
        pm.clear_active_process()
        pm.check_cancelled()
        
        if process.returncode != 0:
            raise RuntimeError(f"Demucs falhou com código de retorno {process.returncode}")
            
        logger.info("Separação do Demucs concluída com sucesso.")
        
        # Caminhos dos arquivos de saída gerados pelo Demucs
        output_folder = Path(temp_output_dir) / model_name / audio_stem
        vocals_path = output_folder / "vocals.wav"
        instrumental_path = output_folder / "no_vocals.wav"
        
        if not vocals_path.exists() or not instrumental_path.exists():
            raise FileNotFoundError(
                f"Arquivos gerados pelo Demucs não foram encontrados. Esperado em: {output_folder}"
            )
            
        return str(vocals_path), str(instrumental_path)
        
    except Exception as e:
        logger.error(f"Erro ao executar o Demucs: {e}")
        raise RuntimeError(f"Demucs falhou: {e}")
