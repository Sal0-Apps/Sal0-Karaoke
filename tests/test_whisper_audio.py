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
        self.assertEqual(transcribe.call_args.kwargs['initial_prompt'], 'cantar você cantar')

    def test_guided_retry_uses_full_audio_and_ignores_provider_clocks(self):
        info = SimpleNamespace(language='pt', language_probability=1, duration=.5)
        word = SimpleNamespace(word=' cantar', start=.1, end=.4, probability=.92)
        transcribe = Mock(return_value=(iter([SimpleNamespace(start=0, end=.5,
            text='cantar', words=[word])]), info))
        module = self.load_transcriber(Mock(return_value=SimpleNamespace(transcribe=transcribe)))
        with patch.object(module.os, 'makedirs'):
            result = module.transcribe_vocals(str(self.audio), quality_mode='max_quality',
                initial_prompt='[offset:8000]\n[00:45]cantar você cantar', guidance_retry=True,
                guide_vocabulary='[00:50]você cantar', enable_vad=False)
        options = transcribe.call_args.kwargs
        self.assertEqual(transcribe.call_args.args[0].shape, (8000,))
        self.assertEqual(options['initial_prompt'], 'cantar você cantar')
        self.assertEqual(options['hotwords'], 'você cantar')
        self.assertGreaterEqual(options['beam_size'], 15)
        self.assertGreaterEqual(options['patience'], 2)
        self.assertNotIn('clip_timestamps', options)
        self.assertNotIn('prefix', options)
        self.assertFalse(options.get('vad_filter', False))
        self.assertEqual(result[0]['words'][0]['probability'], .92)
        self.assertEqual((result[0]['words'][0]['start'], result[0]['words'][0]['end']), (.1,.4))

    def test_cancelled_progress_aborts_without_vad_retry(self):
        info = SimpleNamespace(language='pt', language_probability=1, duration=.5)
        transcribe = Mock(return_value=(iter([]), info))
        module = self.load_transcriber(Mock(return_value=SimpleNamespace(transcribe=transcribe)))
        with patch.object(module.os, 'makedirs'), self.assertRaises(InterruptedError):
            module.transcribe_vocals(str(self.audio), enable_vad=True,
                progress_callback=Mock(side_effect=InterruptedError('cancelado')))
        transcribe.assert_called_once()

    def test_compressed_audio_and_video(self):
        for extension in ('mp3', 'mp4'):
            path = self.audio.with_suffix('.' + extension)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.audio), str(path)], check=True)
            audio = load_whisper_audio(path)
            self.assertEqual(audio.dtype, np.float32)
            self.assertGreater(audio.size, 7000)

    def test_decode_keeps_the_full_timeline_silence_and_sustained_notes(self):
        path = self.audio.with_name('complete.wav')
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
            'aevalsrc=if(between(t\\,1\\,1.5)+between(t\\,3\\,3.8)\\,0.2*sin(2*PI*440*t)\\,0):s=44100:d=4',
            '-ac','2','-c:a','pcm_f32le',str(path)],check=True)
        audio = load_whisper_audio(path)
        self.assertEqual(audio.shape,(64000,))
        def rms(a,b):
            chunk=audio[int(a*16000):int(b*16000)]
            return float(np.sqrt(np.mean(chunk*chunk)))
        self.assertLess(rms(0,.8),.001)
        self.assertAlmostEqual(rms(1.1,1.4),.1,delta=.005)
        self.assertLess(rms(1.7,2.8),.001)
        self.assertAlmostEqual(rms(3.1,3.7),.1,delta=.005)

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
