"""Small real HTTP server for browser -> FastAPI submission regression tests."""
import ast
import json
import socket
import sys
import threading
from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse

from test_easy_mode_config import load_normalizer
from test_queue_cache import QueueCacheTests, ROOT
from submission_logging import SubmissionLoggingMiddleware


if __name__ == '__main__':
    fixture = QueueCacheTests()
    fixture.setUp()
    mode = sys.argv[1] if len(sys.argv) > 1 else 'locked'
    if mode == 'locked':
        fixture.job('active', 'processing')
    scope = fixture.scope
    scope['threading'] = threading
    _, normalize = load_normalizer()
    config = normalize({'background_mode': 'original'})
    scope['load_easy_mode_config'] = lambda: config
    scope.update(USER_DATA_ROOT=str(fixture.root), user_storage_key=lambda name: name)
    paths = next(node for node in ast.parse((ROOT/'app/main.py').read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name == 'get_user_paths')
    exec(compile(ast.Module(body=[paths], type_ignores=[]), 'user-paths', 'exec'), scope)
    legacy = fixture.root/'alice'/'cache'
    if mode == 'locked':
        legacy.rename(Path(str(legacy) + '.previous'))
    ready, release = threading.Event(), threading.Event()

    def hold_promotion():
        with scope['legacy_cache_promotion_lock']:
            ready.set()
            release.wait()

    holder = threading.Thread(target=hold_promotion, daemon=True)
    if mode == 'locked':
        holder.start()
        assert ready.wait(5)
    app = scope['app']
    app.add_middleware(SubmissionLoggingMiddleware, logger=scope['logger'])
    encodings = []

    @app.middleware('http')
    async def capture_encoding(request, call_next):
        if request.url.path == '/api/process':
            encodings.append(request.headers.get('content-type', ''))
        return await call_next(request)

    @app.get('/', response_class=HTMLResponse)
    def index():
        return (ROOT/'app/templates/index.html').read_text().replace(
            '{% include "queue_cache_panel.html" %}', (ROOT/'app/templates/queue_cache_panel.html').read_text())

    @app.get('/api/auth_status')
    def auth():
        return dict(status='authenticated', **fixture.user)

    @app.get('/api/easy-mode')
    def easy_mode():
        return config

    @app.get('/api/library')
    def library():
        return dict(audio=[], backgrounds=[], history=[], videos=[], photos=[])

    @app.get('/api/status')
    def status():
        return dict(status='processing', progress=25, step='Separating vocals', can_cancel=False)

    @app.get('/__test__/jobs')
    def jobs():
        return dict(encodings=encodings, jobs=[dict(id=job['id'], title=job['title'],
            submission_id=job.get('submission_id'), lyrics=job['pipeline'].get('lyrics_text'),
            owner=job['owner_username'], source=job['pipeline'].get('youtube_url'))
            for job in fixture.queue])

    @app.get('/api/{path:path}')
    def other(path):
        return {}

    if mode == 'cleared':
        fixture.job('previous', 'done')
        assert fixture.client.delete('/api/queue-cache').status_code == 200

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    print(json.dumps({'port': sock.getsockname()[1]}), flush=True)
    try:
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
        server.run(sockets=[sock])
    finally:
        release.set()
        if mode == 'locked':
            holder.join(5)
        fixture.doCleanups()
