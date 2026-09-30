"""Admin-only OAuth and a durable, resumable YouTube publication queue."""
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
from media_covers import video_thumbnail

API = 'https://www.googleapis.com/youtube/v3'
UPLOAD = 'https://www.googleapis.com/upload/youtube/v3'
SCOPE = 'https://www.googleapis.com/auth/youtube.force-ssl'
PRIVACY = {'private', 'unlisted', 'public'}
CHUNK = 8 * 1024 * 1024


class PublicationError(Exception):
    pass


def uploaded_offset(response):
    value = response.headers.get('Range', '')
    if not value:
        return 0
    match = re.fullmatch(r'bytes=0-(\d+)', value)
    if not match:
        raise PublicationError('O YouTube retornou uma posição de envio inválida.')
    return int(match[1]) + 1


def write_private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


class YouTubePublisher:
    def __init__(self, root='/data/youtube'):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.worker_lock = threading.Lock()
        self.oauth_states = {}

    def read(self, name, default=None):
        try:
            return json.loads((self.root / name).read_text())
        except (OSError, ValueError):
            return {} if default is None else default

    def save(self, name, value):
        with self.lock:
            write_private_json(self.root / name, value)

    def client_config(self):
        config = {key: os.environ.get(env, '').strip() for key, env in (
            ('client_id', 'YOUTUBE_CLIENT_ID'), ('client_secret', 'YOUTUBE_CLIENT_SECRET'),
            ('redirect_uri', 'YOUTUBE_REDIRECT_URI'))}
        if not all(config.values()):
            raise PublicationError('Configure YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET e YOUTUBE_REDIRECT_URI no servidor.')
        uri = urlparse(config['redirect_uri'])
        if uri.scheme != 'https' and not (uri.scheme == 'http' and uri.hostname in {'localhost', '127.0.0.1'}):
            raise PublicationError('O retorno OAuth exige HTTPS ou localhost.')
        return config

    def authorize(self, username):
        config = self.client_config()
        with self.lock:
            self.oauth_states = {k: v for k, v in self.oauth_states.items() if v['expires'] > time.time()}
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
            self.oauth_states[state] = {'username': username, 'verifier': verifier, 'expires': time.time() + 600}
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': config['client_id'], 'redirect_uri': config['redirect_uri'],
            'response_type': 'code', 'scope': SCOPE, 'access_type': 'offline',
            'prompt': 'consent', 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256',
        })

    def finish_authorization(self, state, code, check_admin):
        with self.lock:
            pending = self.oauth_states.pop(state, None)
        if not pending or pending['expires'] < time.time():
            raise PublicationError('Conexão expirada ou inválida. Conecte novamente pelo painel administrativo.')
        check_admin(pending['username'])
        config = self.client_config()
        response = requests.post('https://oauth2.googleapis.com/token', data={
            **config, 'code': code, 'code_verifier': pending['verifier'], 'grant_type': 'authorization_code'}, timeout=30)
        if response.status_code != 200:
            raise PublicationError('O Google não autorizou a conexão. Tente novamente.')
        token = response.json()
        if not token.get('refresh_token') or not token.get('access_token'):
            raise PublicationError('A conexão não concedeu acesso permanente. Reconecte o canal.')
        channel = requests.get(API + '/channels', params={'part': 'snippet', 'mine': 'true'},
                               headers={'Authorization': 'Bearer ' + token['access_token']}, timeout=30)
        if channel.status_code != 200 or not channel.json().get('items'):
            raise PublicationError('A conta autorizada não possui um canal disponível.')
        item = channel.json()['items'][0]
        token['channel_id'] = item['id']
        token['channel_title'] = item['snippet']['title']
        token['expires_at'] = time.time() + token.get('expires_in', 3600)
        with self.lock:
            if any(j.get('status') in {'queued', 'uploading', 'finalizing'} for j in self.read('jobs.json', [])):
                raise PublicationError('Aguarde os envios pendentes antes de trocar a conexão do canal.')
            self.save('token.json', token)
        return token['channel_title']

    def import_desktop_authorization(self, data):
        if not isinstance(data, dict) or data.get('format') != 'sal0-youtube-desktop-v1':
            raise PublicationError('Use o arquivo gerado pelo autorizador para computador do Sal0.')
        keys = ('client_id', 'client_secret', 'refresh_token')
        if any(not isinstance(data.get(key), str) or not 1 <= len(data[key]) <= 4096 for key in keys):
            raise PublicationError('Arquivo de autorização inválido.')
        # Never trust tokens or channel identities supplied by the upload.
        response = requests.post('https://oauth2.googleapis.com/token', data={
            **{key: data[key] for key in keys}, 'grant_type': 'refresh_token'}, timeout=30)
        if response.status_code != 200:
            raise PublicationError('O Google recusou a autorização. Gere um novo arquivo no computador.')
        token = response.json()
        if not isinstance(token.get('access_token'), str) or SCOPE not in str(token.get('scope', '')).split():
            raise PublicationError('A autorização não permite gerenciar vídeos e playlists. Use o autorizador do Sal0.')
        channel = requests.get(API + '/channels', params={'part': 'snippet', 'mine': 'true'},
            headers={'Authorization': 'Bearer ' + token['access_token']}, timeout=30)
        if channel.status_code != 200 or not channel.json().get('items'):
            raise PublicationError('Não foi possível confirmar o canal dessa autorização.')
        item = channel.json()['items'][0]
        token.update(refresh_token=data['refresh_token'], channel_id=item['id'],
            channel_title=item['snippet']['title'], expires_at=time.time() + token.get('expires_in', 3600),
            desktop_client={key: data[key] for key in ('client_id', 'client_secret')})
        with self.lock:
            if any(j.get('status') in {'queued', 'uploading', 'finalizing'} for j in self.read('jobs.json', [])):
                raise PublicationError('Aguarde os envios pendentes antes de trocar a conexão do canal.')
            self.save('token.json', token)
        return token['channel_title']

    def token(self):
        with self.lock:
            token = self.read('token.json')
            if not token.get('refresh_token'):
                raise PublicationError('Conecte o canal do YouTube no painel administrativo.')
            if token.get('expires_at', 0) <= time.time() + 60:
                config = token.get('desktop_client') or self.client_config()
                response = requests.post('https://oauth2.googleapis.com/token', data={
                    'client_id': config['client_id'], 'client_secret': config['client_secret'],
                    'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'}, timeout=30)
                if response.status_code != 200:
                    raise PublicationError('A conexão do YouTube expirou. Reconecte o canal.')
                updated = response.json()
                token.update(updated)
                token['expires_at'] = time.time() + updated.get('expires_in', 3600)
                self.save('token.json', token)
            return token

    def api(self, method, path, **kwargs):
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = 'Bearer ' + self.token()['access_token']
        response = requests.request(method, API + path, headers=headers, timeout=(15, 60), **kwargs)
        if response.status_code >= 400:
            try:
                reason = response.json()['error']['errors'][0]['reason']
            except (ValueError, KeyError, IndexError):
                reason = 'apiError'
            raise PublicationError(f'YouTube: {reason} (HTTP {response.status_code}).')
        return response.json()

    def playlists(self):
        result, page = [], None
        while True:
            payload = self.api('GET', '/playlists', params={
                'part': 'snippet,status', 'mine': 'true', 'maxResults': 50,
                **({'pageToken': page} if page else {})})
            result.extend({'id': item['id'], 'title': item['snippet']['title']} for item in payload.get('items', []))
            page = payload.get('nextPageToken')
            if not page:
                return result

    def settings(self, username):
        settings = self.read('settings.json')
        return {**{'privacy': 'private', 'playlist_id': '', 'title_template': '{title} | Karaokê'},
                **settings.get('defaults', {}),
                'users_can_publish': settings.get('users_can_publish', False),
                'user_assignments': settings.get('user_assignments', {})}

    def save_settings(self, username, options):
        if not isinstance(options.get('users_can_publish', False), bool):
            raise PublicationError('Ative a permissão de publicação explicitamente.')
        if options.get('privacy') not in PRIVACY:
            raise PublicationError('Privacidade inválida.')
        template = str(options.get('title_template') or '{title} | Karaokê').strip()
        if '{title}' not in template or len(template) > 100:
            raise PublicationError('O modelo de título deve conter {title} e ter até 100 caracteres.')
        assignments = options.get('user_assignments', {})
        if not isinstance(assignments, dict) or len(assignments) > 1000:
            raise PublicationError('Configuração de usuários inválida.')
        validated = {}
        for name, assignment in assignments.items():
            if not isinstance(assignment, dict) or not isinstance(assignment.get('enabled', False), bool) or not isinstance(assignment.get('default_publish', False), bool):
                raise PublicationError('Permissões de usuário inválidas.')
            user = self.user_lookup(name)
            if not user or user.get('role') == 'admin':
                raise PublicationError('Selecione um usuário existente.')
            playlist_id = assignment.get('playlist_id', '')
            if not isinstance(playlist_id, str):
                raise PublicationError('Playlist inválida.')
            validated[name] = {'enabled': assignment.get('enabled', False),
                               'playlist_id': playlist_id,
                               'default_publish': assignment.get('default_publish', False)}
        selected = [value['playlist_id'] for value in validated.values() if value['playlist_id']]
        default_playlist = options.get('playlist_id', '')
        available = {p['id']: p for p in self.playlists()} if selected or default_playlist else {}
        if any(value not in available for value in selected) or (default_playlist and default_playlist not in available):
            raise PublicationError('Selecione playlists do canal conectado.')
        for assignment in validated.values():
            assignment['playlist_title'] = available.get(assignment['playlist_id'], {}).get('title', '')
        if options.get('users_can_publish'):
            self.token()
        self.save('settings.json', {'defaults': {'privacy': options['privacy'],
                    'playlist_id': default_playlist, 'title_template': template},
                    'users_can_publish': options.get('users_can_publish', False),
                    'user_assignments': validated})

    def publication_options(self, user, requested=False, playlist_id='', title=''):
        # A saved default only preselects the UI. Each video must explicitly opt in.
        if not requested:
            return None
        settings = self.settings(user.get('username'))
        if user.get('role') != 'admin':
            assignment = settings['user_assignments'].get(user.get('username'), {})
            if not settings['users_can_publish'] or not assignment.get('enabled'):
                raise PublicationError('O administrador ainda não liberou sua publicação no YouTube.')
            if playlist_id != assignment.get('playlist_id', ''):
                raise PublicationError('Use a playlist atribuída à sua conta pelo administrador.')
        token = self.read('token.json')
        if not token.get('channel_id') or not token.get('refresh_token'):
            raise PublicationError('O administrador precisa conectar o canal do YouTube.')
        if len(title) > 100 or '<' in title or '>' in title:
            raise PublicationError('Título do YouTube inválido.')
        return {'privacy': settings['privacy'], 'title_template': settings['title_template'],
                'playlist_id': playlist_id, 'channel_id': token['channel_id'],
                'title_override': title.strip(), 'requester': dict(username=user.get('username'), role=user.get('role'))}

    def quick_options(self, user):
        settings = self.settings(user.get('username'))
        token = self.read('token.json')
        admin = user.get('role') == 'admin'
        assignment = settings['user_assignments'].get(user.get('username'), {})
        enabled = bool(token.get('channel_id') and token.get('refresh_token') and
                       (admin or (settings['users_can_publish'] and assignment.get('enabled'))))
        playlist_id = settings['playlist_id'] if admin else assignment.get('playlist_id', '')
        playlists = self.playlists() if enabled and admin else ([{'id': playlist_id,
            'title': assignment.get('playlist_title', playlist_id)}] if enabled and playlist_id else [])
        return {'enabled': enabled, 'playlists': playlists, 'allow_no_playlist': admin or not playlist_id,
                'playlist_id': playlist_id, 'default_publish': bool(enabled and assignment.get('default_publish', False)),
                'privacy': settings['privacy'], 'channel_title': token.get('channel_title', ''),
                'title_template': settings['title_template']}

    def enqueue(self, video, title, privacy='private', playlist_id='', thumbnail=None, channel_id=None, requester=None):
        video = Path(video).resolve()
        title = str(title).strip()
        if not video.is_file() or video.suffix.lower() != '.mp4' or not 1 <= len(title) <= 100 or '<' in title or '>' in title:
            raise PublicationError('Vídeo MP4 e título válido de até 100 caracteres são necessários.')
        if privacy not in PRIVACY:
            raise PublicationError('Privacidade inválida.')
        token = self.read('token.json')
        if not token.get('refresh_token') or not token.get('channel_id'):
            raise PublicationError('Conecte o canal do YouTube no painel administrativo.')
        if channel_id and token['channel_id'] != channel_id:
            raise PublicationError('O canal conectado mudou. Revise as opções antes de publicar.')
        if playlist_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', playlist_id):
            raise PublicationError('Identificador de playlist inválido.')
        digest = hashlib.sha256(json.dumps([token['channel_id'], playlist_id, privacy,
            (requester or {}).get('username', '')], ensure_ascii=False).encode())
        with video.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        identity = digest.hexdigest()
        with self.lock:
            jobs = self.read('jobs.json', [])
            existing = next((j for j in jobs if j['identity'] == identity), None)
            if existing:
                return self.public_job(existing)
            job_id = secrets.token_hex(12)
            folder = self.root / 'covers'
            folder.mkdir(parents=True, exist_ok=True)
            cover = folder / (job_id + '.jpg')
            if thumbnail:
                data = thumbnail
                if len(data) > 2 * 1024 * 1024 or not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n')):
                    raise PublicationError('A capa deve ser JPEG ou PNG de até 2 MB.')
                cover = folder / (job_id + ('.png' if data.startswith(b'\x89PNG') else '.jpg'))
                cover.write_bytes(data)
            else:
                import shutil
                shutil.copyfile(video_thumbnail(video, cover=True), cover)
            job = {'id': job_id, 'identity': identity, 'video': str(video), 'thumbnail': str(cover),
                   'title': title, 'privacy': privacy, 'playlist_id': playlist_id, 'channel_id': token['channel_id'],
                   'status': 'queued', 'progress': 0, 'created_at': time.time(), 'requester': requester}
            jobs.append(job)
            self.save('jobs.json', jobs)
        self.start()
        return self.public_job(job)

    def enqueue_automatic(self, video, original_title, options):
        title = options.get('title_override') or options['title_template'].replace('{title}', original_title)[:100]
        return self.enqueue(video, title, options['privacy'], options.get('playlist_id', ''), channel_id=options['channel_id'], requester=options.get('requester'))

    @staticmethod
    def public_job(job):
        return {key: job.get(key) for key in ('id', 'title', 'privacy', 'playlist_id', 'status', 'progress',
                                             'video_id', 'actual_privacy', 'error', 'created_at')}

    def checkpoint(self, job, **updates):
        with self.lock:
            job.update(updates)
            jobs = self.read('jobs.json', [])
            for index, item in enumerate(jobs):
                if item['id'] == job['id']:
                    jobs[index] = job
                    break
            self.save('jobs.json', jobs)

    def upload_request(self, method, url, **kwargs):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com':
            raise PublicationError('Sessão de envio inválida.')
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = 'Bearer ' + self.token()['access_token']
        return requests.request(method, url, headers=headers, timeout=(15, 120), **kwargs)

    def upload_video(self, job):
        if job.get('video_id'):
            return job['video_id']
        size = Path(job['video']).stat().st_size
        if not job.get('upload_uri'):
            response = self.upload_request('POST', UPLOAD + '/videos', params={
                'uploadType': 'resumable', 'part': 'snippet,status', 'notifySubscribers': 'false'},
                headers={'X-Upload-Content-Length': str(size), 'X-Upload-Content-Type': 'video/mp4'},
                json={'snippet': {'title': job['title'], 'categoryId': '10'},
                      'status': {'privacyStatus': 'private'}})
            if response.status_code not in (200, 201) or not response.headers.get('Location'):
                raise PublicationError(f'Não foi possível iniciar o envio (HTTP {response.status_code}).')
            self.checkpoint(job, upload_uri=response.headers['Location'], status='uploading')
        # Probe persisted sessions, including uncertain responses after a connection loss.
        offset = 0
        response = self.upload_request('PUT', job['upload_uri'], headers={'Content-Range': f'bytes */{size}', 'Content-Length': '0'})
        if response.status_code in (200, 201):
            return self.completed_upload(job, response)
        if response.status_code != 308:
            raise PublicationError('A sessão de envio expirou ou foi recusada. Verifique o canal antes de iniciar outro envio.')
        offset = uploaded_offset(response)
        failures = 0
        with open(job['video'], 'rb') as media:
            while offset < size:
                media.seek(offset)
                chunk = media.read(min(CHUNK, size - offset))
                try:
                    response = self.upload_request('PUT', job['upload_uri'], data=chunk,
                        headers={'Content-Type': 'video/mp4', 'Content-Length': str(len(chunk)),
                                 'Content-Range': f'bytes {offset}-{offset + len(chunk) - 1}/{size}'})
                    if response.status_code in (200, 201):
                        return self.completed_upload(job, response)
                    if response.status_code != 308:
                        raise requests.RequestException('Upload chunk rejected')
                    next_offset = uploaded_offset(response)
                    if next_offset <= offset:
                        raise requests.RequestException('No upload progress')
                    offset = next_offset
                    failures = 0
                    self.checkpoint(job, progress=round(offset * 90 / size))
                except requests.RequestException:
                    failures += 1
                    if failures > 3:
                        raise PublicationError('O envio perdeu a conexão. Use Retomar para continuar a mesma sessão.')
                    time.sleep(min(2 ** failures, 8))
                    response = self.upload_request('PUT', job['upload_uri'], headers={'Content-Range': f'bytes */{size}', 'Content-Length': '0'})
                    if response.status_code in (200, 201):
                        return self.completed_upload(job, response)
                    if response.status_code != 308:
                        raise PublicationError('Não foi possível retomar a sessão. Verifique o canal antes de reenviar.')
                    offset = uploaded_offset(response)
        raise PublicationError('O YouTube não confirmou a conclusão do envio. Retome a mesma sessão.')

    def completed_upload(self, job, response):
        video_id = response.json().get('id', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise PublicationError('O YouTube não retornou o identificador do vídeo.')
        self.checkpoint(job, video_id=video_id, status='finalizing', progress=90)
        return video_id

    def publish(self, job):
        requester = job.get('requester')
        if requester:
            user = self.user_lookup(requester['username']) if hasattr(self, 'user_lookup') else requester
            if not user:
                raise PublicationError('A conta que solicitou a publicação não está mais disponível.')
            self.publication_options(user, True, job['playlist_id'], job['title'])
        if self.token()['channel_id'] != job['channel_id']:
            raise PublicationError('O canal conectado mudou. A publicação foi interrompida.')
        if job['playlist_id'] and not job.get('playlist_done'):
            if job['playlist_id'] not in {p['id'] for p in self.playlists()}:
                raise PublicationError('A playlist não pertence ao canal conectado.')
        video_id = self.upload_video(job)
        if not job.get('thumbnail_done'):
            with open(job['thumbnail'], 'rb') as cover:
                response = self.upload_request('POST', UPLOAD + '/thumbnails/set', params={'videoId': video_id},
                    data=cover, headers={'Content-Type': 'image/png' if job['thumbnail'].endswith('.png') else 'image/jpeg'})
            if response.status_code != 200:
                raise PublicationError('O vídeo está privado, mas a capa não foi aplicada. Verifique se o canal permite miniaturas personalizadas e retome.')
            self.checkpoint(job, thumbnail_done=True, progress=94)
        if job['playlist_id'] and not job.get('playlist_done'):
            items = self.api('GET', '/playlistItems', params={'part': 'id', 'playlistId': job['playlist_id'], 'videoId': video_id})
            if not items.get('items'):
                self.api('POST', '/playlistItems', params={'part': 'snippet'}, json={'snippet': {
                    'playlistId': job['playlist_id'], 'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}})
            self.checkpoint(job, playlist_done=True, progress=97)
        response = self.api('PUT', '/videos', params={'part': 'status'}, json={
            'id': video_id, 'status': {'privacyStatus': job['privacy']}})
        actual = response.get('status', {}).get('privacyStatus')
        if actual != job['privacy']:
            self.checkpoint(job, actual_privacy=actual)
            raise PublicationError('O YouTube manteve uma privacidade diferente. Projetos de API sem auditoria podem ficar restritos a privado.')
        self.checkpoint(job, status='done', actual_privacy=actual, progress=100, error=None)

    def work(self):
        if not self.worker_lock.acquire(blocking=False):
            return
        try:
            while True:
                job = next((j for j in self.read('jobs.json', []) if j['status'] in {'queued', 'uploading', 'finalizing'}), None)
                if not job:
                    return
                try:
                    self.publish(job)
                except Exception as error:
                    message = str(error) if isinstance(error, PublicationError) else 'Falha de comunicação com o YouTube. Retome a tarefa pelo painel.'
                    self.checkpoint(job, status='error', error=message)
        finally:
            self.worker_lock.release()
            # An enqueue can race the worker's final empty-queue check.
            if any(j['status'] in {'queued', 'uploading', 'finalizing'} for j in self.read('jobs.json', [])):
                self.start()

    def start(self):
        threading.Thread(target=self.work, name='youtube-publisher', daemon=True).start()

    def retry(self, job_id):
        with self.lock:
            jobs = self.read('jobs.json', [])
            job = next((j for j in jobs if j['id'] == job_id), None)
            if not job or job['status'] != 'error':
                raise PublicationError('Não há envio com erro para retomar.')
            self.checkpoint(job, status='queued', error=None)
        self.start()


def install_routes(app, get_current_user, require_admin, resolve_video, check_admin, user_lookup=None):
    from fastapi import Depends, HTTPException, UploadFile, File, Form
    from fastapi.responses import HTMLResponse
    publisher = YouTubePublisher()
    publisher.user_lookup = user_lookup or (lambda username: None)

    def admin(user=Depends(get_current_user)):
        require_admin(user)
        return user

    def guarded(action):
        try:
            return action()
        except PublicationError as error:
            raise HTTPException(400, str(error))
        except requests.RequestException:
            raise HTTPException(502, 'O YouTube não respondeu. Tente novamente.')

    @app.get('/api/youtube/publication-options')
    def quick_options(user=Depends(get_current_user)):
        return guarded(lambda: publisher.quick_options(user))

    @app.get('/api/admin/youtube/desktop-helper')
    def desktop_helper(platform: str = "python", user=Depends(admin)):
        from fastapi.responses import FileResponse
        if platform == 'windows':
            executable = Path(__file__).with_name('Sal0-YouTube-Conectar.exe')
            if not executable.is_file():
                raise HTTPException(status_code=404, detail='Assistente Windows indisponível nesta instalação. Use a alternativa Python.')
            return FileResponse(executable, media_type='application/octet-stream', filename=executable.name, headers={'Cache-Control': 'no-store'})
        return FileResponse(Path(__file__).with_name('youtube_desktop_oauth.py'),
            media_type='text/x-python', filename='youtube_desktop_oauth.py', headers={'Cache-Control': 'no-store'})

    @app.post('/api/admin/youtube/import-authorization')
    def import_authorization(authorization: UploadFile = File(...), user=Depends(admin)):
        raw = authorization.file.read(32769)
        if len(raw) > 32768:
            raise HTTPException(400, 'O arquivo de autorização deve ter até 32 KB.')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, 'Escolha um arquivo JSON de autorização válido.')
        return guarded(lambda: {'channel_title': publisher.import_desktop_authorization(data)})

    @app.get('/api/admin/youtube/status')
    def status(user=Depends(admin)):
        token = publisher.read('token.json')
        return {'configured': True, 'web_configured': all(os.environ.get(k) for k in ('YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REDIRECT_URI')),
                'connected': bool(token.get('refresh_token')), 'channel_title': token.get('channel_title', ''),
                'settings': publisher.settings(user['username']),
                'jobs': [publisher.public_job(j) for j in publisher.read('jobs.json', [])][-30:]}

    @app.post('/api/admin/youtube/connect')
    def connect(user=Depends(admin)):
        return guarded(lambda: {'url': publisher.authorize(user['username'])})

    @app.get('/api/admin/youtube/callback')
    def callback(state: str = '', code: str = '', error: str = ''):
        import html
        try:
            if error or not code:
                raise PublicationError('Conexão recusada. Volte ao app e tente novamente.')
            channel = publisher.finish_authorization(state, code, check_admin)
            message = 'Canal conectado: ' + channel + '. Volte ao Sal0 Karaokê e atualize o painel.'
        except Exception:
            message = 'Não foi possível concluir a conexão. Volte ao app e conecte novamente.'
        return HTMLResponse('<html><meta name="viewport" content="width=device-width"><body><p>' + html.escape(message) + '</p><a href="/">Voltar ao Sal0 Karaokê</a></body></html>',
                            headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})

    @app.get('/api/admin/youtube/playlists')
    def playlists(user=Depends(admin)):
        return guarded(lambda: {'playlists': publisher.playlists()})

    @app.post('/api/admin/youtube/settings')
    def settings(options: dict, user=Depends(admin)):
        guarded(lambda: publisher.save_settings(user['username'], options))
        return {'status': 'saved'}

    @app.post('/api/admin/youtube/publish')
    def publish(owner_key: str = Form(...), filename: str = Form(...), title: str = Form(...),
                privacy: str = Form('private'), playlist_id: str = Form(''),
                cover: UploadFile = File(None), user=Depends(admin)):
        video = resolve_video(owner_key, filename, user)
        data = cover.file.read(2 * 1024 * 1024 + 1) if cover else None
        return guarded(lambda: publisher.enqueue(video, title, privacy, playlist_id, data))

    @app.post('/api/admin/youtube/cover')
    def preview_cover(options: dict, user=Depends(admin)):
        from fastapi.responses import FileResponse
        video = resolve_video(options.get('owner_key', ''), options.get('filename', ''), user)
        title = str(options.get('title') or Path(video).stem)[:100]
        cover = video_thumbnail(video, cover=True)
        return FileResponse(cover, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.post('/api/admin/youtube/jobs/{job_id}/retry')
    def retry(job_id: str, user=Depends(admin)):
        guarded(lambda: publisher.retry(job_id))
        return {'status': 'queued'}

    @app.on_event('startup')
    def resume_uploads():
        publisher.start()

    return publisher
