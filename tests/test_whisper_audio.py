import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import process_manager as pm
from whisper_audio import load_whisper_audio


class WhisperAudioTests(unittest.TestCase):
    def setUp(self):
        pm.cancel_event.clear()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.audio = Path(self.folder.name) / 'lead.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.5', '-ar', '44100', '-ac', '2',
                        str(self.audio)], check=True)

    def tearDown(self):
        pm.cancel_event.clear()
        self.assertIsNone(pm.active_process)

    def test_stereo_resampled_and_normalized(self):
        audio = load_whisper_audio(self.audio)
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.shape, (8000,))
        self.assertGreater(float(np.max(np.abs(audio))), 0.05)
        self.assertLess(float(np.max(np.abs(audio))), 1)

    def test_float_decode_preserves_samples_smaller_than_a_16_bit_step(self):
        path = self.audio.with_name('quiet.wav')
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
            'sine=frequency=440:duration=0.5','-af','volume=0.00008',
            '-c:a','pcm_f32le',str(path)],check=True)
        audio = load_whisper_audio(path)
        self.assertGreater(float(np.max(np.abs(audio))), .000005)
        self.assertLess(float(np.max(np.abs(audio))), 1/32768)

    def test_max_quality_uses_float_precision_and_guided_vocabulary(self):
        info = SimpleNamespace(language='pt', language_probability=1, duration=.5)
        transcribe = Mock(return_value=(iter([]), info))
        model = Mock(return_value=SimpleNamespace(transcribe=transcribe))
        module = self.load_transcriber(model)
        with patch.object(module.os, 'makedirs'):
            module.transcribe_vocals(str(self.audio), quality_mode='max_quality',
                                    initial_prompt='cantar você cantar')
        self.assertEqual(model.call_args.kwargs['compute_type'], 'float32')
        self.assertGreaterEqual(transcribe.call_args.kwargs['beam_size'], 10)
        self.assertEqual(transcribe.call_args.kwargs['hotwords'], 'cantar você')

    def test_compressed_audio_and_video(self):
        for extension in ('mp3', 'mp4'):
            path = self.audio.with_suffix('.' + extension)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.audio), str(path)], check=True)
            audio = load_whisper_audio(path)
            self.assertEqual(audio.dtype, np.float32)
            self.assertGreater(audio.size, 7000)

    def test_invalid_audio_reports_decode_error(self):
        self.audio.write_bytes(b'not audio')
        with self.assertRaisesRegex(RuntimeError, 'abrir o áudio'):
            load_whisper_audio(self.audio)

    def test_cancelled_before_launch(self):
        pm.cancel_event.set()
        with patch('whisper_audio.subprocess.Popen') as launch:
            with self.assertRaises(InterruptedError):
                load_whisper_audio(self.audio)
            launch.assert_not_called()

    def test_cancelled_after_decode(self):
        real_check = pm.check_cancelled
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 2:
                pm.cancel_event.set()
            real_check()
        with patch.object(pm, 'check_cancelled', side_effect=check):
            with self.assertRaises(InterruptedError):
                load_whisper_audio(self.audio)

    def load_transcriber(self, model):
        spec = importlib.util.spec_from_file_location('isolated_transcriber', ROOT / 'app/transcriber.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=model)}):
            spec.loader.exec_module(module)
        module.get_model_local_dir = lambda _: self.folder.name
        return module

    def test_array_bypasses_incompatible_pyav_and_vad_retry_reuses_it(self):
        inputs = []
        info = SimpleNamespace(language='pt', language_probability=1, duration=0.5)
        def transcribe(audio, **options):
            if isinstance(audio, str):
                raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")
            inputs.append(audio)
            self.assertEqual(audio.dtype, np.float32)
            if options.get('vad_filter'):
                raise RuntimeError('VAD unavailable')
            return iter([]), info
        model = Mock(return_value=SimpleNamespace(transcribe=transcribe))
        module = self.load_transcriber(model)
        progress = []
        with patch.object(module.os, 'makedirs'):
            result, metadata = module.transcribe_vocals(str(self.audio), enable_vad=True,
                return_info=True, progress_callback=lambda percent, *_: progress.append(percent))
        self.assertEqual(result, [])
        self.assertEqual(metadata['language'], 'pt')
        self.assertEqual(progress[-1], 100)
        self.assertEqual(len(inputs), 2)
        self.assertIs(inputs[0], inputs[1])

    def test_decode_failure_does_not_load_model(self):
        model = Mock()
        module = self.load_transcriber(model)
        self.audio.write_bytes(b'broken')
        with self.assertRaises(RuntimeError):
            module.transcribe_vocals(str(self.audio))
        model.assert_not_called()
