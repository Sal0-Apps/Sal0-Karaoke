"""One-time desktop YouTube authorization; no HTTPS server or extra packages."""
import argparse
import base64
import hashlib
import json
import os
import secrets
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCOPE = 'https://www.googleapis.com/auth/youtube.force-ssl'


def obtain_authorization(client, opener=webbrowser.open, timeout=300):
    if not isinstance(client, dict) or not client.get('client_id') or not client.get('client_secret'):
        raise ValueError('Escolha o JSON de um cliente OAuth do tipo Aplicativo para computador.')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    result = {}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Authorization codes must never reach request logs.
        def do_GET(self):
            parts = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parts.query)
            valid = parts.path == '/callback' and secrets.compare_digest(params.get('state', [''])[0], state)
            if not valid:
                self.send_response(400); self.end_headers(); self.wfile.write(b'Autorizacao invalida.'); return
            if params.get('error') or not params.get('code'):
                result['error'] = 'A autorização foi recusada.'
            else:
                result['code'] = params['code'][0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write('Autorização recebida. Volte à aba do assistente para baixar o arquivo e importá-lo no Karaokê.'.encode())
    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        server.timeout = 1
        redirect = f'http://127.0.0.1:{server.server_port}/callback'
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
            'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
            'scope': SCOPE, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
            'access_type': 'offline', 'prompt': 'consent'})
        if not opener(url):
            raise ValueError('Não foi possível abrir o navegador. Execute em um computador com navegador.')
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if 'code' not in result:
        raise ValueError(result.get('error', 'A autorização expirou. Execute novamente.'))
    request = urllib.request.Request('https://oauth2.googleapis.com/token', data=urllib.parse.urlencode({
        'client_id': client['client_id'], 'client_secret': client['client_secret'],
        'code': result['code'], 'code_verifier': verifier, 'redirect_uri': redirect,
        'grant_type': 'authorization_code'}).encode(), method='POST')
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            token = json.load(response)
    except (urllib.error.URLError, ValueError):
        raise ValueError('Não foi possível concluir a autorização com o Google.') from None
    if not token.get('refresh_token'):
        raise ValueError('O Google não concedeu acesso permanente. Execute novamente.')
    return {'format': 'sal0-youtube-desktop-v1', 'client_id': client['client_id'],
            'client_secret': client['client_secret'], 'refresh_token': token['refresh_token']}


def save_authorization(path, data):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    os.chmod(path, 0o600)


WIZARD_HTML = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conectar YouTube · Sal0 Karaokê</title><style>
body{background:#101827;color:#eef3ff;font:18px system-ui;margin:0;padding:24px}main{max-width:640px;margin:auto}button,a.button,input{box-sizing:border-box;width:100%;padding:16px;margin:12px 0;border-radius:12px;font:inherit}button,a.button{background:#69d8ff;color:#102030;border:0;display:block;text-align:center;text-decoration:none}button:disabled{opacity:.5}a{color:#69d8ff}p{line-height:1.5}input{border:1px solid #678} [hidden]{display:none!important}</style>
<main><h1>Conectar meu canal</h1><p>Configuração gratuita. Nenhuma senha Google é digitada neste assistente.</p>
<h2>1. Escolha o JSON do Google</h2><input id="file" type="file" accept=".json,application/json"><button id="start">Preparar conexão</button>
<h2>2. Autorize sua conta</h2><a id="google" class="button" target="_blank" rel="noopener noreferrer" hidden>Abrir Google e autorizar</a>
<p id="status" role="status">Escolha a credencial do tipo Aplicativo para computador.</p>
<h2>3. Volte ao Karaokê</h2><a id="download" class="button" hidden>Baixar autorização</a><p>Em Ajustes → Publicar no YouTube, escolha o arquivo baixado e clique em Conectar meu canal. Mantenha este programa aberto até baixar o arquivo.</p></main>
<script>
const base=location.pathname;let polling;
const status=document.getElementById('status'),start=document.getElementById('start'),google=document.getElementById('google'),download=document.getElementById('download');
start.onclick=async()=>{const file=document.getElementById('file').files[0];if(!file){status.textContent='Escolha primeiro o JSON do Google.';return}if(file.size>32768){status.textContent='O arquivo é muito grande. Escolha o JSON de credenciais.';return}start.disabled=true;google.hidden=true;download.hidden=true;try{const response=await fetch(base+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:await file.text()});const data=await response.json();if(!response.ok)throw Error(data.error);status.textContent='Preparando autorização…';clearInterval(polling);polling=setInterval(check,700);await check()}catch(e){status.textContent=e.message;start.disabled=false}};
async function check(){try{const response=await fetch(base+'/status');if(!response.ok)throw Error('O assistente expirou. Abra o programa novamente.');const data=await response.json();if(data.url){google.href=data.url;google.hidden=false;status.textContent='Clique em Abrir Google e autorizar. Depois volte a esta aba.'}if(data.ready){clearInterval(polling);google.hidden=true;download.href=base+'/download';download.hidden=false;status.textContent='Autorização concluída. Baixe o arquivo e importe no Karaokê.'}if(data.error){clearInterval(polling);status.textContent=data.error;start.disabled=false}}catch(e){clearInterval(polling);status.textContent=e.message}}
</script></html>"""


def create_browser_wizard(authorize=obtain_authorization):
    """Local-only, random-path wizard; credentials stay in memory until export."""
    prefix = '/' + secrets.token_urlsafe(32)
    state = {}
    lock = threading.Lock()
    def worker(client):
        try:
            def open_google(url):
                with lock: state['url'] = url
                return True
            data = authorize(client, opener=open_google)
            with lock: state.update(data=data, ready=True)
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else 'Não foi possível autorizar. Tente novamente.'
            with lock: state['error'] = message
    class Wizard(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, code, body, kind='application/json; charset=utf-8', download=False):
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            if download: self.send_header('Content-Disposition', 'attachment; filename="youtube-autorizacao.json"')
            self.end_headers(); self.wfile.write(body.encode())
        def allowed(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            origin = self.headers.get('Origin')
            return self.headers.get('Host') == expected and (not origin or origin == 'http://' + expected)
        def do_GET(self):
            if not self.allowed(): self.send(403, '{}'); return
            with lock:
                if self.path == prefix:
                    self.send(200, WIZARD_HTML, 'text/html; charset=utf-8')
                elif self.path == prefix + '/status':
                    self.send(200, json.dumps({k: v for k, v in state.items() if k in ('url', 'ready', 'error')}, ensure_ascii=False))
                elif self.path == prefix + '/download' and state.get('ready'):
                    self.send(200, json.dumps(state['data']), download=True)
                else: self.send(404, '{}')
        def do_POST(self):
            if not self.allowed() or self.path != prefix + '/start': self.send(403, '{}'); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32768: raise ValueError('Escolha um JSON de credenciais de até 32 KB.')
                config = json.loads(self.rfile.read(size))
                client = config.get('installed') if isinstance(config, dict) else None
                if not isinstance(client, dict) or not all(isinstance(client.get(k), str) and client[k] for k in ('client_id', 'client_secret')):
                    raise ValueError('Escolha o JSON de um cliente Aplicativo para computador.')
                with lock:
                    if state and not state.get('error'): self.send(409, json.dumps({'error': 'Uma autorização já está em andamento.'})); return
                    state.clear(); state['started'] = True
                threading.Thread(target=worker, args=(client,), daemon=True).start()
                self.send(202, '{}')
            except (ValueError, TypeError):
                self.send(400, json.dumps({'error': 'Arquivo inválido. Baixe o JSON de um cliente Aplicativo para computador.'}))
    return HTTPServer(('127.0.0.1', 0), Wizard), prefix


def run_browser_wizard(opener=webbrowser.open, timeout=600):
    server, prefix = create_browser_wizard()
    with server:
        server.timeout = 1
        url = f'http://127.0.0.1:{server.server_port}{prefix}'
        print('Assistente de conexão aberto no navegador. Mantenha esta janela aberta até terminar.')
        if not opener(url):
            raise ValueError('Não foi possível abrir o navegador. Execute em um computador com navegador.')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline: server.handle_request()


def main():
    parser = argparse.ArgumentParser(description='Conectar YouTube gratuitamente pelo navegador, sem HTTPS no servidor Sal0.')
    parser.add_argument('client_json', nargs='?')
    parser.add_argument('--output', default='youtube-autorizacao.json')
    args = parser.parse_args()
    try:
        if not args.client_json:
            run_browser_wizard()
            return 0
        config = json.loads(Path(args.client_json).read_text(encoding='utf-8'))
        if 'installed' not in config:
            raise ValueError('Este JSON não é de um cliente Aplicativo para computador. Crie esse tipo no Google Cloud.')
        save_authorization(args.output, obtain_authorization(config['installed']))
        print('Arquivo salvo. No Karaokê: Ajustes → YouTube → Conectar meu canal.')
    except Exception as error:
        print(str(error) if isinstance(error, ValueError) else 'Não foi possível executar a autorização.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
