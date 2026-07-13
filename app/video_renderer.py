import os
import subprocess
import logging
import random
from audio_processor import get_file_duration

logger = logging.getLogger("karaoke")

def check_has_video(file_path: str) -> bool:
    """Verifica se o arquivo contém um fluxo de vídeo válido usando ffprobe."""
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return "video" in result.stdout.strip().lower()
    except Exception as e:
        logger.warning(f"Erro ao verificar fluxo de vídeo para {file_path}: {e}")
        return False

def get_random_default_background() -> str:
    """Retorna o caminho de uma imagem de paisagem aleatória pré-baixada."""
    bg_dir = "/app/default_backgrounds"
    if os.path.exists(bg_dir):
        try:
            files = [os.path.join(bg_dir, f) for f in os.listdir(bg_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            if files:
                chosen = random.choice(files)
                logger.info(f"Selecionada imagem de paisagem aleatória: {chosen}")
                return chosen
        except Exception as e:
            logger.error(f"Erro ao selecionar imagem de fundo aleatória: {e}")
    return None

def run_ffmpeg_with_logging(cmd: list[str], env: dict = None) -> bool:
    """Executa o FFmpeg transmitindo a saída em tempo real para os logs do container."""
    import process_manager as pm
    pm.check_cancelled()
    try:
        logger.info(f"Executando FFmpeg: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        pm.set_active_process(process)
        
        # Ler a saída linha a linha
        for line in process.stdout:
            if pm.cancel_event.is_set():
                process.terminate()
                break
            line_str = line.strip()
            # Filtrar logs repetitivos de frame para evitar inundação de logs, mantendo alertas de erro
            if "frame=" in line_str or "size=" in line_str or "time=" in line_str or "speed=" in line_str or "Error" in line_str:
                logger.info(f"[FFmpeg] {line_str}")
        
        process.wait()
        pm.clear_active_process()
        pm.check_cancelled()
        
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg falhou com código de retorno {process.returncode}")
        return True
    except Exception as e:
        pm.clear_active_process()
        logger.error(f"Exceção ao rodar FFmpeg: {e}")
        raise

def render_karaoke_video(
    instrumental_path: str,
    ass_path: str,
    output_mp4_path: str,
    background_image_path: str = None,
    original_video_path: str = None,
    background_mode: str = "image"
) -> str:
    """
    Renderiza o vídeo final de karaoke em formato MP4.
    Suporta fundo de imagem estática, vídeo original, paisagem aleatória ou cor preta sólida.
    """
    logger.info(f"Iniciando a renderização do vídeo final via FFmpeg. Modo de Fundo: {background_mode}")
    
    # 1. Obter a duração exata do áudio instrumental
    duration = get_file_duration(instrumental_path)
    if duration <= 0:
        raise ValueError(
            f"Duração inválida do áudio instrumental ({duration}s). Não é possível renderizar."
        )
        
    logger.info(f"Duração do áudio instrumental: {duration:.2f} segundos.")
    
    subtitles_filter = f"subtitles='{ass_path}'"
    
    # Decidir o arquivo de imagem/vídeo de fundo com base no modo selecionado
    final_bg_image = None
    use_original_video = False
    
    if background_mode == "image" and background_image_path and os.path.exists(background_image_path):
        final_bg_image = background_image_path
    elif background_mode == "original_video" and original_video_path and check_has_video(original_video_path):
        use_original_video = True
    elif background_mode == "random_landscape":
        final_bg_image = get_random_default_background()
        if not final_bg_image:
            logger.info("Nenhuma imagem de paisagem disponível no cache. Usando fundo preto sólido.")
    elif background_mode == "solid_black":
        # Mantém final_bg_image = None
        pass
    else:
        # Fallback inteligente se nada for definido
        if background_image_path and os.path.exists(background_image_path):
            final_bg_image = background_image_path
        else:
            final_bg_image = get_random_default_background()

    # Filtro comum de redimensionamento e padding de vídeo para caber em 1280x720
    video_filters = (
        f"scale=1280:720:force_original_aspect_ratio=decrease,"
        f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
        f"{subtitles_filter}"
    )

    if use_original_video:
        logger.info(f"Configurando vídeo original como fundo: {original_video_path}")
        cmd = [
            "ffmpeg",
            "-y",
            "-i", original_video_path,
            "-i", instrumental_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-vf", video_filters,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{duration:.3f}",
            output_mp4_path
        ]
    elif final_bg_image:
        logger.info(f"Configurando imagem de plano de fundo: {final_bg_image}")
        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", final_bg_image,
            "-i", instrumental_path,
            "-vf", video_filters,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{duration:.3f}",
            output_mp4_path
        ]
    else:
        logger.info("Configurando fundo preto sólido.")
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s=1280x720:r=25:d={duration:.3f}",
            "-i", instrumental_path,
            "-vf", subtitles_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_mp4_path
        ]
        
    try:
        run_ffmpeg_with_logging(cmd)
        logger.info("Renderização do vídeo concluída com sucesso.")
        return output_mp4_path
    except Exception as e:
        raise RuntimeError(f"FFmpeg falhou ao renderizar o vídeo: {e}")
