import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
import audio_processor
import process_manager as pm
import runtime_resources as resources
import video_renderer


class RuntimeResourcesTests(unittest.TestCase):
    def setUp(self):
        pm.cancel_event.clear()
        pm.clear_active_process()

    def tearDown(self):
        pm.cancel_event.clear()
        pm.clear_active_process()

    def test_cpu_budget_uses_all_four_threads_and_clamps_affinity_quota_and_override(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(resources.os, "cpu_count", return_value=4), patch.object(resources.os, "sched_getaffinity", return_value={0, 1, 2, 3}, create=True), patch.object(resources, "_cgroup_cpu_limits", return_value=[]):
            self.assertEqual(resources.available_cpu_threads(), 4)
            self.assertEqual(resources.available_cpu_threads(3), 3)
            self.assertEqual(resources.available_cpu_threads(99), 4)
            with patch.dict(os.environ, {"KARAOKE_CPU_THREADS": "2"}):
                self.assertEqual(resources.available_cpu_threads(), 2)
            with patch.dict(os.environ, {"KARAOKE_CPU_THREADS": "invalid"}):
                self.assertEqual(resources.available_cpu_threads(), 4)
            with patch.object(resources, "_cgroup_cpu_limits", return_value=[1]):
                self.assertEqual(resources.available_cpu_threads(4), 1)
            with patch.object(resources.os, "sched_getaffinity", return_value={0, 1}, create=True):
                self.assertEqual(resources.available_cpu_threads(), 2)

    def test_cpu_detection_handles_unavailable_affinity(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(resources.os, "cpu_count", return_value=None), patch.object(resources.os, "sched_getaffinity", side_effect=OSError, create=True), patch.object(resources, "_cgroup_cpu_limits", return_value=[]):
            self.assertEqual(resources.available_cpu_threads(), 1)
            with patch.object(resources.os, "sched_getaffinity", return_value={0, 1}, create=True):
                self.assertEqual(resources.available_cpu_threads(), 2)

    def test_cgroup_v2_nested_and_parent_quotas_and_v1_fractional_budget(self):
        files = {
            "/proc/self/cgroup": "0::/services/karaoke\n",
            "/sys/fs/cgroup/cpu.max": "max 100000",
            "/sys/fs/cgroup/services/cpu.max": "200000 100000",
            "/sys/fs/cgroup/services/karaoke/cpu.max": "150000 100000",
        }
        read = lambda path: files.get(str(path).replace("\\", "/"), "")
        with patch.object(resources, "_read_text", side_effect=read):
            self.assertEqual(sorted(resources._cgroup_cpu_limits()), [2, 2])
        files = {
            "/proc/self/cgroup": "2:cpu,cpuacct:/docker/karaoke\n",
            "/sys/fs/cgroup/cpu/docker/karaoke/cpu.cfs_quota_us": "100000",
            "/sys/fs/cgroup/cpu/docker/karaoke/cpu.cfs_period_us": "100000",
        }
        with patch.object(resources, "_read_text", side_effect=read):
            self.assertEqual(resources._cgroup_cpu_limits(), [1])

    def test_whisper_uses_supported_precision_and_explicit_cpu_fallback(self):
        ct2 = types.SimpleNamespace(
            get_cuda_device_count=lambda: 1,
            get_supported_compute_types=lambda device: {"float32", "int8", "int8_float32"} if device == "cpu" else {"float16", "int8_float16"},
        )
        with patch.dict(sys.modules, {"ctranslate2": ct2}), patch.dict(os.environ, {}, clear=True), patch.object(resources, "available_cpu_threads", return_value=4):
            self.assertEqual(resources.whisper_runtime_options()["device"], "cuda")
            self.assertEqual(resources.whisper_runtime_options()["compute_type"], "int8_float16")
            self.assertEqual(resources.whisper_runtime_options("max_quality", device="cpu")["compute_type"], "float32")
            self.assertEqual(resources.whisper_runtime_options(device="cpu")["compute_type"], "int8")
            with patch.dict(os.environ, {"WHISPER_COMPUTE_TYPE": "int8_float32"}):
                self.assertEqual(resources.whisper_runtime_options("max_quality", device="cpu")["compute_type"], "int8_float32")
            with patch.dict(os.environ, {"WHISPER_COMPUTE_TYPE": "float16"}):
                self.assertEqual(resources.whisper_runtime_options("max_quality", device="cpu")["compute_type"], "float32")
        ct2.get_cuda_device_count = Mock(side_effect=RuntimeError("CUDA library absent"))
        with patch.dict(sys.modules, {"ctranslate2": ct2}), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resources.whisper_runtime_options()["device"], "cpu")

    def test_demucs_parent_budget_reaches_torch_in_runner(self):
        captured = {}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "track.wav"
            output = Path(directory) / "htdemucs_ft" / source.stem
            output.mkdir(parents=True)
            for name in ("vocals.wav", "no_vocals.wav"):
                (output / name).touch()
            process = types.SimpleNamespace(stdout=io.StringIO("100%\n"), returncode=0,
                                            wait=lambda: 0, poll=lambda: 0)
            def launch(command, **kwargs):
                captured.update(kwargs["env"])
                self.assertEqual(command[command.index("--jobs") + 1], "0")
                self.assertIn("--float32", command)
                return process
            with patch.object(resources, "_cgroup_cpu_limits", return_value=[]), patch.object(resources.os, "cpu_count", return_value=4), patch.object(resources.os, "sched_getaffinity", return_value={0, 1, 2, 3}, create=True), patch.dict(os.environ, {}, clear=True), patch.object(audio_processor.subprocess, "Popen", side_effect=launch):
                audio_processor.separate_vocals(str(source), directory)
            self.assertEqual(captured["DEMUCS_CPU_THREADS"], "4")
            self.assertEqual(captured["OMP_NUM_THREADS"], "4")
            self.assertEqual(captured["OMP_WAIT_POLICY"], "PASSIVE")
            torch = types.SimpleNamespace(set_num_threads=Mock(), set_num_interop_threads=Mock())
            demucs = types.SimpleNamespace(main=Mock())
            with patch.dict(sys.modules, {"torch": torch, "demucs.separate": demucs}), patch.dict(os.environ, captured, clear=True), patch.object(resources, "available_cpu_threads", return_value=4):
                runpy.run_path(str(APP / "demucs_runner.py"), run_name="__main__")
            torch.set_num_threads.assert_called_once_with(4)
            torch.set_num_interop_threads.assert_called_once_with(1)
        self.assertIsNone(pm.active_process)

    def test_old_process_cleanup_cannot_clear_new_process(self):
        old, new = object(), object()
        pm.set_active_process(new)
        pm.clear_active_process(old)
        self.assertIs(pm.active_process, new)

    def test_cancel_arriving_between_launch_and_registration_reaps_child(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            pm.cancel_event.set()
            with self.assertRaises(InterruptedError):
                pm.set_active_process(process)
            self.assertIsNotNone(process.poll())
            self.assertIsNone(pm.active_process)
        finally:
            pm.stop_process(process)

    def test_ffmpeg_callback_failure_reaps_process_and_preserves_explicit_threads(self):
        process = Mock(stdout=io.StringIO(""))
        process.poll.return_value = None
        callback = Mock(side_effect=RuntimeError("callback failed"))
        with patch.object(video_renderer.subprocess, "Popen", return_value=process) as launch:
            with self.assertRaisesRegex(RuntimeError, "callback failed"):
                video_renderer.run_ffmpeg_with_logging(["ffmpeg", "-i", "input", "-threads", "1", "out.png"], progress_callback=callback, total_duration=1)
        command = launch.call_args.args[0]
        self.assertEqual(command[command.index("-threads") + 1], "1")
        self.assertNotIn("-threads:v", command)
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertIsNone(pm.active_process)

    def test_ffmpeg_progress_and_error_diagnostics_are_retained(self):
        process = Mock(stdout=io.StringIO("out_time_ms=500000\nprogress=continue\n"), returncode=0)
        process.poll.return_value = 0
        callback = Mock()
        with patch.object(video_renderer.subprocess, "Popen", return_value=process):
            video_renderer.run_ffmpeg_with_logging(["ffmpeg", "-i", "input", "out.mp4"], progress_callback=callback, total_duration=1)
        self.assertEqual([call.args[0] for call in callback.call_args_list], [0, 50, 100])
        process = Mock(stdout=io.StringIO("Unable to open output file: permission denied\n"), returncode=1)
        process.poll.return_value = 1
        with patch.object(video_renderer.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "permission denied"):
                video_renderer.run_ffmpeg_with_logging(["ffmpeg", "-i", "input", "out.mp4"])


if __name__ == "__main__":
    unittest.main()
