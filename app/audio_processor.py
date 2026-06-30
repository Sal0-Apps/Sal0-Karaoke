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
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        logger.info("Extração de áudio concluída com sucesso via FFmpeg.")
        return output_wav_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Erro no FFmpeg ao extrair áudio: {e.stderr}")
        raise RuntimeError(f"FFmpeg falhou: {e.stderr}")

def separate_vocals(audio_path: str, temp_output_dir: str) -> tuple[str, str]:
    """Usa Demucs em modo CPU para separar o áudio em vocais e instrumental (no_vocals)."""
    logger.info(f"Iniciando a separação de vocais com Demucs para: {audio_path}")
    
    # Nome base do arquivo de áudio para localizar o diretório de saída do Demucs
    audio_stem = Path(audio_path).stem
    
    # Demucs salva em: <temp_output_dir>/<model_name>/<audio_stem>/
    # O modelo padrão que usamos é o "htdemucs"
    model_name = "htdemucs"
    
    # Montar comando do Demucs
    # Usando o modelo padrão htdemucs, rodando apenas na CPU, e separando apenas vocals + instrumental
    cmd = [
        "demucs",
        "-d", "cpu",
        "--two-stems", "vocals",
        "-o", temp_output_dir,
        audio_path
    ]
    
    try:
        # Configurar variáveis de ambiente para salvar modelos do PyTorch/Demucs no disco persistente
        env = os.environ.copy()
        env["TORCH_HOME"] = "/data/output/models/torch"
        env["HF_HOME"] = "/data/output/models/huggingface"
        
        # Executar o Demucs
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, env=env)
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
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Erro ao executar o Demucs: {e.stderr}")
        raise RuntimeError(f"Demucs falhou: {e.stderr}")
