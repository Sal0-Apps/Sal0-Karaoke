"""Check audio/video timelines before reusing or publishing local media."""
import json
import math
from pathlib import Path
import subprocess


def _seconds(value):
    try:
        pieces = str(value).split(':')
        result = sum(float(piece)*60**index for index, piece in enumerate(reversed(pieces)))
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


def media_durations(path):
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
            'stream=codec_type,duration:stream_tags=DURATION:format=duration', '-of', 'json', str(path)],
            capture_output=True, text=True, check=True, timeout=30)
        data = json.loads(result.stdout)
        duration = _seconds(data.get('format', {}).get('duration'))
        streams = {'container': duration}
        for stream in data.get('streams', []):
            kind = stream.get('codec_type')
            if kind in {'audio', 'video'} and kind not in streams:
                streams[kind] = (_seconds(stream.get('duration'))
                    or _seconds(stream.get('tags', {}).get('DURATION')) or duration)
        return streams
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        raise RuntimeError('Não foi possível conferir a duração da mídia: '+Path(path).name) from error


def require_duration(path, expected, kinds=('audio',), extra_tolerance=0):
    if not math.isfinite(expected) or expected <= 0:
        raise ValueError('A duração esperada da música é inválida.')
    streams = media_durations(path)
    tolerance = max(.06, min(.25, expected*.001), extra_tolerance)
    for kind in kinds:
        actual = streams.get(kind)
        if actual is None or abs(actual-expected) > tolerance:
            label = {'audio':'áudio','video':'vídeo','container':'mídia'}[kind]
            measured = f'{actual:.2f} s' if actual is not None else 'ausente'
            raise RuntimeError(f'Resultado incompleto: {label} com duração {measured}; '
                f'eram esperados {expected:.2f} s. O arquivo não será publicado.')
    return streams


def complete_audio_cache(path, expected):
    if not Path(path).is_file():
        return False
    try:
        require_duration(path, expected)
        return True
    except RuntimeError:
        return False


def invalidate_audio_derivatives(cache_dir, *, extraction=False):
    """Discard automatic artifacts, retaining the input, guide and human reviews."""
    root = Path(cache_dir)
    names = ['vocals.wav', 'instrumental.wav', 'lead_vocals.wav', 'backing_vocals.wav',
        'instrumental_with_backing.wav', 'backing_model_version.txt', 'transcribed_segments.json',
        'synced_acoustic_segments.json', 'whisper_cache_meta.json', 'guided_whisper_lyrics.json',
        'aligned_lyrics.json', 'display_segments.json', 'lyrics_guide_cache.json', 'karaoke.ass']
    if extraction:
        names.append('original_converted.wav')
    for name in names:
        (root/name).unlink(missing_ok=True)
    checkpoints = root/'stage_checkpoints.json'
    if checkpoints.exists():
        try:
            data = json.loads(checkpoints.read_text())
            completed = data['completed_stages']
            for stage in ('audio_extracted', 'vocals_separated', 'transcription_ready', 'subtitles_generated', 'video_rendered'):
                completed.pop(stage, None)
            temporary = checkpoints.with_suffix('.repair.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False))
            temporary.replace(checkpoints)
        except (ValueError, TypeError, KeyError):
            checkpoints.unlink(missing_ok=True)
