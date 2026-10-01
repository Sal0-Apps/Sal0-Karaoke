import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))


class WebStackCompatibilityTests(unittest.TestCase):
    def test_actual_updated_stack_serves_complete_interface(self):
        from fastapi import FastAPI, Request
        from fastapi.testclient import TestClient
        from starlette.templating import Jinja2Templates
        source=(ROOT/'app/main.py').read_text()
        tree=ast.parse(source)
        endpoint=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='read_index')
        endpoint.decorator_list=[]
        scope={'Request':Request,'templates':Jinja2Templates(directory=str(ROOT/'app/templates'))}
        exec(compile(ast.Module(body=[endpoint],type_ignores=[]),'index','exec'),scope)
        app=FastAPI();app.get('/')(scope['read_index'])
        with TestClient(app) as client:
            response=client.get('/')
        self.assertEqual(response.status_code,200)
        for text in ('easyAudioFile','subtitleVideoFile','ytPublishVideo','Termos do YouTube'):
            self.assertIn(text,response.text)

    def test_current_multipart_accepts_binary_upload_without_changing_bytes(self):
        from fastapi import FastAPI, File, UploadFile
        from fastapi.testclient import TestClient
        import hashlib
        app=FastAPI()
        @app.post('/upload')
        async def upload(file: UploadFile=File(...)):
            data=await file.read()
            return {'name':file.filename,'digest':hashlib.sha256(data).hexdigest()}
        content=b'\x00\xff\r\n--partial-boundary\x80' * 1000
        with TestClient(app) as client:
            response=client.post('/upload',files={'file':('song.wav',content,'audio/wav')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'name':'song.wav','digest':hashlib.sha256(content).hexdigest()})

    def test_existing_password_hashes_remain_compatible(self):
        import hashlib
        tree=ast.parse((ROOT/'app/main.py').read_text())
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='hash_password')
        scope={'hashlib':hashlib}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'password','exec'),scope)
        salt='00112233445566778899aabbccddeeff'
        expected=hashlib.pbkdf2_hmac('sha256',b'existing-password',bytes.fromhex(salt),100000).hex()
        self.assertEqual(scope['hash_password']('existing-password',salt),(expected,salt))
