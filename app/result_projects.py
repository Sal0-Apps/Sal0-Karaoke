"""Keep an editable, private project beside each retained video result."""
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

_lock = threading.RLock()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.project-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def read(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError): return {}


def enabled(output_dir):
    return read(Path(output_dir)/'result-cache-settings.json').get('keep_individual_results', True) is not False


def save_settings(output_dir, value):
    if type(value) is not bool:
        raise ValueError('Escolha se os projetos dos resultados devem ser preservados.')
    atomic(Path(output_dir)/'result-cache-settings.json', {'keep_individual_results':value})


def _root(job_id, queue_root):
    if not re.fullmatch(r'[a-f0-9]{32}', str(job_id)):
        return None
    root = Path(queue_root).resolve()
    folder = root/job_id
    return folder if folder.resolve().parent == root and not folder.is_symlink() else None


def _marker(video):
    video = Path(video)
    return video.parent/'.sal0-projects'/(video.name+'.json')


def capture(job, queue_root):
    """Record settings only; media and checkpoints already belong to this job."""
    if job.get('retain_result_cache', True) is False: return False
    folder = _root(job.get('id'), queue_root)
    pipeline = job.get('pipeline') or {}
    filename = job.get('history_filename')
    if not folder or not filename or Path(filename).name != filename or not pipeline.get('library_dir'): return False
    cache = folder/'cache'
    if Path(pipeline.get('cache_dir','/missing')).resolve() != cache.resolve() or not cache.is_dir(): return False
    video = Path(pipeline['library_dir'])/'history'/filename
    if not video.is_file() or video.suffix.lower() != '.mp4': return False
    snapshot = json.loads(json.dumps(job))
    snapshot.update(status='done', history_filename=filename, _archived_result=True)
    with _lock:
        atomic(folder/'result-project.json', {'video':str(video.resolve()),'job':snapshot})
        atomic(_marker(video), {'job_id':job['id']})
    return True


def lookup_job(job_id, queue_root, user=None, admin=False):
    folder = _root(job_id, queue_root)
    if not folder: return None
    document = read(folder/'result-project.json')
    job = document.get('job') or {}
    pipeline = job.get('pipeline') or {}
    if job.get('id') != job_id: return None
    if user is not None and not admin and job.get('owner_username') != user.get('username'): return None
    cache = folder/'cache'
    if Path(pipeline.get('cache_dir','/missing')).resolve() != cache.resolve() or not cache.is_dir(): return None
    video = Path(pipeline.get('library_dir','/missing'))/'history'/str(job.get('history_filename',''))
    if str(video.resolve()) != document.get('video') or not video.is_file(): return None
    return job


def lookup_video(video, queue_root, user=None, admin=False):
    job = lookup_job(read(_marker(video)).get('job_id'), queue_root, user, admin)
    if not job: return None
    actual = Path(job['pipeline']['library_dir'])/'history'/job['history_filename']
    return job if actual.resolve() == Path(video).resolve() else None


def protected(cache_dir, queue_root):
    if not cache_dir: return False
    folder = Path(cache_dir).resolve().parent
    return bool(lookup_job(folder.name, queue_root))


def rename_video(old, new, queue_root):
    with _lock:
        identifier = read(_marker(old)).get('job_id')
        folder = _root(identifier, queue_root)
        if not folder: return
        document = read(folder/'result-project.json')
        if document.get('video') != str(Path(old).resolve()): return
        document['video'] = str(Path(new).resolve())
        document['job']['history_filename'] = Path(new).name
        atomic(folder/'result-project.json', document)
        atomic(_marker(new), {'job_id':identifier})
        _marker(old).unlink(missing_ok=True)


def remove_video(video, queue_root):
    """Called only after a successful video deletion, under the queue's edit lock."""
    with _lock:
        identifier = read(_marker(video)).get('job_id')
        folder = _root(identifier, queue_root)
        document = read(folder/'result-project.json') if folder else {}
        _marker(video).unlink(missing_ok=True)
        if folder and document.get('video') == str(Path(video).resolve()):
            shutil.rmtree(folder)
