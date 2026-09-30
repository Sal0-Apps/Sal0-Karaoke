"""Create a captioned MP4 for audio-only SRT jobs, using local FFmpeg."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def media_has_motion_video(source):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)],
                            capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout).get('streams', [])
    return any(stream.get('codec_type') == 'video' and not stream.get('disposition', {}).get('attached_pic')
               for stream in streams)


def render_audio_subtitle_video(audio, subtitles, output, duration, runner=None, progress_callback=None):
    if duration <= 0:
        raise ValueError('A duração do áudio deve ser positiva.')
    if runner is None:
        from video_renderer import run_ffmpeg_with_logging
        runner = run_ffmpeg_with_logging
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    temporary_output = str(Path(output).with_suffix('.rendering.mp4'))
    try:
        with tempfile.TemporaryDirectory(prefix='sal0-srt-video-') as folder:
            # Controlled filename avoids filter escaping problems in uploaded filenames.
            caption_file = Path(folder) / 'captions.srt'
            shutil.copy2(subtitles, caption_file)
            command = ['ffmpeg', '-y', '-i', str(audio), '-f', 'lavfi', '-i',
                'color=c=0x101827:s=1280x720:r=25', '-map', '1:v:0', '-map', '0:a:0',
                '-vf', f"subtitles='{caption_file}':force_style='FontName=DejaVu Sans,FontSize=24,Outline=2,MarginV=40'",
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-t', str(duration), '-shortest', '-movflags', '+faststart', temporary_output]
            if not runner(command, progress_callback=progress_callback, total_duration=duration):
                raise RuntimeError('Não foi possível criar o vídeo do áudio. O SRT permanece na Biblioteca.')
            os.replace(temporary_output, output)
    finally:
        if os.path.exists(temporary_output): os.remove(temporary_output)
    return str(output)
