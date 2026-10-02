"""Reutilização de insumos, nunca de checkpoints de outra tarefa."""
import os
import shutil
import json
from urllib.parse import urlparse, parse_qs
import hashlib


def file_fingerprint(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def youtube_identity(url):
    parsed = urlparse(str(url or ''))
    if parsed.hostname in {'youtu.be', 'www.youtu.be'}:
        return parsed.path.strip('/').split('/')[0]
    if parsed.hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}:
        if parsed.path == '/watch':
            return parse_qs(parsed.query).get('v', [''])[0]
        parts = parsed.path.strip('/').split('/')
        if len(parts) == 2 and parts[0] in {'shorts', 'embed', 'live'}:
            return parts[1]
    return ''


def copy_reusable_inputs(source, destination, youtube_url=None):
    """Novas tarefas reaproveitam áudio caro, mas refazem revisão e renderização.

    Retomadas após pausa continuam usando a pasta isolada da mesma tarefa e
    não passam por esta função. Checkpoints, ASS e resultados não são copiados.
    """
    if youtube_url:
        try:
            with open(os.path.join(source, 'cache_meta.json'), encoding='utf-8') as file:
                meta = json.load(file)
            identity = youtube_identity(youtube_url)
            if not identity or identity != youtube_identity(meta.get('youtube_url')):
                return
            # Requests for a fresh source upgrade old, capped downloads once.
            if meta.get('download_quality_version') != 2:
                return
        except (OSError, ValueError, AttributeError):
            return
    allowed = {'cache_meta.json', 'original_converted.wav', 'vocals.wav',
               'instrumental.wav', 'transcribed_segments.json', 'lead_vocals.wav',
               'backing_vocals.wav', 'backing_model_version.txt',
               'synced_acoustic_segments.json', 'whisper_cache_meta.json',
               'subtitle_segments_original.json', 'subtitle_info_original.json'}
    os.makedirs(destination, exist_ok=True)
    for name in os.listdir(source):
        path = os.path.join(source, name)
        if os.path.isfile(path) and (name in allowed or name.startswith(('original_input.', 'original_bg.'))):
            shutil.copy2(path, os.path.join(destination, name))
