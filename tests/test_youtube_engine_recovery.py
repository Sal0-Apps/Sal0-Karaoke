"""Safe engine selection, replacement, cleanup and recovery on persistent volumes."""
import ast
import errno
import importlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
from youtube_download_access import package_version, version_key
from youtube_engine_runtime import EngineRuntime

ROOT = Path(__file__).parents[1]


def load(name,scope):
    node = next(item for item in ast.parse((ROOT/'app/main.py').read_text()).body if isinstance(item,ast.FunctionDef) and item.name==name)
    node.decorator_list = []
    namespace = dict(Depends=lambda _:None,get_current_user=lambda:None,os=os,sys=sys,shutil=shutil,
        logger=logging.getLogger('engine-test'), EngineRuntime=EngineRuntime, yt_dlp_import_lock=threading.RLock(),
        YT_DLP_STAGING_DIR='/unused/staging', YT_DLP_BACKUP_DIR='/unused/backup')
    namespace.update(scope)
    scope = namespace
    exec(compile(ast.Module(body=[node],type_ignores=[]),'main.py','exec'),scope)
    return scope[name]


class EngineRecoveryTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('yt_dlp'), 'Real yt-dlp is validated in the release image')
    def test_real_engine_reload_and_import_failure_recovery_in_isolated_process(self):
        script = textwrap.dedent('''
            import ast, importlib, importlib.machinery, os, shutil, sys, tempfile, threading
            from pathlib import Path
            sys.path.insert(0, str(Path(sys.argv[1])/'app'))
            from youtube_engine_runtime import EngineRuntime
            from youtube_download_access import package_version, version_key
            image = importlib.import_module('yt_dlp')
            source = Path(image.__file__).parent
            nodes = [node for node in ast.parse((Path(sys.argv[1])/'app/main.py').read_text()).body
                     if isinstance(node, ast.FunctionDef) and node.name in ('load_yt_dlp', 'yt_dlp_version')]
            with tempfile.TemporaryDirectory() as folder:
                runtime, staging, backup = [str(Path(folder)/name) for name in ('runtime', 'staging', 'backup')]
                scope = dict(os=os, sys=sys, importlib=importlib, EngineRuntime=EngineRuntime,
                    package_version=package_version, version_key=version_key,
                    yt_dlp_import_lock=threading.RLock(), YT_DLP_RUNTIME_DIR=runtime,
                    YT_DLP_STAGING_DIR=staging, YT_DLP_BACKUP_DIR=backup)
                exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), scope)
                storage = EngineRuntime(runtime, staging, backup)
                def reload():
                    engine = scope['load_yt_dlp'](force_reload=True)
                    assert engine.__file__.startswith(runtime + os.sep)
                    with engine.YoutubeDL({'quiet': True}) as downloader:
                        assert callable(downloader.extract_info)
                    return scope['yt_dlp_version']()
                for _ in range(2):
                    prepared = storage.prepare()
                    shutil.copytree(source, Path(prepared)/'yt_dlp')
                    assert storage.activate(prepared, reload) == image.version.__version__
                    storage.cleanup_obsolete()
                broken = storage.prepare()
                shutil.copytree(source, Path(broken)/'yt_dlp')
                (Path(broken)/'yt_dlp/__init__.py').write_text("raise ImportError('broken candidate')\\n")
                try:
                    storage.activate(broken, reload)
                    raise AssertionError('Invalid candidate was accepted')
                except ImportError as error:
                    assert str(error) == 'broken candidate'
                assert reload() == image.version.__version__
                storage.cleanup_obsolete()
                print('Real engine swaps, downloader construction and rollback passed.')
        ''')
        result = subprocess.run([sys.executable, '-c', script, str(ROOT)], text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)

    def update_scope(self, folder, run=None, **overrides):
        scope = {'yt_dlp_update_lock':threading.RLock(), 'yt_dlp_operation_lock':threading.RLock(),
            'yt_dlp_update_state':{}, 'YT_DLP_RUNTIME_DIR':str(Path(folder)/'runtime'),
            'YT_DLP_STAGING_DIR':str(Path(folder)/'staging'), 'YT_DLP_BACKUP_DIR':str(Path(folder)/'backup'),
            'subprocess':SimpleNamespace(run=run or (lambda *a, **k:SimpleNamespace(returncode=0, stdout='2026.10.09', stderr=''))),
            'load_yt_dlp':Mock(), 'yt_dlp_version':lambda:'2026.10.09'}
        scope.update(overrides)
        return scope

    def test_retry_uses_fresh_staging_despite_undeletable_legacy_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy = Path(folder)/'staging'; legacy.mkdir(); (legacy/'old').write_text('stale')
            targets = []; real_remove = shutil.rmtree
            def remove(path, *args, **kwargs):
                if str(path) == str(legacy): raise OSError(errno.ENOTEMPTY, 'Directory not empty', str(path))
                return real_remove(path, *args, **kwargs)
            def install(command, **kwargs):
                if '--target' in command:
                    target = command[command.index('--target')+1]; targets.append(target)
                    self.assertNotEqual(target, str(legacy))
                    self.assertFalse((Path(target)/'old').exists())
                    (Path(target)/'working').write_text(str(len(targets)))
                return SimpleNamespace(returncode=0, stdout='2026.10.09', stderr='')
            scope = self.update_scope(folder, install)
            with patch('shutil.rmtree', side_effect=remove):
                for _ in range(2):
                    load('run_yt_dlp_update', scope)()
                    self.assertEqual(scope['yt_dlp_update_state']['status'], 'done')
            self.assertNotEqual(*targets)
            self.assertEqual((Path(folder)/'runtime/working').read_text(), '2')
            self.assertEqual((legacy/'old').read_text(), 'stale')

    def test_cleanup_retries_real_directory_change_without_deleting_private_files(self):
        with tempfile.TemporaryDirectory() as folder:
            storage = EngineRuntime(*(str(Path(folder)/name) for name in ('runtime', 'staging', 'backup')))
            private = Path(folder)/'youtube_access'; private.mkdir(); (private/'cookies.txt').write_text('session')
            token = Path(folder)/'token.json'; token.write_text('channel')
            package = Path(folder)/(storage.discard_prefix+'old')
            util = package/'Cryptodome/Util'; util.mkdir(parents=True)
            link = Path(folder)/(storage.discard_prefix+'link'); link.symlink_to(private, target_is_directory=True)
            abandoned = Path(folder)/'staging-interrupted'; abandoned.mkdir()
            real_rmdir = os.rmdir; injected = []
            def rmdir(path, *args, **kwargs):
                if str(path) == 'Util' and not injected:
                    (util/'new-bytecode').write_text('created during removal'); injected.append(True)
                return real_rmdir(path, *args, **kwargs)
            with patch('os.rmdir', side_effect=rmdir): storage.cleanup_obsolete()
            self.assertEqual(injected, [True])
            self.assertFalse(package.exists()); self.assertFalse(link.exists()); self.assertFalse(abandoned.exists())
            self.assertEqual((private/'cookies.txt').read_text(), 'session')
            self.assertEqual(token.read_text(), 'channel')

    def test_worker_stays_reserved_until_cleanup_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            state = {}; start_thread = Mock()
            start = load('update_youtube_tools', {'yt_dlp_update_lock':threading.RLock(), 'yt_dlp_update_state':state,
                'require_admin':Mock(), 'threading':SimpleNamespace(Thread=start_thread), 'run_yt_dlp_update':Mock()})
            cleanup_status = []
            class ObservedRuntime(EngineRuntime):
                def cleanup_obsolete(self):
                    cleanup_status.append(start({})['status'])
                    return super().cleanup_obsolete()
            scope = self.update_scope(folder, yt_dlp_update_state=state, EngineRuntime=ObservedRuntime)
            load('run_yt_dlp_update', scope)()
            self.assertEqual(cleanup_status, ['updating', 'updating'])
            start_thread.assert_not_called()
            self.assertEqual(state['status'], 'done')

    def test_interrupted_swap_is_restored_before_loading_the_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime, staging, backup = [str(Path(folder)/name) for name in ('runtime', 'staging', 'backup')]
            package = Path(backup)/'yt_dlp'; package.mkdir(parents=True)
            (package/'version.py').write_text("__version__ = '2026.10.10'\n")
            fake_sys = SimpleNamespace(path=[], modules={})
            imports = SimpleNamespace(machinery=SimpleNamespace(PathFinder=Mock(find_spec=Mock(return_value=None))),
                invalidate_caches=Mock(), import_module=Mock(return_value=object()))
            load('load_yt_dlp', {'sys':fake_sys, 'importlib':imports, 'package_version':package_version,
                'version_key':version_key, 'YT_DLP_RUNTIME_DIR':runtime, 'YT_DLP_STAGING_DIR':staging,
                'YT_DLP_BACKUP_DIR':backup})()
            self.assertTrue((Path(runtime)/'yt_dlp/version.py').exists())
            self.assertIn(runtime, fake_sys.path); self.assertFalse(Path(backup).exists())

    def test_status_waits_for_activation_but_not_an_active_download(self):
        lock = threading.RLock(); operation = threading.Lock(); operation.acquire()
        called = threading.Event(); finished = threading.Event()
        scope = {'yt_dlp_import_lock':lock, 'yt_dlp_operation_lock':operation, 'require_admin':Mock(),
            'load_yt_dlp':lambda:(called.set() or SimpleNamespace(__file__='/runtime/yt_dlp/__init__.py')),
            'yt_dlp_version':lambda:'2026.10.09', 'deno_runtime_version':lambda:'deno',
            'yt_dlp_update_lock':threading.RLock(), 'yt_dlp_update_state':{}, 'YT_DLP_RUNTIME_DIR':'/runtime',
            'DOWNLOAD_ACCESS':SimpleNamespace(status=lambda:{'session_state':'saved'})}
        status = load('get_youtube_tools_status', scope); results = []
        def query():
            results.append(status({})); finished.set()
        with lock:
            worker = threading.Thread(target=query); worker.start()
            self.assertFalse(called.wait(0.05))
        self.assertTrue(finished.wait(2)); worker.join(2)
        self.assertEqual(results[0]['yt_dlp_version'], '2026.10.09')
        self.assertEqual(results[0]['source'], 'persistent')

    def test_directory_not_empty_cleanup_never_fails_a_valid_update(self):
        for old_backup in (False, True):
            with self.subTest(old_backup=old_backup), tempfile.TemporaryDirectory() as folder:
                runtime, staging, backup = [str(Path(folder)/name) for name in ('runtime', 'staging', 'backup')]
                Path(runtime).mkdir(); (Path(runtime)/'working').write_text('previous')
                if old_backup:
                    leftover = Path(backup)/'Cryptodome/Util'
                    leftover.mkdir(parents=True); (leftover/'busy').write_text('old package')
                state = {}; real_remove = shutil.rmtree
                def remove(path, *args, **kwargs):
                    if str(path) == backup or '.discarded-' in str(path):
                        raise OSError(errno.ENOTEMPTY, 'Directory not empty', str(Path(path)/'Cryptodome/Util'))
                    return real_remove(path, *args, **kwargs)
                def install(command, **kwargs):
                    if '--target' in command:
                        target = Path(command[command.index('--target')+1])
                        (target/'working').write_text('updated')
                    return SimpleNamespace(returncode=0, stdout='2026.10.09', stderr='')
                scope = {'yt_dlp_update_lock':threading.RLock(), 'yt_dlp_operation_lock':threading.RLock(),
                    'yt_dlp_update_state':state, 'YT_DLP_RUNTIME_DIR':runtime, 'YT_DLP_STAGING_DIR':staging,
                    'YT_DLP_BACKUP_DIR':backup, 'subprocess':SimpleNamespace(run=install),
                    'load_yt_dlp':Mock(), 'yt_dlp_version':lambda:'2026.10.09'}
                with patch('shutil.rmtree', side_effect=remove):
                    load('run_yt_dlp_update', scope)()
                self.assertEqual(state['status'], 'done', state.get('error'))
                self.assertIsNone(state['error'])
                self.assertEqual((Path(runtime)/'working').read_text(), 'updated')

    def test_failed_import_restores_previous_runtime_even_if_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime, staging, backup = [str(Path(folder)/name) for name in ('runtime', 'staging', 'backup')]
            Path(runtime).mkdir(); (Path(runtime)/'working').write_text('previous')
            state = {}; real_remove = shutil.rmtree
            def remove(path, *args, **kwargs):
                if str(path) == runtime or '.discarded-' in str(path):
                    raise OSError(errno.ENOTEMPTY, 'Directory not empty', str(path))
                return real_remove(path, *args, **kwargs)
            scope = {'yt_dlp_update_lock':threading.RLock(), 'yt_dlp_operation_lock':threading.RLock(),
                'yt_dlp_update_state':state, 'YT_DLP_RUNTIME_DIR':runtime, 'YT_DLP_STAGING_DIR':staging,
                'YT_DLP_BACKUP_DIR':backup,
                'subprocess':SimpleNamespace(run=lambda *a, **k:SimpleNamespace(returncode=0, stdout='2026.10.09', stderr='')),
                'load_yt_dlp':Mock(side_effect=[ImportError('broken update'), object()]),
                'yt_dlp_version':lambda:'2026.10.09'}
            with patch('shutil.rmtree', side_effect=remove):
                load('run_yt_dlp_update', scope)()
            self.assertEqual(state['status'], 'error')
            self.assertEqual((Path(runtime)/'working').read_text(), 'previous')
            self.assertIn('broken update', state['error'])

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
                if str(source).startswith(staging+'-'): raise OSError('swap failed')
                real_replace(source,target)
            scope = {'yt_dlp_update_lock':threading.RLock(),'yt_dlp_operation_lock':threading.Lock(),'yt_dlp_update_state':state,
                'YT_DLP_RUNTIME_DIR':runtime,'YT_DLP_STAGING_DIR':staging,'YT_DLP_BACKUP_DIR':backup,
                'subprocess':SimpleNamespace(run=lambda *args,**kwargs:SimpleNamespace(returncode=0,stdout='2026.10.09',stderr='')),
                'load_yt_dlp':Mock(),'yt_dlp_version':lambda:'2026.10.09'}
            with patch('os.replace',side_effect=replace): load('run_yt_dlp_update',scope)()
            self.assertEqual(state['status'],'error'); self.assertEqual((Path(runtime)/'working').read_text(),'previous')
