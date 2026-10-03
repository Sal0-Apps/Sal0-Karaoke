"""Burn speech subtitles into the original video, or a background for audio."""
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from subtitle_settings import normalize_subtitle_settings


def media_has_motion_video(source):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(source)],
                            capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout).get('streams', [])
    return any(stream.get('codec_type') == 'video' and not stream.get('disposition', {}).get('attached_pic')
               for stream in streams)


def ass_color(color, opacity=100):
    alpha = round(255 * (1 - opacity / 100))
    return f'&H{alpha:02X}{color[5:7]}{color[3:5]}{color[1:3]}'


def render_subtitle_video(source, subtitles, output, duration, runner=None, progress_callback=None,
                          settings=None, background=None):
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('A duração da mídia deve ser positiva.')
    settings = normalize_subtitle_settings(settings)
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
            command = ['ffmpeg', '-y', '-i', str(source)]
            if media_has_motion_video(source):
                # Keep the original image and every second of the source audio.
                command += ['-map', '0:v:0', '-map', '0:a:0']
                base_filter = f'pad=ceil(iw/2)*2:ceil(ih/2)*2,tpad=stop_mode=clone:stop_duration={duration}'
            elif background and os.path.isfile(background):
                if media_has_motion_video(background):
                    command += ['-stream_loop', '-1', '-i', str(background)]
                else:
                    command += ['-loop', '1', '-i', str(background)]
                command += ['-map', '1:v:0', '-map', '0:a:0']
                base_filter = 'scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1,fps=25'
            else:
                color = settings['background_color'].replace('#', '0x')
                command += ['-f', 'lavfi', '-i', f'color=c={color}:s=1280x720:r=25', '-map', '1:v:0', '-map', '0:a:0']
                base_filter = 'setsar=1'
            style = ','.join([
                'FontName=DejaVu Sans', f"FontSize={settings['font_size']}",
                f"PrimaryColour={ass_color(settings['text_color'])}",
                f"OutlineColour={ass_color(settings['box_color'], settings['box_opacity'])}",
                f"BackColour={ass_color(settings['box_color'], settings['box_opacity'])}",
                'BorderStyle=3', 'Outline=2', 'Shadow=0', 'MarginL=32', 'MarginR=32', 'MarginV=24',
                f"Alignment={dict(bottom=2, middle=5, top=8)[settings['text_position']]}",
            ])
            command += ['-vf', f"{base_filter},subtitles='{caption_file}':force_style='{style}'",
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '320k', '-t', str(duration), '-shortest', '-movflags', '+faststart', temporary_output]
            if not runner(command, progress_callback=progress_callback, total_duration=duration):
                raise RuntimeError('Não foi possível criar o vídeo legendado. O SRT permanece na Biblioteca.')
            os.replace(temporary_output, output)
    finally:
        if os.path.exists(temporary_output): os.remove(temporary_output)
    return str(output)


def render_audio_subtitle_video(audio, subtitles, output, duration, runner=None, progress_callback=None):
    return render_subtitle_video(audio, subtitles, output, duration, runner, progress_callback)
