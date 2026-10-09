"""Google device consent for a headless server; secrets never reach the UI."""
import json
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

DEVICE_SCOPE = 'https://www.googleapis.com/auth/youtube'


class AuthorizationError(Exception):
    def __init__(self, message, kind='api_error'):
        super().__init__(message)
        self.kind = kind


def oauth_error(response):
    try:
        payload = response.json()
        code = payload.get('error', '')
    except (ValueError, TypeError, AttributeError):
        code = ''
    if code in {'invalid_grant', 'expired_token', 'access_denied'}:
        return AuthorizationError('A autorização do Google expirou ou foi revogada. Use Reconectar canal no app.', 'auth_required')
    if code in {'invalid_client', 'unauthorized_client'}:
        return AuthorizationError('O Google recusou a credencial. Para conectar pelo celular, crie um cliente do tipo TVs e dispositivos com entrada limitada e salve-o aqui.', 'configure_client')
    if code == 'invalid_scope':
        return AuthorizationError('O Google recusou as permissões. Confira o tipo da credencial e ative a YouTube Data API v3.', 'configure_client')
    if response.status_code == 429 or code == 'rate_limit_exceeded':
        return AuthorizationError('O Google limitou as tentativas. Aguarde alguns minutos e tente novamente.', 'retry_later')
    return AuthorizationError('O Google não conseguiu renovar a conexão agora. Use Verificar e renovar para tentar novamente.', 'retry_later')


class DeviceAuthorization:
    def __init__(self, root, writer, finish):
        self.root = Path(root)
        self.writer = writer
        self.finish = finish
        self.lock = threading.RLock()

    def read(self, name):
        try:
            value = json.loads((self.root / name).read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, name, value):
        self.writer(self.root / name, value)

    def configured(self):
        return bool(self.read('device_client.json').get('client_id'))

    @staticmethod
    def credentials(data):
        if not isinstance(data, dict):
            raise AuthorizationError('Escolha o JSON da credencial Google ou informe ID e chave.', 'configure_client')
        config = data.get('installed') or data.get('web') or data
        if not isinstance(config, dict):
            raise AuthorizationError('A credencial Google não é válida.', 'configure_client')
        result = {key: config.get(key, '') for key in ('client_id', 'client_secret')}
        if any(not isinstance(value, str) or not 1 <= len(value.strip()) <= 4096 for value in result.values()):
            raise AuthorizationError('A credencial precisa conter ID do cliente e chave secreta.', 'configure_client')
        return {key: value.strip() for key, value in result.items()}

    def public_session(self, session):
        return {key: session.get(key) for key in ('session_id', 'status', 'user_code',
            'verification_url', 'expires_at', 'interval', 'message', 'channel_title', 'recovery')}

    def status(self, username):
        with self.lock:
            session = self.read('device_sessions.json').get(username, {})
            if session.get('status') == 'pending' and not session.get('granted_token') and session.get('expires_at', 0) <= time.time():
                session = {**session, 'status': 'expired', 'message': 'O código expirou. Toque em Reconectar canal para gerar outro.', 'recovery': 'auth_required'}
            return self.public_session(session) if session else None

    def start(self, username, data=None):
        with self.lock:
            config = self.credentials(data if data else self.read('device_client.json'))
            response = requests.post('https://oauth2.googleapis.com/device/code',
                data={'client_id': config['client_id'], 'scope': DEVICE_SCOPE}, timeout=20)
            if response.status_code != 200:
                raise oauth_error(response)
            try:
                payload = response.json()
                interval = max(5, min(120, int(payload.get('interval', 5))))
                lifetime = max(5, min(3600, int(payload.get('expires_in', 1800))))
            except (ValueError, TypeError, AttributeError):
                raise AuthorizationError('O Google retornou uma resposta inválida. Tente gerar outro código.')
            uri = urlparse(str(payload.get('verification_url') or payload.get('verification_uri') or ''))
            if uri.scheme != 'https' or uri.hostname not in {'google.com', 'www.google.com', 'accounts.google.com'}:
                raise AuthorizationError('O Google retornou um endereço de autorização inválido.')
            if not all(isinstance(payload.get(key), str) and 1 <= len(payload[key]) <= 512 for key in ('device_code', 'user_code')):
                raise AuthorizationError('O Google não retornou um código de autorização válido.')
            now = time.time()
            session = dict(config, session_id=secrets.token_urlsafe(24), status='pending',
                device_code=payload['device_code'], user_code=payload['user_code'],
                verification_url=uri.geturl(), expires_at=now + lifetime,
                interval=interval, next_poll=now + interval,
                message='Abra o Google no navegador, informe o código e permita o acesso ao seu canal.')
            sessions = {name: value for name, value in self.read('device_sessions.json').items()
                        if isinstance(value, dict) and (value.get('granted_token') or value.get('expires_at', 0) > now)}
            sessions[username] = session
            # Only save credentials after Google accepts this device client.
            self.save('device_client.json', config)
            self.save('device_sessions.json', sessions)
            return self.public_session(session)

    def poll(self, username, session_id):
        with self.lock:
            sessions = self.read('device_sessions.json')
            session = sessions.get(username, {})
            if not session or not secrets.compare_digest(str(session.get('session_id', '')), str(session_id)):
                raise AuthorizationError('Esta autorização não está mais ativa. Gere um novo código.', 'auth_required')
            if session['status'] != 'pending':
                return self.public_session(session)
            now = time.time()
            if session['expires_at'] <= now and not session.get('granted_token'):
                session.update(status='expired', message='O código expirou. Gere outro pelo botão Reconectar canal.', recovery='auth_required')
            elif now >= session['next_poll']:
                session['next_poll'] = now + session['interval']
                try:
                    if not session.get('granted_token'):
                        response = requests.post('https://oauth2.googleapis.com/token', data={
                            'client_id': session['client_id'], 'client_secret': session['client_secret'],
                            'device_code': session['device_code'],
                            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'}, timeout=20)
                        payload = response.json()
                        if not isinstance(payload, dict):
                            raise ValueError('Invalid Google response')
                        if response.status_code == 200:
                            # The grant is single-use. Persist it before querying the
                            # channel so a network failure or restart cannot lose it.
                            payload['expires_at'] = now + float(payload.get('expires_in', 3600))
                            session['granted_token'] = payload
                            sessions[username] = session
                            self.save('device_sessions.json', sessions)
                        elif payload.get('error') == 'authorization_pending':
                            session['message'] = 'Aguardando sua confirmação no Google. Depois volte ao app.'
                        elif payload.get('error') == 'slow_down':
                            session['interval'] = min(120, session['interval'] + 5)
                            session['next_poll'] = now + session['interval']
                        else:
                            error = oauth_error(response)
                            session.update(status='error', message=str(error), recovery=error.kind)
                    if session.get('granted_token'):
                        result = self.finish(session['granted_token'], {key: session[key] for key in ('client_id', 'client_secret')})
                        session.update(status='connected', channel_title=result, message='Canal conectado: ' + result)
                except (requests.RequestException, ValueError, TypeError):
                    session['next_poll'] = time.time() + max(15, session['interval'])
                    session['message'] = 'O Google não respondeu agora. A autorização continua ativa; tentaremos novamente.'
                except AuthorizationError as error:
                    session.update(status='error', message=str(error), recovery=error.kind)
            if session['status'] != 'pending':
                for key in ('device_code', 'client_secret', 'client_id', 'granted_token'):
                    session.pop(key, None)
            sessions[username] = session
            self.save('device_sessions.json', sessions)
            return self.public_session(session)

    def cancel(self, username, session_id=None):
        with self.lock:
            sessions = self.read('device_sessions.json')
            session = sessions.get(username, {})
            if session and session_id and not secrets.compare_digest(str(session.get('session_id', '')), str(session_id)):
                raise AuthorizationError('Este código já foi substituído. Atualize o painel para ver o código atual.', 'auth_required')
            sessions.pop(username, None)
            self.save('device_sessions.json', sessions)
