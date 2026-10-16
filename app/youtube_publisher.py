"""Admin-only OAuth and a durable, resumable YouTube publication queue."""
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
from media_covers import video_thumbnail
from result_publication import youtube_eligible
from youtube_device_auth import AuthorizationError, DeviceAuthorization, DEVICE_SCOPE, oauth_error

API = 'https://www.googleapis.com/youtube/v3'
UPLOAD = 'https://www.googleapis.com/upload/youtube/v3'
SCOPE = 'https://www.googleapis.com/auth/youtube.force-ssl'
PRIVACY = {'private', 'unlisted', 'public'}
CHUNK = 8 * 1024 * 1024


PublicationError = AuthorizationError
logger = logging.getLogger(__name__)


def json_object(response):
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        raise PublicationError('O Google retornou uma resposta inválida. Tente atualizar o painel novamente.', 'retry_later')
    return payload


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
        self._device = None
        self.on_published = None
        self.on_auth_required = None
        self._auth_alert_pending = set()

    def notify_auth_required(self, message=None):
        """Notify administrators once per expired grant; delivery never blocks uploads."""
        with self.lock:
            token = self.read('token.json')
            if not token.get('refresh_token') or not token.get('channel_id'):
                return
            token['auth_error'] = message or token.get('auth_error') or 'Reconecte o canal do YouTube.'
            episode = token.setdefault('auth_alert_episode', secrets.token_hex(12))
            self.save('token.json', token)
            if not self.on_auth_required or token.get('auth_alert_notified_at') or episode in self._auth_alert_pending:
                return
            self._auth_alert_pending.add(episode)
            event = {'channel_title': token.get('channel_title', ''),
                     'pending_count': sum(job.get('status') in {'queued', 'uploading', 'finalizing', 'auth_required'}
                                          for job in self.read('jobs.json', []))}
        threading.Thread(target=self._deliver_auth_alert, args=(episode, event),
                         name='youtube-auth-alert', daemon=True).start()

    def _deliver_auth_alert(self, episode, event):
        try:
            delivered = self.on_auth_required(event)
            with self.lock:
                token = self.read('token.json')
                if delivered and token.get('auth_error') and token.get('auth_alert_episode') == episode:
                    token['auth_alert_notified_at'] = time.time()
                    self.save('token.json', token)
        except Exception as error:
            logger.warning('Alerta de renovação do YouTube pendente (%s).', type(error).__name__)
        finally:
            with self.lock:
                self._auth_alert_pending.discard(episode)

    @property
    def device(self):
        if self._device is None or self._device.root != self.root:
            self._device = DeviceAuthorization(self.root, write_private_json, self.accept_device_token)
        return self._device

    def save_authorization(self, token):
        """A renewal of the same channel must not be blocked by its own queue."""
        with self.lock:
            jobs = self.read('jobs.json', [])
            if any(job.get('channel_id') != token['channel_id'] and
                   job.get('status') in {'queued', 'uploading', 'finalizing', 'auth_required'} for job in jobs):
                raise PublicationError('Há envios pendentes para outro canal. Reconecte a mesma conta para retomá-los.')
            token.pop('auth_error', None)
            token.pop('refresh_retry_at', None)
            token.pop('auth_alert_episode', None)
            token.pop('auth_alert_notified_at', None)
            token['checked_at'] = time.time()
            token['grant_revision'] = secrets.token_hex(12)
            self.save('token.json', token)
            resumed = False
            for job in jobs:
                # Keep the resumable session and any confirmed video ID intact.
                recoverable = (job.get('status') == 'auth_required' or
                    job.get('status') == 'error' and (job.get('error_kind') in {'auth_required', 'upload_session_expired'} or
                    job.get('error') in {'A sessão de envio expirou ou foi recusada. Verifique o canal antes de iniciar outro envio.',
                                         'Não foi possível retomar a sessão. Verifique o canal antes de reenviar.'}))
                if recoverable and job.get('channel_id') == token['channel_id']:
                    job.update(status='queued', error=None, error_kind=None)
                    resumed = True
            if resumed:
                self.save('jobs.json', jobs)
                self.start()

    def accept_device_token(self, token, config):
        if not token.get('access_token') or not token.get('refresh_token'):
            raise PublicationError('O Google não concedeu a autorização completa. Gere outro código.', 'auth_required')
        scopes = token.get('scope', '')
        if DEVICE_SCOPE not in str(scopes).split():
            raise PublicationError('Permita o acesso ao YouTube solicitado pelo Google e tente novamente.', 'auth_required')
        expires_at = token.get('expires_at', time.time() + token.get('expires_in', 3600))
        if expires_at <= time.time() + 60:
            response = requests.post('https://oauth2.googleapis.com/token', data={
                **config, 'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'}, timeout=20)
            if response.status_code != 200:
                raise oauth_error(response)
            updated = json_object(response)
            if not updated.get('access_token'):
                raise PublicationError('O Google não retornou um acesso válido. Tente reconectar.', 'auth_required')
            token.update(updated)
            expires_at = time.time() + updated.get('expires_in', 3600)
            token['expires_at'] = expires_at
        item = self.confirm_channel(token['access_token'])
        token.update(channel_id=item['id'], channel_title=item['snippet']['title'],
            expires_at=expires_at,
            oauth_client=config, authorization_method='device')
        self.save_authorization(token)
        return token['channel_title']

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
            if response.status_code == 401:
                raise PublicationError('O Google recusou o acesso ao canal. Use Reconectar canal no app.', 'auth_required')
            raise PublicationError('O Google não autorizou a conexão. Tente novamente.')
        token = json_object(response)
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
        self.save_authorization(token)
        return token['channel_title']

    def confirm_channel(self, access_token):
        response = requests.get(API + '/channels', params={'part': 'snippet', 'mine': 'true'},
            headers={'Authorization': 'Bearer ' + access_token}, timeout=30)
        if response.status_code != 200:
            if response.status_code == 401:
                raise PublicationError('O Google recusou o acesso ao canal. Use Reconectar canal no app.', 'auth_required')
            reason = ''
            try:
                reason = response.json().get('error', {}).get('errors', [{}])[0].get('reason', '')
            except (ValueError, TypeError, AttributeError, IndexError):
                pass
            if reason in {'accessNotConfigured', 'serviceDisabled'}:
                raise PublicationError('Ative a YouTube Data API v3 no mesmo projeto Google da credencial e tente conectar novamente.')
            if reason in {'insufficientPermissions', 'forbidden'}:
                raise PublicationError('O Google negou a consulta do canal. Autorize novamente usando a conta do canal e permita o acesso solicitado.', 'auth_required')
            if reason == 'quotaExceeded':
                raise PublicationError('A cota diária da API do YouTube foi atingida. Aguarde a renovação e tente novamente.')
            raise PublicationError(f'O Google não confirmou o canal (HTTP {response.status_code}). Confira se a YouTube Data API v3 está ativa no projeto da credencial.')
        items = json_object(response).get('items', [])
        if not isinstance(items, list) or (items and (not isinstance(items[0], dict) or
                not isinstance(items[0].get('id'), str) or not isinstance(items[0].get('snippet'), dict) or
                not isinstance(items[0]['snippet'].get('title'), str))):
            raise PublicationError('O Google não retornou dados válidos do canal. Tente verificar novamente.', 'retry_later')
        if not items:
            raise PublicationError('A conta autorizada não possui um canal disponível. Abra o YouTube com essa conta, crie ou selecione seu canal e autorize novamente.')
        return items[0]

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
        token = json_object(response)
        if not isinstance(token.get('access_token'), str) or not token['access_token']:
            raise PublicationError('O Google não retornou uma autorização válida. Gere um novo arquivo no assistente.')
        # Refresh replies can omit scope. Confirm it with Google rather than rejecting
        # a valid connection or trusting the imported file.
        scopes = token.get('scope')
        if scopes is None:
            info = requests.get('https://oauth2.googleapis.com/tokeninfo', params={'access_token': token['access_token']}, timeout=30)
            if info.status_code != 200:
                raise PublicationError('Não foi possível validar as permissões no Google. Tente novamente.')
            scopes = info.json().get('scope', '')
        if not {SCOPE, DEVICE_SCOPE}.intersection(str(scopes).split()):
            raise PublicationError('A autorização não permite gerenciar vídeos e playlists. Gere um novo arquivo no assistente e permita o acesso solicitado.')
        item = self.confirm_channel(token['access_token'])
        token.update(refresh_token=data['refresh_token'], channel_id=item['id'],
            channel_title=item['snippet']['title'], expires_at=time.time() + token.get('expires_in', 3600),
            desktop_client={key: data[key] for key in ('client_id', 'client_secret')})
        self.save_authorization(token)
        return token['channel_title']

    def token(self, force_refresh=False):
        with self.lock:
            token = self.read('token.json')
            if not token.get('refresh_token'):
                raise PublicationError('Conecte o canal do YouTube no painel administrativo.')
            if token.get('auth_error') and not force_refresh:
                self.notify_auth_required(token['auth_error'])
                raise PublicationError(token['auth_error'], 'auth_required')
            if token.get('refresh_retry_at', 0) > time.time() and not force_refresh:
                raise PublicationError('O Google não respondeu à renovação. Use Verificar e renovar para tentar novamente.', 'retry_later')
            if force_refresh or token.get('expires_at', 0) <= time.time() + 60:
                config = token.get('oauth_client') or token.get('desktop_client') or self.client_config()
                response = requests.post('https://oauth2.googleapis.com/token', data={
                    'client_id': config['client_id'], 'client_secret': config['client_secret'],
                    'refresh_token': token['refresh_token'], 'grant_type': 'refresh_token'}, timeout=30)
                if response.status_code != 200:
                    error = oauth_error(response)
                    if error.kind == 'auth_required':
                        token['auth_error'] = str(error)
                    else:
                        token['refresh_retry_at'] = time.time() + 60
                    self.save('token.json', token)
                    if error.kind == 'auth_required':
                        self.notify_auth_required(str(error))
                    raise error
                updated = json_object(response)
                if not updated.get('access_token'):
                    raise PublicationError('O Google não retornou uma autorização válida. Tente verificar novamente.', 'retry_later')
                token.update(updated)
                token['expires_at'] = time.time() + updated.get('expires_in', 3600)
                token['checked_at'] = time.time()
                token.pop('auth_error', None)
                token.pop('refresh_retry_at', None)
                token.pop('auth_alert_episode', None)
                token.pop('auth_alert_notified_at', None)
                self.save('token.json', token)
            return token

    def connection_status(self, force=False):
        # Do not overwrite a newly approved grant with a delayed check result.
        with self.lock:
            return self._connection_status(force)

    def _connection_status(self, force=False):
        saved = self.read('token.json')
        result = dict(connected=False, channel_title=saved.get('channel_title', ''), channel_id=saved.get('channel_id', ''),
            connection_state='not_connected', message='Conecte seu canal para publicar vídeos.', recovery='connect')
        if not saved.get('refresh_token'):
            return result
        try:
            token = self.token(force_refresh=force)
            if force:
                item = self.confirm_channel(token['access_token'])
                if item['id'] != token.get('channel_id'):
                    raise PublicationError('A conta autorizada mudou de canal. Reconecte e confira o destino.', 'auth_required')
                self.save_authorization(token)
            result.update(connected=True, channel_title=token.get('channel_title', ''),
                connection_state='connected', message='Canal conectado: ' + token.get('channel_title', ''), recovery=None)
        except PublicationError as error:
            if error.kind == 'auth_required':
                latest = self.read('token.json')
                latest['auth_error'] = str(error)
                self.save('token.json', latest)
                self.notify_auth_required(str(error))
            elif error.kind == 'retry_later':
                latest = self.read('token.json')
                if latest.get('refresh_retry_at', 0) <= time.time():
                    latest['refresh_retry_at'] = time.time() + 60
                    self.save('token.json', latest)
            result.update(connection_state=error.kind, message=str(error), recovery=error.kind)
        except requests.RequestException:
            latest = self.read('token.json')
            latest['refresh_retry_at'] = time.time() + 60
            self.save('token.json', latest)
            result.update(connection_state='network_error', message='O Google não respondeu. Sua autorização foi preservada; tente Verificar e renovar.', recovery='retry_later')
        return result

    def authenticated_request(self, method, url, timeout, **kwargs):
        # OAuth is for YouTube only: never forward it to other Google APIs or redirects.
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'www.googleapis.com' or
                not parsed.path.startswith(('/youtube/v3/', '/upload/youtube/v3/')) or
                any(part in {'.', '..'} for part in parsed.path.split('/')) or '%' in parsed.path):
            raise PublicationError('Endereço fora da API do YouTube bloqueado.')
        kwargs['allow_redirects'] = False
        headers = dict(kwargs.pop('headers', {}))
        body = kwargs.get('data')
        body_position = body.tell() if hasattr(body, 'tell') and hasattr(body, 'seek') else None
        for attempt in range(2):
            if attempt and body_position is not None:
                body.seek(body_position)
            headers['Authorization'] = 'Bearer ' + self.token(force_refresh=bool(attempt))['access_token']
            response = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
            if response.status_code == 403:
                try:
                    reason = response.json()['error']['errors'][0]['reason']
                except (ValueError, TypeError, AttributeError, KeyError, IndexError):
                    reason = ''
                if reason in {'quotaExceeded', 'dailyLimitExceeded'}:
                    raise PublicationError('A cota diária do YouTube foi atingida. Aguarde a renovação; sua conexão foi preservada.', 'quota_exceeded')
                if reason == 'insufficientPermissions':
                    message = 'O Google não permitiu o envio. Reconecte o canal e permita o acesso solicitado.'
                    self.notify_auth_required(message)
                    raise PublicationError(message, 'auth_required')
            if response.status_code != 401:
                return response
        token = self.read('token.json')
        token['auth_error'] = 'O Google recusou o acesso ao canal. Use Reconectar canal no app.'
        self.save('token.json', token)
        self.notify_auth_required(token['auth_error'])
        raise PublicationError(token['auth_error'], 'auth_required')

    def api(self, method, path, validate=None, **kwargs):
        reading = method.upper() == 'GET'
        for attempt in range(2 if reading else 1):
            try:
                response = self.authenticated_request(method, API + path, (10, 15) if reading else (15, 60), **kwargs)
                if response.status_code >= 400:
                    if reading and attempt == 0 and response.status_code >= 500:
                        continue
                    try:
                        reason = response.json()['error']['errors'][0]['reason']
                    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
                        reason = 'apiError'
                    messages = {
                        'quotaExceeded':'A cota diária do YouTube foi atingida. Aguarde a renovação; sua conexão foi preservada.',
                        'dailyLimitExceeded':'A cota diária do YouTube foi atingida. Aguarde a renovação; sua conexão foi preservada.',
                        'accessNotConfigured':'Ative a YouTube Data API v3 no projeto Google da credencial.',
                        'serviceDisabled':'Ative a YouTube Data API v3 no projeto Google da credencial.',
                        'insufficientPermissions':'O Google não permitiu consultar ou gerenciar playlists. Reconecte e permita o acesso solicitado.',
                    }
                    kind = ('auth_required' if reason == 'insufficientPermissions' else
                            'quota_exceeded' if reason in {'quotaExceeded', 'dailyLimitExceeded'} else 'api_error')
                    if kind == 'auth_required':
                        self.notify_auth_required(messages[reason])
                    raise PublicationError(messages.get(str(reason), f'O YouTube recusou a solicitação (HTTP {response.status_code}).'), kind)
                if method.upper() == "DELETE" and response.status_code == 204:
                    return {}
                payload = json_object(response)
                if validate:
                    validate(payload)
                return payload
            except requests.RequestException:
                if not reading or attempt:
                    raise PublicationError('O YouTube não respondeu. Tente atualizar o painel novamente.', 'retry_later') from None
            except PublicationError as error:
                if not reading or attempt or error.kind != 'retry_later':
                    raise

    @staticmethod
    def validate_playlist_page(payload):
        items = payload.get('items', [])
        if not isinstance(items, list) or any(not isinstance(item, dict) or
                not isinstance(item.get('id'), str) or not item['id'] or
                not isinstance(item.get('snippet'), dict) or
                not isinstance(item['snippet'].get('title'), str) for item in items):
            raise PublicationError('O YouTube retornou dados inválidos das playlists. Toque em Atualizar playlists para tentar novamente.', 'retry_later')
        if payload.get('nextPageToken') is not None and not isinstance(payload['nextPageToken'], str):
            raise PublicationError('O YouTube retornou uma paginação inválida. Tente atualizar as playlists novamente.', 'retry_later')

    def playlists(self):
        result, page, seen = [], None, set()
        while True:
            payload = self.api('GET', '/playlists', validate=self.validate_playlist_page, params={
                'part': 'snippet,status', 'mine': 'true', 'maxResults': 50,
                **({'pageToken': page} if page else {})})
            result.extend({'id': item['id'], 'title': item['snippet']['title']} for item in payload.get('items', []))
            page = payload.get('nextPageToken')
            if not page:
                return result
            if page in seen:
                raise PublicationError('O YouTube repetiu uma página de playlists. Tente atualizar as playlists novamente.', 'retry_later')
            seen.add(page)

    def settings(self, username):
        settings = self.read('settings.json')
        return {**{'playlist_id': '', 'title_template': '{title} | Karaokê'},
                **settings.get('defaults', {}), 'privacy': 'unlisted', 'default_publish': True,
                'users_can_publish': True,
                'user_assignments': settings.get('user_assignments', {})}

    def save_settings(self, username, options):
        if not isinstance(options.get('default_publish', True), bool):
            raise PublicationError('A marcação padrão de publicação deve ser verdadeira ou falsa.')
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
            validated[name] = {'enabled': True,
                               'playlist_id': playlist_id,
                               'default_publish': True}
        selected = [value['playlist_id'] for value in validated.values() if value['playlist_id']]
        default_playlist = options.get('playlist_id', '')
        available = {p['id']: p for p in self.playlists()} if selected or default_playlist else {}
        if any(value not in available for value in selected) or (default_playlist and default_playlist not in available):
            raise PublicationError('Selecione playlists do canal conectado.')
        for assignment in validated.values():
            assignment['playlist_title'] = available.get(assignment['playlist_id'], {}).get('title', '')
        if options.get('users_can_publish'):
            self.token()
        self.save('settings.json', {'defaults': {'privacy': 'unlisted', 'default_publish': True,
                    'playlist_id': default_playlist, 'title_template': template},
                    'users_can_publish': True,
                    'user_assignments': validated})

    def validate_profile_playlist(self, user, playlist_id=''):
        settings = self.settings(user.get('username'))
        admin = user.get('role') == 'admin'
        assigned = settings['playlist_id'] if admin else settings['user_assignments'].get(user.get('username'), {}).get('playlist_id', '')
        if not assigned:
            raise PublicationError('Defina uma playlist no perfil antes de publicar no YouTube.')
        selected = playlist_id or assigned
        if not isinstance(selected, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', selected):
            raise PublicationError('Identificador de playlist inválido.')
        if not admin and selected != assigned:
            raise PublicationError('Use a playlist atribuída à sua conta pelo administrador.')
        return selected

    def validate_additional_playlists(self, values, primary):
        if values is None:
            return []
        if not isinstance(values, list) or len(values) > 20 or any(
                not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) for value in values):
            raise PublicationError('Escolha até 20 playlists adicionais válidas.')
        values = list(dict.fromkeys(value for value in values if value != primary))
        if values and not set(values).issubset({item['id'] for item in self.playlists()}):
            raise PublicationError('Uma playlist adicional não pertence ao canal conectado.')
        return values

    def replacement_for(self, video):
        path = str(Path(video).resolve())
        with self.lock:
            jobs = self.read('jobs.json', [])
            found = next((item for item in reversed(jobs) if item.get('status') == 'done'
                and (item.get('video') == path or any(binding.get('video') == path
                     for binding in item.get('telegram_results', [])))), None)
            seen = set()
            while found and found.get('replaced_by') and found['id'] not in seen:
                seen.add(found['id'])
                replacement = next((item for item in jobs if item['id'] == found['replaced_by']
                    and item.get('status') == 'done' and item.get('replacement_done')
                    and item.get('channel_id') == found.get('channel_id')), None)
                if not replacement:
                    break
                found = replacement
            return dict(found) if found else None

    def publication_options(self, user, requested=False, playlist_id='', title='', additional_playlists=None):
        # Every account starts checked in the UI; each video still submits its own choice.
        if not requested:
            return None
        settings = self.settings(user.get('username'))
        playlist_id = self.validate_profile_playlist(user, playlist_id)
        token = self.read('token.json')
        if not token.get('channel_id') or not token.get('refresh_token'):
            raise PublicationError('O administrador precisa conectar o canal do YouTube.')
        if token.get('auth_error'):
            raise PublicationError(token['auth_error'], 'auth_required')
        if len(title) > 100 or '<' in title or '>' in title:
            raise PublicationError('Título do YouTube inválido.')
        additional_playlists = self.validate_additional_playlists(additional_playlists, playlist_id)
        return {'privacy': settings['privacy'], 'title_template': settings['title_template'],
                'additional_playlists': additional_playlists,
                'playlist_id': playlist_id, 'channel_id': token['channel_id'],
                'title_override': title.strip(), 'requester': dict(username=user.get('username'), role=user.get('role'))}

    def quick_options(self, user):
        settings = self.settings(user.get('username'))
        token = self.read('token.json')
        admin = user.get('role') == 'admin'
        assignment = settings['user_assignments'].get(user.get('username'), {})
        enabled = bool(token.get('channel_id') and token.get('refresh_token') and not token.get('auth_error'))
        playlist_id = settings['playlist_id'] if admin else assignment.get('playlist_id', '')
        error = None
        try:
            playlists = self.playlists() if enabled and admin else ([{'id': playlist_id,
                'title': assignment.get('playlist_title', playlist_id)}] if enabled and playlist_id else [])
        except (PublicationError, requests.RequestException) as failure:
            playlists = []
            error = str(failure) if isinstance(failure, PublicationError) else 'O YouTube não respondeu agora.'
            if getattr(failure, 'kind', '') == 'auth_required':
                enabled = False
        return {'enabled': enabled, 'playlists': playlists, 'additional_playlists': playlists if admin else [], 'allow_no_playlist': False, 'can_choose_playlist': admin, 'can_publish': bool(enabled and playlist_id and any(p['id'] == playlist_id for p in playlists)),
                'playlist_id': playlist_id, 'default_publish': bool(enabled and playlist_id and any(p['id'] == playlist_id for p in playlists)),
                'privacy': settings['privacy'], 'channel_title': token.get('channel_title', ''),
                'title_template': settings['title_template'], 'connection_message': error,
                'needs_reconnection': bool(token.get('auth_error') or (error and not enabled))}

    def enqueue(self, video, title, privacy='unlisted', playlist_id='', thumbnail=None, channel_id=None, requester=None, automatic=False, additional_playlists=None, replaces_video_id=None):
        video = Path(video).resolve()
        title = str(title).strip()
        if not youtube_eligible(video):
            raise PublicationError("Resultados do modo SRT nunca podem ser publicados no YouTube. Apenas karaokês com origem confirmada são permitidos.")
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
        playlist_id = self.validate_profile_playlist(requester or {'role':'admin'}, playlist_id)
        additional_playlists = self.validate_additional_playlists(additional_playlists, playlist_id)
        previous = None
        if replaces_video_id:
            previous = next((item for item in self.read('jobs.json', []) if item.get('video_id') == replaces_video_id
                             and item.get('status') == 'done' and item.get('channel_id') == token['channel_id']), None)
            if not previous:
                raise PublicationError('Não foi possível confirmar a publicação anterior deste canal.')
        digest = hashlib.sha256(json.dumps([token['channel_id'], playlist_id, privacy, additional_playlists, replaces_video_id,
            (requester or {}).get('username', '')], ensure_ascii=False).encode())
        with video.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        identity = digest.hexdigest()
        with self.lock:
            jobs = self.read('jobs.json', [])
            existing = next((j for j in jobs if j['identity'] == identity), None)
            if existing:
                bindings = existing.setdefault('telegram_results',
                    [{'video': existing['video'], 'automatic': bool(existing.get('automatic'))}]
                    if existing.get('telegram_link_enabled') else [])
                binding = next((item for item in bindings if item['video'] == str(video)), None)
                if binding:
                    binding['automatic'] = bool(binding.get('automatic')) and automatic
                else:
                    bindings.append({'video': str(video), 'automatic': automatic})
                existing['telegram_link_enabled'] = True
                self.save('jobs.json', jobs)
                if existing.get('status') == 'done':
                    threading.Thread(target=self.notify_published, args=(existing,), daemon=True).start()
                self.start()
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
                   'status': 'queued', 'progress': 0, 'created_at': time.time(), 'requester': requester,
                   'automatic': automatic, 'telegram_link_enabled': True,
                   'telegram_results': [{'video': str(video), 'automatic': automatic}],
                   'playlist_ids': [playlist_id, *additional_playlists], 'replaces_video_id': replaces_video_id}
            if previous:
                for binding in previous.get('telegram_results') or [{'video': previous['video']}]:
                    if binding['video'] != str(video):
                        job['telegram_results'].append({**binding, 'automatic': True})
            jobs.append(job)
            self.save('jobs.json', jobs)
        self.start()
        return self.public_job(job)

    def enqueue_automatic(self, video, original_title, options):
        title = options.get('title_override') or options['title_template'].replace('{title}', original_title)[:100]
        return self.enqueue(video, title, options['privacy'], options.get('playlist_id', ''), channel_id=options['channel_id'], requester=options.get('requester'), automatic=True, additional_playlists=options.get('additional_playlists'), replaces_video_id=options.get('replaces_video_id'))

    @staticmethod
    def public_job(job):
        return {key: job.get(key) for key in ('id', 'title', 'privacy', 'playlist_id', 'status', 'progress',
                                             'video_id', 'actual_privacy', 'error', 'created_at', 'playlist_ids', 'replaces_video_id', 'replacement_done')}

    def checkpoint(self, job, **updates):
        with self.lock:
            job.update(updates)
            jobs = self.read('jobs.json', [])
            for index, item in enumerate(jobs):
                if item['id'] == job['id']:
                    # Another result can reuse this upload while the worker is active.
                    if 'telegram_results' in item:
                        job['telegram_results'] = item['telegram_results']
                        job['telegram_link_enabled'] = True
                    if item.get('replaced_by'):
                        job['replaced_by'] = item['replaced_by']
                        job['telegram_link_enabled'] = False
                    jobs[index] = job
                    break
            self.save('jobs.json', jobs)

    def upload_request(self, method, url, **kwargs):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'www.googleapis.com':
            raise PublicationError('Sessão de envio inválida.')
        return self.authenticated_request(method, url, (15, 120), **kwargs)

    def upload_video(self, job):
        # A renewed OAuth grant cannot revive an expired resumable upload URI.
        for attempt in range(2):
            try:
                return self._upload_video_session(job)
            except PublicationError as error:
                if error.kind != 'upload_session_expired' or attempt or job.get('video_id'):
                    raise
                self.checkpoint(job, upload_uri=None, progress=0, status='uploading')

    def _upload_video_session(self, job):
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
        if response.status_code in (404, 410):
            raise PublicationError('A sessão de envio expirou; é necessário reiniciar a transferência.', 'upload_session_expired')
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
                    if response.status_code in (404, 410):
                        raise PublicationError('A sessão de envio expirou; é necessário reiniciar a transferência.', 'upload_session_expired')
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
                    if response.status_code in (404, 410):
                        raise PublicationError('A sessão de envio expirou; é necessário reiniciar a transferência.', 'upload_session_expired')
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
        if not youtube_eligible(job["video"]):
            raise PublicationError("Publicação bloqueada: resultados SRT e vídeos sem origem confirmada não podem ir ao YouTube.")
        if not job.get('playlist_id'):
            raise PublicationError('Publicação bloqueada: o vídeo precisa de uma playlist.')
        requester = job.get('requester')
        if requester:
            user = self.user_lookup(requester['username']) if hasattr(self, 'user_lookup') else requester
            if not user:
                raise PublicationError('A conta que solicitou a publicação não está mais disponível.')
            self.publication_options(user, True, job['playlist_id'], job['title'])
            profile_playlist = self.validate_profile_playlist(user)
        if not requester:
            self.validate_profile_playlist({'role':'admin'}, job['playlist_id'])
            profile_playlist = self.validate_profile_playlist({'role':'admin'})
        if self.token()['channel_id'] != job['channel_id']:
            raise PublicationError('O canal conectado mudou. A publicação foi interrompida.')
        targets = list(dict.fromkeys([profile_playlist, *(job.get('playlist_ids') or [job['playlist_id']])]))
        completed = list(job.get('completed_playlists') or ([job['playlist_id']] if job.get('playlist_done') else []))
        if any(playlist not in completed for playlist in targets):
            available_playlists = {p['id'] for p in self.playlists()}
            if not set(targets).issubset(available_playlists):
                raise PublicationError('A playlist não pertence ao canal conectado.')
        video_id = self.upload_video(job)
        if not job.get('thumbnail_done'):
            with open(job['thumbnail'], 'rb') as cover:
                response = self.upload_request('POST', UPLOAD + '/thumbnails/set', params={'videoId': video_id},
                    data=cover, headers={'Content-Type': 'image/png' if job['thumbnail'].endswith('.png') else 'image/jpeg'})
            if response.status_code != 200:
                raise PublicationError('O vídeo está privado, mas a capa não foi aplicada. Verifique se o canal permite miniaturas personalizadas e retome.')
            self.checkpoint(job, thumbnail_done=True, progress=94)
        for playlist in targets:
            if playlist in completed:
                continue
            items = self.api('GET', '/playlistItems', params={'part': 'id', 'playlistId': playlist, 'videoId': video_id})
            if not items.get('items'):
                self.api('POST', '/playlistItems', params={'part': 'snippet'}, json={'snippet': {
                    'playlistId': playlist, 'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}})
            completed.append(playlist)
            self.checkpoint(job, completed_playlists=list(completed), progress=97)
        self.checkpoint(job, playlist_done=True)
        response = self.api('PUT', '/videos', params={'part': 'status'}, json={
            'id': video_id, 'status': {'privacyStatus': job['privacy']}})
        actual = response.get('status', {}).get('privacyStatus')
        if actual != job['privacy']:
            self.checkpoint(job, actual_privacy=actual)
            raise PublicationError('O YouTube manteve uma privacidade diferente. Projetos de API sem auditoria podem ficar restritos a privado.')
        previous_id = job.get('replaces_video_id')
        if previous_id and not job.get('replacement_done'):
            # Follow revisions completed by another job while this one was being rendered.
            prior = next((item for item in self.read('jobs.json', []) if item.get('video_id') == previous_id), None)
            latest = self.replacement_for(prior['video']) if prior else None
            if latest and latest.get('video_id') != previous_id:
                previous_id = latest['video_id']
                self.checkpoint(job, replaces_video_id=previous_id)
            if previous_id == video_id:
                raise PublicationError('Não é possível remover o vídeo que acabou de ser enviado.')
            old = self.api('GET', '/videos', params={'part': 'snippet', 'id': previous_id})
            items = old.get('items')
            if not isinstance(items, list):
                raise PublicationError('Não foi possível confirmar o vídeo anterior. Retome a publicação.')
            if items:
                if len(items) != 1 or items[0].get('id') != previous_id or items[0].get('snippet', {}).get('channelId') != job['channel_id']:
                    raise PublicationError('O vídeo anterior não pertence ao canal conectado. Ele foi preservado.')
                self.api('DELETE', '/videos', params={'id': previous_id})
            self.checkpoint(job, replacement_done=True)
            with self.lock:
                jobs = self.read('jobs.json', [])
                for item in jobs:
                    if item.get('video_id') == previous_id:
                        item['replaced_by'] = job['id']
                        item['telegram_link_enabled'] = False
                self.save('jobs.json', jobs)
        self.checkpoint(job, status='done', actual_privacy=actual, progress=100, error=None,
                        telegram_link_enabled=True, telegram_link_pending=True)
        self.notify_published(job)

    def notify_published(self, job):
        if not self.on_published or job.get('replaced_by') or any(
                item.get('replaced_by') for item in self.read('jobs.json', []) if item.get('id') == job['id']):
            return
        confirmed = True
        bindings = job.get('telegram_results') or [{'video': job['video'], 'automatic': bool(job.get('automatic'))}]
        for binding in bindings:
            try:
                delivered = self.on_published({**job, **binding})
                confirmed = bool(delivered) and confirmed
            except Exception as error:
                # Telegram cannot turn a confirmed YouTube publication into an upload failure.
                confirmed = False
                logger.warning('YouTube publicado; atualização do Telegram pendente (%s).', type(error).__name__)
        self.checkpoint(job, telegram_link_pending=not confirmed)

    def work(self):
        if not self.worker_lock.acquire(blocking=False):
            return
        try:
            for completed in self.read('jobs.json', []):
                if completed.get('status') == 'done' and completed.get('telegram_link_enabled') and not completed.get('replaced_by'):
                    self.notify_published(completed)
            while True:
                job = next((j for j in self.read('jobs.json', []) if j['status'] in {'queued', 'uploading', 'finalizing'}), None)
                if not job:
                    return
                grant_revision = self.read('token.json').get('grant_revision')
                try:
                    self.publish(job)
                except Exception as error:
                    message = str(error) if isinstance(error, PublicationError) else 'Falha de comunicação com o YouTube. Retome a tarefa pelo painel.'
                    kind = getattr(error, 'kind', '')
                    with self.lock:
                        current_token = self.read('token.json')
                        if (kind == 'auth_required' and not current_token.get('auth_error') and
                                current_token.get('grant_revision') != grant_revision):
                            # Consent completed while the old attempt was returning its error.
                            self.checkpoint(job, status='queued', error=None, error_kind=None)
                            continue
                        self.checkpoint(job, status='auth_required' if kind == 'auth_required' else 'error', error=message, error_kind=kind)
                        if kind == 'auth_required':
                            self.notify_auth_required(message)
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
            self.checkpoint(job, status='queued', error=None, error_kind=None)
        self.start()


def install_routes(app, get_current_user, require_admin, resolve_video, check_admin, user_lookup=None, on_published=None, on_auth_required=None):
    from fastapi import Depends, HTTPException, UploadFile, File, Form
    from fastapi.responses import HTMLResponse
    publisher = YouTubePublisher()
    publisher.user_lookup = user_lookup or (lambda username: None)
    publisher.on_published = on_published
    publisher.on_auth_required = on_auth_required

    def admin(user=Depends(get_current_user)):
        require_admin(user)
        return user

    def guarded(action):
        try:
            return action()
        except PublicationError as error:
            raise HTTPException(400, str(error), headers={'X-YouTube-Recovery': error.kind})
        except requests.RequestException:
            raise HTTPException(502, 'O YouTube não respondeu. Tente novamente.')
        except HTTPException:
            raise
        except Exception as error:
            diagnostic = secrets.token_hex(4)
            locations = ' → '.join(f'{Path(frame.filename).name}:{frame.lineno} {frame.name}'
                                   for frame in traceback.extract_tb(error.__traceback__)[-8:])
            logger.error('Falha interna YouTube [%s] %s; %s', diagnostic, type(error).__name__, locations)
            raise HTTPException(500, 'Não foi possível concluir a consulta no servidor. Tente atualizar o painel. Código: ' + diagnostic + '.',
                                headers={'X-YouTube-Diagnostic':diagnostic}) from None

    @app.get('/api/youtube/publication-options')
    def quick_options(user=Depends(get_current_user)):
        return guarded(lambda: publisher.quick_options(user))

    @app.get('/api/youtube/additional-playlists')
    def additional_playlists(user=Depends(get_current_user)):
        def action():
            publisher.validate_profile_playlist(user)
            return {'playlists': publisher.playlists()}
        return guarded(action)

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
        return guarded(lambda: {'configured': True, 'web_configured': all(os.environ.get(k) for k in ('YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REDIRECT_URI')),
                **publisher.connection_status(), 'device_configured': publisher.device.configured(),
                'device_session': publisher.device.status(user['username']),
                'settings': publisher.settings(user['username']),
                'jobs': [publisher.public_job(j) for j in publisher.read('jobs.json', [])][-30:]})

    @app.post('/api/admin/youtube/verify-connection')
    def verify_connection(user=Depends(admin)):
        return guarded(lambda: publisher.connection_status(force=True))

    @app.post('/api/admin/youtube/device/start')
    def device_start(options: dict, user=Depends(admin)):
        return guarded(lambda: publisher.device.start(user['username'], options.get('credentials')))

    @app.post('/api/admin/youtube/device/poll')
    def device_poll(options: dict, user=Depends(admin)):
        check_admin(user['username'])
        return guarded(lambda: publisher.device.poll(user['username'], options.get('session_id', '')))

    @app.post('/api/admin/youtube/device/cancel')
    def device_cancel(options: dict, user=Depends(admin)):
        return guarded(lambda: (publisher.device.cancel(user['username'], options.get('session_id')) or {'status': 'cancelled'}))

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
                privacy: str = Form('unlisted'), playlist_id: str = Form(''),
                cover: UploadFile = File(None), user=Depends(admin)):
        video = resolve_video(owner_key, filename, user)
        data = cover.file.read(2 * 1024 * 1024 + 1) if cover else None
        return guarded(lambda: publisher.enqueue(video, title, privacy, playlist_id, data, requester=user))

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
