"""One-time desktop YouTube authorization; no HTTPS server or extra packages."""
import argparse
import base64
import hashlib
import json
import os
import secrets
import time
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
            self.wfile.write('Autorização recebida. Volte ao programa para salvar o arquivo e importá-lo no Karaokê.'.encode())
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


def main():
    parser = argparse.ArgumentParser(description='Conectar YouTube sem HTTPS no servidor Sal0.')
    parser.add_argument('client_json', nargs='?')
    parser.add_argument('--output', default='youtube-autorizacao.json')
    args = parser.parse_args()
    gui = None
    try:
        if not args.client_json:
            import tkinter as tk
            from tkinter import filedialog, messagebox
            gui = tk.Tk(); gui.withdraw()
            args.client_json = filedialog.askopenfilename(title='Escolha o JSON OAuth para computador do Google', filetypes=[('JSON', '*.json')])
            if not args.client_json: return
        config = json.loads(Path(args.client_json).read_text(encoding='utf-8'))
        if 'installed' not in config:
            raise ValueError('Este JSON não é de um cliente Aplicativo para computador. Crie esse tipo no Google Cloud.')
        data = obtain_authorization(config['installed'])
        output = args.output
        if gui:
            output = filedialog.asksaveasfilename(title='Salvar autorização para importar no Karaokê', initialfile='youtube-autorizacao.json', defaultextension='.json')
            if not output: return
        save_authorization(output, data)
        message = 'Arquivo salvo. No Karaokê: Ajustes → YouTube → Importar autorização. Guarde o arquivo como uma senha; não compartilhe.'
        if gui: messagebox.showinfo('YouTube autorizado', message)
        else: print(message)
    except Exception as error:
        message = str(error) if isinstance(error, ValueError) else 'Não foi possível abrir os arquivos ou executar a autorização.'
        if gui: messagebox.showerror('Autorização não concluída', message)
        else: print(message)
        return 1
    finally:
        if gui: gui.destroy()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
