"""An image update cannot be shadowed by old yt-dlp files in a persistent volume."""
import ast
import importlib
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
from youtube_download_access import package_version, version_key

ROOT = Path(__file__).parents[1]


def load(name,scope):
    node = next(item for item in ast.parse((ROOT/'app/main.py').read_text()).body if isinstance(item,ast.FunctionDef) and item.name==name)
    node.decorator_list = []
    namespace = dict(Depends=lambda _:None,get_current_user=lambda:None,os=os,sys=sys,shutil=shutil,logger=logging.getLogger('engine-test'))
    namespace.update(scope)
    scope = namespace
    exec(compile(ast.Module(body=[node],type_ignores=[]),'main.py','exec'),scope)
    return scope[name]


class EngineRecoveryTests(unittest.TestCase):
    def test_new_image_is_selected_and_previous_engine_and_ejs_are_invalidated(self):
        for saved,image,expected_saved in [('2026.09.01','2026.10.09',False),('2026.10.10.123456.dev0','2026.10.09',True)]:
            with tempfile.TemporaryDirectory() as folder:
                runtime = Path(folder)/'saved'; packaged = Path(folder)/'image'
                for path,version in ((runtime/'yt_dlp',saved),(packaged/'yt_dlp',image)):
                    path.mkdir(parents=True); (path/'version.py').write_text("__version__ = '"+version+"'\n")
                fake_sys = SimpleNamespace(path=[str(runtime),str(packaged)],modules={'yt_dlp':SimpleNamespace(__file__=str(runtime/'yt_dlp/__init__.py')),'yt_dlp_ejs':object(),'yt_dlp_ejs.provider':object()})
                pathfinder = Mock(); pathfinder.find_spec.return_value = SimpleNamespace(origin=str(packaged/'yt_dlp/__init__.py'))
                engine = SimpleNamespace(__file__=str((runtime if expected_saved else packaged)/'yt_dlp/__init__.py'))
                imports = SimpleNamespace(machinery=SimpleNamespace(PathFinder=pathfinder),invalidate_caches=Mock(),import_module=Mock(return_value=engine))
                function = load('load_yt_dlp',{'sys':fake_sys,'importlib':imports,'YT_DLP_RUNTIME_DIR':str(runtime),'package_version':package_version,'version_key':version_key})
                self.assertIs(function(force_reload=True),engine)
                self.assertEqual(str(runtime) in fake_sys.path,expected_saved)
                self.assertNotIn('yt_dlp_ejs',fake_sys.modules); self.assertNotIn('yt_dlp_ejs.provider',fake_sys.modules)


    def test_canceled_music_or_background_download_does_not_try_another_format(self):
        for name in ('download_youtube','download_bg_youtube'):
            with tempfile.TemporaryDirectory() as folder:
                extract = Mock(side_effect=InterruptedError('Canceled'))
                function = load(name,{'yt_dlp_operation_lock':threading.RLock(),'load_yt_dlp':Mock(),
                    'youtube_download_options':lambda *args:{},'extract_youtube_info':extract})
                with self.assertRaises(InterruptedError): function('https://youtu.be/abcdefghijk',folder)
                extract.assert_called_once()

    def test_update_can_start_during_whisper_processing_without_duplicate_worker(self):
        processing = threading.Lock(); processing.acquire()
        thread = Mock(); state = {}
        function = load('update_youtube_tools',{'processing_lock':processing,'yt_dlp_update_lock':threading.RLock(),'yt_dlp_update_state':state,'require_admin':Mock(),'threading':SimpleNamespace(Thread=thread),'run_yt_dlp_update':Mock()})
        self.assertEqual(function({})['status'],'started')
        self.assertEqual(function({})['status'],'updating'); thread.assert_called_once()

    def test_installation_is_staged_without_holding_active_download_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime,staging,backup = [str(Path(folder)/name) for name in ('runtime','staging','backup')]
            operation = threading.Lock(); state = {}; calls = []
            def run(command,**kwargs):
                calls.append(command); self.assertFalse(operation.locked())
                return SimpleNamespace(returncode=0,stdout='2026.10.09',stderr='')
            def reload(**kwargs): self.assertTrue(operation.locked()); return object()
            scope = {'yt_dlp_update_lock':threading.RLock(),'yt_dlp_operation_lock':operation,'yt_dlp_update_state':state,
                'YT_DLP_RUNTIME_DIR':runtime,'YT_DLP_STAGING_DIR':staging,'YT_DLP_BACKUP_DIR':backup,
                'subprocess':SimpleNamespace(run=run),'load_yt_dlp':reload,'yt_dlp_version':lambda:'2026.10.09'}
            load('run_yt_dlp_update',scope)()
            self.assertEqual(state['status'],'done'); self.assertEqual(len(calls),2)
            self.assertTrue(Path(runtime).is_dir()); self.assertFalse(Path(backup).exists())

    def test_failed_swap_restores_previous_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime,staging,backup = [str(Path(folder)/name) for name in ('runtime','staging','backup')]
            Path(runtime).mkdir(); (Path(runtime)/'working').write_text('previous')
            state = {}; real_replace = os.replace
            def replace(source,target):
                if source == staging: raise OSError('swap failed')
                real_replace(source,target)
            scope = {'yt_dlp_update_lock':threading.RLock(),'yt_dlp_operation_lock':threading.Lock(),'yt_dlp_update_state':state,
                'YT_DLP_RUNTIME_DIR':runtime,'YT_DLP_STAGING_DIR':staging,'YT_DLP_BACKUP_DIR':backup,
                'subprocess':SimpleNamespace(run=lambda *args,**kwargs:SimpleNamespace(returncode=0,stdout='2026.10.09',stderr='')),
                'load_yt_dlp':Mock(),'yt_dlp_version':lambda:'2026.10.09'}
            with patch('os.replace',side_effect=replace): load('run_yt_dlp_update',scope)()
            self.assertEqual(state['status'],'error'); self.assertEqual((Path(runtime)/'working').read_text(),'previous')
