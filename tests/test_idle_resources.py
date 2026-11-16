import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
import runtime_resources as resources

class IdleResourcesTests(unittest.TestCase):
    def test_transcriber_does_not_import_native_inference_at_server_start(self):
        code="import sys; import transcriber; assert 'faster_whisper' not in sys.modules; assert 'torch' not in sys.modules"
        result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).parents[1]/'app',capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_idle_release_discards_live_models_and_returns_native_cpu_pool_to_one_thread(self):
        whisper=SimpleNamespace(clear_cached_model=Mock())
        cache=SimpleNamespace(cache_clear=Mock())
        torch=SimpleNamespace(set_num_threads=Mock(),cuda=SimpleNamespace(is_initialized=lambda:False,empty_cache=Mock()))
        with patch.dict(sys.modules,{'transcriber':whisper,'faster_whisper.vad':SimpleNamespace(get_vad_model=cache),'torch':torch}):
            resources.release_idle_resources()
        whisper.clear_cached_model.assert_called_once()
        cache.cache_clear.assert_called_once()
        torch.set_num_threads.assert_called_once_with(1)
        torch.cuda.empty_cache.assert_not_called()

    def test_quiet_native_policy_keeps_the_processing_cpu_budget(self):
        with patch.dict(os.environ,{'KARAOKE_CPU_THREADS':'3'},clear=True),patch.object(resources,'_cgroup_cpu_limits',return_value=[]),patch.object(resources.os,'cpu_count',return_value=4),patch.object(resources.os,'sched_getaffinity',return_value={0,1,2,3}):
            resources.configure_idle_runtime()
            self.assertEqual(os.environ['OMP_WAIT_POLICY'],'PASSIVE')
            self.assertEqual(os.environ['GOMP_SPINCOUNT'],'0')
            self.assertEqual(resources.available_cpu_threads(),3)
            self.assertEqual(resources.thread_environment()['OMP_NUM_THREADS'],'3')
