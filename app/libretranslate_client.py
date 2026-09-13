"""Cliente HTTP para instâncias LibreTranslate administradas pelo usuário."""

import json
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import requests

CONFIG_FILE = Path('/data/output/libretranslate.json')
CONFIG_LOCK = threading.RLock()


def normalize_url(value):
    value = str(value or '').strip().rstrip('/')
    if not value:
        return ''
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('Informe uma URL HTTP/HTTPS sem chave, usuário ou parâmetros.')
    if value.endswith('/translate'):
        value = value[:-10]
    return value


def load_config():
    with CONFIG_LOCK:
        config = {
            'url': os.environ.get('LIBRETRANSLATE_URL', ''),
            'api_key': os.environ.get('LIBRETRANSLATE_API_KEY', ''),
            'timeout': 1800,
        }
        if CONFIG_FILE.exists():
            config.update(json.loads(CONFIG_FILE.read_text(encoding='utf-8')))
        config['url'] = normalize_url(config['url'])
        return config


def public_config(config=None):
    config = config if config is not None else load_config()
    return {key: config[key] for key in ('url', 'timeout')} | {
        'has_api_key': bool(config.get('api_key')),
    }


def save_config(url, api_key=None, timeout=1800):
    with CONFIG_LOCK:
        config = load_config()
        config.update(url=normalize_url(url), timeout=int(timeout))
        config.pop('chunk_size', None)
        if not 10 <= config['timeout'] <= 7200:
            raise ValueError('Tempo limite fora dos limites permitidos.')
        if api_key is not None:
            config['api_key'] = api_key.strip()
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(dir=CONFIG_FILE.parent, prefix='.libretranslate-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(config, stream, ensure_ascii=False)
            os.replace(filename, CONFIG_FILE)
        finally:
            if os.path.exists(filename):
                os.unlink(filename)
        return public_config(config)


class TranslationServiceError(RuntimeError):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


class LibreTranslateClient:
    def __init__(self, config=None, cancel_event=None):
        self.config = dict(config if config is not None else load_config())
        self.url = normalize_url(self.config['url'])
        if not self.url:
            raise TranslationServiceError('Configure o LibreTranslate em Ajustes → Tradução de SRT.')
        self.cancel_event = cancel_event or threading.Event()
        self.session = requests.Session()
        self.encoding = 'json'

    def close(self):
        self.session.close()

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise InterruptedError('Cancelado pelo usuário.')

    def request(self, method, path, payload=None, files=None, raw=False):
        for attempt in range(3):
            self.check_cancelled()
            kwargs = {('data' if files else self.encoding): payload} if payload is not None else {}
            if files:
                kwargs['files'] = files
            try:
                response = self.session.request(
                    method, self.url + path, timeout=(5, self.config['timeout']),
                    allow_redirects=False, **kwargs,
                )
            except requests.RequestException:
                if attempt == 2:
                    raise TranslationServiceError(
                        'LibreTranslate não respondeu. Verifique endereço, porta e serviço; '
                        'aumente o tempo limite se a tradução estiver lenta.'
                    ) from None
                if self.cancel_event.wait(2 ** attempt):
                    self.check_cancelled()
                continue
            self.check_cancelled()
            if response.status_code in {429, 502, 503, 504} and attempt < 2:
                try:
                    delay = min(15, max(1, float(response.headers.get('Retry-After', 2 ** attempt))))
                except ValueError:
                    delay = 2 ** attempt
                if self.cancel_event.wait(delay):
                    self.check_cancelled()
                continue
            if response.status_code == 415 and self.encoding == 'json' and payload is not None and not files:
                self.encoding = 'data'
                return self.request(method, path, payload)
            messages = {
                400: 'LibreTranslate recusou o texto ou o par de idiomas.',
                401: 'Verifique a chave de API do LibreTranslate.',
                403: 'LibreTranslate negou acesso. Verifique a chave e as permissões.',
                404: 'API LibreTranslate não encontrada. Confira o endereço base e o prefixo.',
                413: 'O trecho excede o limite de caracteres do LibreTranslate.',
                429: 'LibreTranslate atingiu o limite de requisições. Tente novamente mais tarde.',
            }
            if response.status_code != 200:
                if path == '/translate_file' and response.status_code in {400, 404, 413}:
                    raise TranslationServiceError('LibreTranslate recusou o arquivo SRT. Verifique se a tradução de arquivos está habilitada, o limite de upload e os idiomas instalados.', response.status_code)
                raise TranslationServiceError(messages.get(response.status_code,
                    f'LibreTranslate retornou HTTP {response.status_code}.'), response.status_code)
            if raw:
                return response.content
            try:
                result = response.json()
            except ValueError:
                raise TranslationServiceError('A resposta não é JSON. Confira se a URL aponta para a API.') from None
            if isinstance(result, dict) and result.get('error'):
                # Não reproduzir respostas remotas: podem conter texto privado ou a chave.
                raise TranslationServiceError('LibreTranslate informou erro ao traduzir. Verifique os idiomas instalados.')
            return result
        raise TranslationServiceError('LibreTranslate temporariamente indisponível.')

    def languages(self):
        result = self.request('GET', '/languages')
        if not isinstance(result, list) or not result:
            raise TranslationServiceError('LibreTranslate não informou idiomas instalados.')
        languages = []
        for item in result:
            if not isinstance(item, dict) or not isinstance(item.get('code'), str):
                raise TranslationServiceError('Formato da lista de idiomas incompatível.')
            targets = item.get('targets')
            languages.append({'code': item['code'], 'name': str(item.get('name', item['code'])),
                              'targets': targets if isinstance(targets, list) else None})
        return languages

    def translate_srt_file(self, source_path, destination, target='pt-BR', progress_callback=None):
        from subtitle_translator import parse_srt
        languages = self.languages()
        if target not in {item['code'] for item in languages}:
            raise TranslationServiceError('Instale no LibreTranslate o idioma de destino solicitado: ' + target)
        original_bytes = Path(source_path).read_bytes()
        original = parse_srt(original_bytes.decode('utf-8-sig'))
        if progress_callback:
            progress_callback(0, 1)
        payload = {'source': 'auto', 'target': target}
        if self.config.get('api_key'):
            payload['api_key'] = self.config['api_key']
        result = self.request('POST', '/translate_file', payload,
                              files={'file': ('subtitles.srt', original_bytes, 'application/x-subrip')})
        file_url = result.get('translatedFileUrl') if isinstance(result, dict) else None
        if not isinstance(file_url, str) or not file_url:
            raise TranslationServiceError('LibreTranslate não devolveu o endereço do SRT traduzido.')
        file_url = urljoin(self.url + '/', file_url)
        base, translated = urlsplit(self.url), urlsplit(file_url)
        if (translated.scheme, translated.hostname, translated.port) != (base.scheme, base.hostname, base.port) or translated.username or translated.password:
            raise TranslationServiceError('O endereço do SRT traduzido aponta para outro servidor.')
        relative = file_url[len(self.url):] if file_url.startswith(self.url + '/') else None
        if relative is None:
            raise TranslationServiceError('O endereço do resultado está fora do prefixo configurado.')
        raw = self.request('GET', relative, raw=True)
        try:
            translated_segments = parse_srt(raw.decode('utf-8-sig'))
        except (UnicodeError, ValueError):
            raise TranslationServiceError('O arquivo recebido não é um SRT válido.') from None
        if [(s['start'], s['end']) for s in translated_segments] != [(s['start'], s['end']) for s in original]:
            raise TranslationServiceError('A tradução alterou os tempos ou a quantidade de legendas. O original foi preservado.')
        self.check_cancelled()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.translated-', suffix='.srt')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if progress_callback:
            progress_callback(1, 1)
        return translated_segments



def test_connection():
    client = LibreTranslateClient()
    try:
        languages = client.languages()
        codes = {item['code'] for item in languages}
        if 'pt-BR' in codes:
            with tempfile.TemporaryDirectory() as directory:
                original = Path(directory) / 'test.srt'
                original.write_text('1\n00:00:00,000 --> 00:00:02,000\nHello world.\n', encoding='utf-8')
                translated = client.translate_srt_file(original, Path(directory) / 'translated.srt')
            return {'languages': languages, 'message': 'Envio e download de SRT automático → PT-BR verificados.', 'sample': translated[0]['text']}
        return {'languages': languages, 'message': 'Conexão verificada, mas PT-BR não está instalado nesta instância.'}
    finally:
        client.close()
