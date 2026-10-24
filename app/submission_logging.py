"""Log queue requests before form parsing, without URLs, lyrics or credentials."""
import re


class SubmissionLoggingMiddleware:
    def __init__(self, app, logger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('path') != '/api/process' or scope.get('method') != 'POST':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        supplied = headers.get(b'x-submission-id', b'').decode('ascii', errors='ignore')
        identifier = supplied if re.fullmatch(r'[A-Za-z0-9_-]{16,80}', supplied) else 'sem identificador'
        encoding = headers.get(b'content-type', b'').split(b';', 1)[0].decode('ascii', errors='ignore')
        encoding = encoding if encoding in {'multipart/form-data', 'application/x-www-form-urlencoded'} else 'outro formato'
        self.logger.info('Inclusão %s: requisição recebida (%s), antes da leitura dos campos.', identifier, encoding)

        async def log_response(message):
            if message['type'] == 'http.response.start':
                self.logger.info('Inclusão %s: resposta HTTP %s.', identifier, message['status'])
            await send(message)

        return await self.app(scope, receive, log_response)
