import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]/'app'))
from submission_logging import SubmissionLoggingMiddleware


class SubmissionLoggingTests(unittest.TestCase):
    def test_malformed_upload_is_visible_before_parsing_without_exposing_private_data(self):
        logger = Mock()
        app = FastAPI()
        app.add_middleware(SubmissionLoggingMiddleware, logger=logger)
        endpoint = Mock()

        @app.post('/api/process')
        def process(audio_file: UploadFile = File(None)):
            endpoint()
            return {}

        with TestClient(app) as client:
            response = client.post('/api/process', content=b'private lyrics and file bytes', headers={
                'content-type': 'multipart/form-data', 'x-submission-id': 'a'*32,
                'authorization': 'Bearer private-session', 'x-session-token': 'private-session'})
        self.assertEqual(response.status_code, 400)
        endpoint.assert_not_called()
        records = [str(call) for call in logger.info.call_args_list]
        self.assertIn('antes da leitura dos campos', records[0])
        self.assertIn('400', records[-1])
        self.assertIn('a'*32, records[0])
        self.assertNotIn('private', '\n'.join(records))

    def test_unrelated_requests_are_not_logged_as_submissions(self):
        logger = Mock()
        app = FastAPI()
        app.add_middleware(SubmissionLoggingMiddleware, logger=logger)
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/process').status_code, 404)
        logger.info.assert_not_called()
