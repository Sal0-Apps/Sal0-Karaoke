"""Capas locais com FFmpeg, sem serviços externos nem alterações no áudio."""
import hashlib
import os
import subprocess
import tempfile
import textwrap
import threading
from pathlib import Path

THUMBNAIL_ROOT = Path('/data/cache/thumbnails')
thumbnail_lock = threading.Lock()


def filter_path(path):
    return str(path).replace('\\', '/').replace(':', '\\:').replace("'", "'\\''")


def cover_title(title):
    title = ' '.join(str(title).split()) or 'Sal0 Karaokê'
    # No máximo 180 caracteres, como os nomes persistidos na biblioteca.
    return '\n'.join(textwrap.wrap(title[:180], width=36, break_long_words=True))


def create_video_cover(source, title, destination, runner):
    """Gera um único frame escurecido com o título, em 1280x720."""
    with tempfile.TemporaryDirectory(prefix='sal0-cover-') as directory:
        text_file = Path(directory) / 'title.txt'
        text_file.write_text(cover_title(title), encoding='utf-8', newline='\n')
        command = ['ffmpeg', '-y']
        if source:
            command += ['-i', str(source)]
        else:
            command += ['-f', 'lavfi', '-i', 'color=c=0x071522:s=1280x720:r=1']
        fonts = [Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
                 Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/arialbd.ttf']
        font = next((path for path in fonts if path.is_file()), None)
        font_option = f"fontfile='{filter_path(font)}'" if font else "font='DejaVu Sans'"
        filters = (
            'scale=1280:720:force_original_aspect_ratio=decrease,'
            'pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,'
            'drawbox=x=0:y=0:w=iw:h=ih:color=black@0.58:t=fill,'
            f"drawtext={font_option}:textfile='{filter_path(text_file)}':"
            'expansion=none:fontcolor=white:fontsize=48:line_spacing=14:'
            'x=(w-text_w)/2:y=(h-text_h)/2'
        )
        command += ['-vf', filters, '-frames:v', '1', '-threads', '1', str(destination)]
        runner(command)


def add_cover_to_command(command, cover_path, duration):
    """Acrescenta três segundos silenciosos antes do conteúdo já sincronizado."""
    command = list(command)
    video_filter = 'null'
    if '-vf' in command:
        index = command.index('-vf')
        video_filter = command[index + 1]
        del command[index:index + 2]
    while '-map' in command:
        index = command.index('-map')
        del command[index:index + 2]
    # Os dois inputs existentes são fundo e instrumental; a capa é o terceiro.
    second_input = [i for i, value in enumerate(command) if value == '-i'][1]
    command[second_input + 2:second_input + 2] = ['-loop', '1', '-i', str(cover_path)]
    if '-shortest' in command:
        command.remove('-shortest')
    if '-t' in command:
        index = command.index('-t')
        del command[index:index + 2]
    graph = (
        f'[0:v]{video_filter},fps=25,setsar=1,trim=duration={duration:.3f},setpts=PTS-STARTPTS[main];'
        '[2:v]fps=25,setsar=1,trim=duration=3,setpts=PTS-STARTPTS[intro];'
        'anullsrc=r=48000:cl=stereo,atrim=duration=3,asetpts=PTS-STARTPTS[silence];'
        f'[1:a]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[audio];'
        '[intro][silence][main][audio]concat=n=2:v=1:a=1[out][sound]'
    )
    command[-1:-1] = ['-filter_complex', graph, '-map', '[out]', '-map', '[sound]',
                      '-t', f'{duration + 3:.3f}', '-movflags', '+faststart']
    return command


def video_thumbnail(source):
    """Miniatura derivada, privada e invalidada quando o arquivo é substituído."""
    source = Path(source)
    stat = source.stat()
    identity = hashlib.sha256(str(source.resolve()).encode()).hexdigest()
    revision = hashlib.sha256(f'{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:16]
    destination = THUMBNAIL_ROOT / f'{identity}-{revision}.jpg'
    with thumbnail_lock:
        if destination.is_file():
            return destination
        THUMBNAIL_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=THUMBNAIL_ROOT) as directory:
            temporary = Path(directory) / 'frame.jpg'
            # Prefere um frame após a abertura; vídeos curtos usam o primeiro.
            for sample_time in ('3.2', '0'):
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', sample_time, '-i', str(source),
                                '-vf', 'scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2',
                                '-frames:v', '1', '-threads', '1', str(temporary)],
                               check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if temporary.is_file() and temporary.stat().st_size:
                    break
            os.replace(temporary, destination)
        for stale in THUMBNAIL_ROOT.glob(f'{identity}-*.jpg'):
            if stale != destination:
                stale.unlink(missing_ok=True)
    return destination
