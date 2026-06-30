import os
import subprocess
import logging
from audio_processor import get_file_duration

logger = logging.getLogger("karaoke")

def render_karaoke_video(
    instrumental_path: str,
    ass_path: str,
    output_mp4_path: str,
    background_image_path: str = None
) -> str:
    """
    Renderiza o vídeo final de karaoke em formato MP4.
    Fundo preto sólido ou imagem de fundo estática.
    """
    logger.info("Iniciando a renderização do vídeo final via FFmpeg...")
    
    # 1. Obter a duração exata do áudio instrumental
    duration = get_file_duration(instrumental_path)
    if duration <= 0:
        raise ValueError(
            f"Duração inválida do áudio instrumental ({duration}s). Não é possível renderizar."
        )
        
    logger.info(f"Duração do áudio instrumental: {duration:.2f} segundos.")
    
    # O filtro de legendas do FFmpeg no linux aceita caminhos normais, mas é bom colocar entre aspas simples
    # para evitar problemas se contiver caminhos com caracteres não-convencionais.
    # Ex: subtitles='/tmp/tmp123/karaoke.ass'
    subtitles_filter = f"subtitles='{ass_path}'"
    
    if background_image_path and os.path.exists(background_image_path):
        logger.info(f"Usando imagem de fundo: {background_image_path}")
        
        # Filtro de vídeo para imagem de fundo:
        # - Redimensiona mantendo aspect ratio para caber dentro de 1280x720 (decrease)
        # - Centraliza a imagem e completa o restante com bordas pretas (pad)
        # - Aplica as legendas ASS por cima
        video_filters = (
            f"scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,"
            f"{subtitles_filter}"
        )
        
        cmd = [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", background_image_path,
            "-i", instrumental_path,
            "-vf", video_filters,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{duration:.3f}",
            output_mp4_path
        ]
    else:
        logger.info("Nenhuma imagem de fundo fornecida. Usando fundo preto sólido padrão.")
        
        # Filtro de vídeo para cor preta sólida com as legendas embutidas
        video_filters = subtitles_filter
        
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi",
            "-i", f"color=c=black:s=1280x720:r=25:d={duration:.3f}",
            "-i", instrumental_path,
            "-vf", video_filters,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_mp4_path
        ]
        
    try:
        # Executar comando FFmpeg
        logger.info("Executando FFmpeg...")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        logger.info("Renderização do vídeo concluída com sucesso.")
        return output_mp4_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Erro ao executar o FFmpeg para renderizar o vídeo: {e.stderr}")
        raise RuntimeError(f"FFmpeg falhou ao renderizar o vídeo: {e.stderr}")
