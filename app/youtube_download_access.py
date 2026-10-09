"""Private download cookies, disposable yt-dlp jars and useful recovery states."""
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

MAX_COOKIES = 512 * 1024
HEADERS = {'# Netscape HTTP Cookie File', '# HTTP Cookie File'}


class DownloadAccessError(RuntimeError):
    def __init__(self, message, recovery='update_engine'):
        super().__init__(message)
        self.recovery = recovery


def download_error(error):
    text = str(error).casefold()
    if any(value in text for value in ('cookies are no longer valid', 'cookies have expired', 'expired cookies')):
        return DownloadAccessError('A sessão de downloads expirou. Renove os cookies em Ajustes → YouTube → Downloads.', 'renew_cookies')
    if any(value in text for value in ('sign in', 'not a bot', 'login required', 'confirm your age', 'http error 401')):
        return DownloadAccessError('O YouTube pediu uma sessão válida. Use Renovar sessão em Ajustes → YouTube → Downloads e teste o link.', 'renew_cookies')
    if any(value in text for value in ('private video', 'members-only', 'not available in your country', 'video unavailable', 'has been removed')):
        return DownloadAccessError('Esse vídeo está privado, indisponível ou restrito. Confira o acesso no YouTube ou escolha outro link.', 'check_video')
    if any(value in text for value in ('http error 403', 'signature', 'nsig', 'po token', 'challenge', 'requested format')):
        return DownloadAccessError('O YouTube recusou o acesso ao vídeo. Atualize o mecanismo no app e teste o link; se pedir login, renove a sessão de downloads.', 'update_engine')
    return DownloadAccessError('Não foi possível acessar o YouTube agora. Teste o link em Ajustes → YouTube → Downloads para verificar a conexão.', 'test_link')


def package_version(path):
    try:
        text = Path(path).read_text()
        match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)", text, re.MULTILINE)
        return match.group(1) if match else ''
    except OSError:
        return ''


def version_key(value):
    numbers = [int(number) for number in re.findall(r'\d+', value)]
    return tuple((numbers + [0, 0, 0])[:3]) + (0 if 'dev' in value or 'rc' in value else 1, tuple(numbers[3:]))


class YouTubeDownloadAccess:
    def __init__(self, root='/data/output/youtube_access'):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.last_check = None

    @property
    def cookies_path(self):
        return self.root / 'cookies.txt'

    @staticmethod
    def parse(raw):
        if len(raw) > MAX_COOKIES:
            raise DownloadAccessError('O arquivo de cookies deve ter até 512 KB.', 'renew_cookies')
        try:
            text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
        except UnicodeDecodeError:
            raise DownloadAccessError('Use cookies.txt em UTF-8, no formato Netscape.', 'renew_cookies')
        lines = text.strip().splitlines()
        if not lines or lines[0].strip() not in HEADERS:
            raise DownloadAccessError('Use cookies.txt no formato Netscape. O JSON da autorização do canal é outro arquivo.', 'renew_cookies')
        result, records = ['# Netscape HTTP Cookie File'], []
        for line in lines[1:]:
            if not line or (line.startswith('#') and not line.startswith('#HttpOnly_')):
                continue
            parts = line.split('\t')
            if len(parts) != 7:
                raise DownloadAccessError('O arquivo de cookies contém uma linha inválida. Exporte-o novamente.', 'renew_cookies')
            domain = parts[0].removeprefix('#HttpOnly_').lstrip('.').casefold()
            if not (domain == 'youtube.com' or domain.endswith('.youtube.com') or
                    domain == 'google.com' or domain.endswith('.google.com')):
                continue
            if parts[1] not in {'TRUE', 'FALSE'} or parts[3] not in {'TRUE', 'FALSE'} or not parts[4].isdigit() or not parts[2].startswith('/'):
                raise DownloadAccessError('O formato dos cookies não é válido. Exporte novamente no formato Netscape.', 'renew_cookies')
            if not re.fullmatch(r"[!#$%&'*+.^`|~0-9A-Za-z_-]+", parts[5]):
                raise DownloadAccessError('O arquivo contém um nome de cookie inválido.', 'renew_cookies')
            result.append(line)
            records.append((parts[5], int(parts[4])))
        if not records:
            raise DownloadAccessError('O arquivo não contém cookies do YouTube ou Google.', 'renew_cookies')
        return ('\n'.join(result) + '\n').encode(), records

    def save(self, raw):
        content, _ = self.parse(raw)
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='cookies-', dir=self.root)
            try:
                with os.fdopen(fd, 'wb') as file:
                    file.write(content)
                os.replace(name, self.cookies_path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            self.last_check = None
        return self.status()

    def clear(self):
        with self.lock:
            self.cookies_path.unlink(missing_ok=True)
            self.last_check = None

    def status(self):
        with self.lock:
            saved = self.cookies_path.is_file()
            state = 'saved' if saved else 'anonymous'
            if saved:
                try:
                    _, records = self.parse(self.cookies_path.read_bytes())
                    auth = [(name, expiry) for name, expiry in records
                            if 'SID' in name or name in {'LOGIN_INFO', 'APISID', 'SAPISID'}]
                    if auth and all(expiry and expiry <= time.time() for _, expiry in auth):
                        state = 'expired'
                except (OSError, DownloadAccessError):
                    state = 'invalid'
            return dict(cookies_saved=saved, session_state=state,
                last_check=dict(self.last_check) if self.last_check else None)

    def extract_info(self, module, url, options):
        with self.lock:
            raw = self.cookies_path.read_bytes() if self.cookies_path.is_file() else None
            state = self.status()['session_state']
        use_cookies = raw is not None and state == 'saved'
        # A fresh disposable jar prevents yt-dlp cookie rotation or a late write
        # from replacing cookies the administrator just renewed in another tab.
        for attempt in range(2 if use_cookies else 1):
            try:
                with tempfile.TemporaryDirectory(prefix='sal0-youtube-access-') as folder:
                    selected = dict(options)
                    if use_cookies and attempt == 0:
                        jar = Path(folder) / 'cookies.txt'
                        jar.write_bytes(raw)
                        os.chmod(jar, 0o600)
                        selected['cookiefile'] = str(jar)
                    with module.YoutubeDL(selected) as downloader:
                        info = downloader.extract_info(url, download=not selected.get('skip_download', False))
                with self.lock:
                    current = self.cookies_path.read_bytes() if self.cookies_path.is_file() else None
                    if current == raw:
                        self.last_check = {'status': 'ok', 'checked_at': time.time(),
                        'used_cookies': use_cookies and attempt == 0,
                        'message': 'O link foi acessado com a sessão salva.' if use_cookies and attempt == 0 else 'O link público foi acessado sem sessão.'}
                return info
            except InterruptedError:
                raise
            except OSError:
                raise  # Local disk/permissions failures are not expired YouTube login.
            except Exception as failure:
                error = download_error(failure)
                if attempt == 0 and use_cookies and error.recovery in {'renew_cookies', 'update_engine'}:
                    continue  # Public videos may remain accessible without stale cookies.
                with self.lock:
                    current = self.cookies_path.read_bytes() if self.cookies_path.is_file() else None
                    if current == raw:
                        self.last_check = {'status': 'error', 'checked_at': time.time(),
                            'message': str(error), 'recovery': error.recovery}
                raise error from None


DOWNLOAD_ACCESS = YouTubeDownloadAccess()


def extract_youtube_info(module, url, options):
    return DOWNLOAD_ACCESS.extract_info(module, url, options)


def install_routes(app, get_current_user, require_admin, probe):
    from fastapi import Depends, File, UploadFile, HTTPException

    def admin(user=Depends(get_current_user)):
        require_admin(user)
        return user

    @app.get('/api/youtube-tools/access')
    def status(user=Depends(admin)):
        return DOWNLOAD_ACCESS.status()

    @app.post('/api/youtube-tools/cookies')
    def save_cookies(cookies_file: UploadFile = File(...), user=Depends(admin)):
        try:
            return DOWNLOAD_ACCESS.save(cookies_file.file.read(MAX_COOKIES + 1))
        except DownloadAccessError as error:
            raise HTTPException(400, str(error))

    @app.delete('/api/youtube-tools/cookies')
    def clear_cookies(user=Depends(admin)):
        DOWNLOAD_ACCESS.clear()
        return DOWNLOAD_ACCESS.status()

    @app.post('/api/youtube-tools/test')
    def test_link(options: dict, user=Depends(admin)):
        url = str(options.get('url', '')).strip()
        parsed = urlparse(url)
        if len(url) > 2048 or parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.hostname not in {
                'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtu.be', 'www.youtu.be'}:
            raise HTTPException(400, 'Cole um link válido de vídeo do YouTube.')
        try:
            info = probe(url)
            return {'status': 'ok', 'title': str((info or {}).get('title') or 'Vídeo disponível'),
                'message': 'O link foi consultado. Você pode tentar a criação ou o download novamente.',
                'access': DOWNLOAD_ACCESS.status()}
        except DownloadAccessError as error:
            raise HTTPException(400, str(error), headers={'X-YouTube-Recovery': error.recovery})
