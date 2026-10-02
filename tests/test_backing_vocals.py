import math
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "app"))
import backing_vocals as backing


def tone(path, frequency, amplitude=0.08, seconds=0.25):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(44100)
        frames = [round(32767 * amplitude * math.sin(2 * math.pi * frequency * i / 44100))
                  for i in range(round(seconds * 44100))]
        audio.writeframes(b"".join(struct.pack("<hh", sample, sample) for sample in frames))


def spectral_amplitude(path, frequency):
    rate = 44100
    data = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path),
                                    '-af', 'pan=mono|c0=c0', '-ar', str(rate), '-f', 'f32le', '-'])
    values = struct.unpack('<' + 'f' * (len(data) // 4), data)
    real = sum(v * math.cos(2 * math.pi * frequency * i / rate) for i, v in enumerate(values))
    imag = sum(v * math.sin(2 * math.pi * frequency * i / rate) for i, v in enumerate(values))
    return 2 * math.hypot(real, imag) / len(values)


class BackingVocalsTests(unittest.TestCase):
    def test_mix_preserves_music_level_and_backing_gain_without_lead(self):
        with tempfile.TemporaryDirectory() as folder:
            instrumental, voices, output = [Path(folder) / f"{x}.wav" for x in ("instrumental", "backing", "output")]
            tone(instrumental, 400)
            tone(voices, 800)
            backing.mix_backing(str(instrumental), str(voices), str(output), 0.5)
            self.assertAlmostEqual(spectral_amplitude(output, 400), 0.08, delta=0.004)
            self.assertAlmostEqual(spectral_amplitude(output, 800), 0.04, delta=0.004)
            self.assertLess(spectral_amplitude(output, 1200), 0.003)
            duration = float(subprocess.check_output(['ffprobe', '-v', 'error',
                '-show_entries', 'format=duration', '-of', 'csv=p=0', str(output)]))
            self.assertAlmostEqual(duration, .25, places=4)

    def test_valid_cached_stems_are_reused_and_volume_is_recomputed(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("lead_vocals.wav", "backing_vocals.wav"):
                tone(Path(folder) / name, 800)
            (Path(folder) / "backing_model_version.txt").write_text(backing.BACKING_MODEL_VERSION)
            def mix(original, voices, output, gain):
                self.assertEqual(original, "clean-instrumental.wav")
                self.assertEqual(gain, 0.3)
                tone(Path(output), 800)
            with patch.object(backing, "run_cancellable") as runner, patch.object(backing, "mix_backing", side_effect=mix):
                lead, output = backing.preserve_backing_vocals("all-voices.wav", "clean-instrumental.wav", folder, 0.3)
                runner.assert_not_called()
                self.assertEqual(Path(lead).name, "lead_vocals.wav")
                self.assertTrue(Path(output).is_file())

    def test_failed_model_does_not_create_a_cache_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(backing, "run_cancellable", side_effect=RuntimeError("failed")) as runner:
                with self.assertRaises(RuntimeError):
                    backing.preserve_backing_vocals("all-voices.wav", "clean-instrumental.wav", folder)
                self.assertEqual(runner.call_args.kwargs["env"]["CUDA_VISIBLE_DEVICES"], "-1")
            self.assertFalse((Path(folder) / "backing_model_version.txt").exists())
            self.assertFalse((Path(folder) / "instrumental_with_backing.wav").exists())

    def test_inference_progress_ignores_preparation_bars_and_allows_phase_reset(self):
        callback, stages = Mock(), Mock()
        events = [('preparing_audio',25),('preparing_audio',100),
                  ('preparing_windows',0),('preparing_windows',100),
                  ('inference',0),('inference',25),('inference',75),
                  ('inference',50),('inference',100),('inference',100),('reconstructing',None)]
        script = "print('Downloading model: 100%'); print('100%|4/4'); print('100%|55/55'); print('0%|0/55')\n"
        for phase, percent in events:
            line = 'SAL0_BVE_PROGRESS ' + json.dumps({'phase':phase,'percent':percent})
            script += 'print(' + repr(line) + ')\n'
        backing.run_cancellable([sys.executable,'-c',script], progress_callback=callback)
        self.assertEqual([call.args[0] for call in callback.call_args_list], [0,25,75,100])
        backing.run_cancellable([sys.executable,'-c',script], stage_callback=stages)
        self.assertIn(('preparing_windows',100), [c.args for c in stages.call_args_list])
        self.assertIn(('inference',0), [c.args for c in stages.call_args_list])
        self.assertEqual(stages.call_args.args, ('reconstructing',None))

    def test_stage_percentage_matches_inference_logs_before_separate_mix_stage(self):
        callback = Mock()
        with tempfile.TemporaryDirectory() as folder:
            def infer(command, **kwargs):
                for percent in (0, 25, 75, 100):
                    kwargs["progress_callback"](percent)
                for name in ("lead_vocals.wav", "backing_vocals.wav"):
                    tone(Path(command[3]) / name, 800)
            def mix(original, voices, output, gain):
                tone(Path(output), 800)
            with patch.object(backing, "run_cancellable", side_effect=infer), patch.object(backing, "mix_backing", side_effect=mix):
                backing.preserve_backing_vocals("vocals.wav", "instrumental.wav", folder, update_callback=callback)
        inference = [call.kwargs["stage_progress"] for call in callback.call_args_list
                     if call.args[1] == "Separando backing vocals"]
        self.assertEqual(inference, [0, 0, 25, 75, 100])
        self.assertEqual(callback.call_args_list[-2].args[1], "Misturando backing vocals")
        self.assertEqual(callback.call_args_list[-2].kwargs["stage_progress"], 0)
        self.assertEqual(callback.call_args_list[-1].kwargs["stage_progress"], 100)

    def test_preparation_one_hundred_does_not_hold_inference_at_one_hundred(self):
        callback = Mock()
        with tempfile.TemporaryDirectory() as folder:
            def infer(command, **kwargs):
                for phase,percent in [('preparing_audio',100),('preparing_windows',100),
                                      ('inference',0),('inference',50),('inference',100),('reconstructing',None)]:
                    kwargs['stage_callback'](phase,percent)
                for name in ('lead_vocals.wav','backing_vocals.wav'):
                    tone(Path(command[3])/name,800)
            with patch.object(backing,'run_cancellable',side_effect=infer), patch.object(backing,'mix_backing',
                    side_effect=lambda original,voices,output,gain:tone(Path(output),800)):
                backing.preserve_backing_vocals('voices.wav','music.wav',folder,update_callback=callback)
        analysis = [c.kwargs['stage_progress'] for c in callback.call_args_list
                    if c.args[1]=='Separando backing vocals']
        self.assertEqual(analysis,[0,0,50,100])
        reconstruction = next(c for c in callback.call_args_list if c.args[1]=='Gerando faixas de backing vocals')
        self.assertIsNone(reconstruction.kwargs['stage_progress'])

    def test_gain_outside_the_supported_range_is_rejected(self):
        for gain in (-1, 1.1, float("nan")):
            with self.assertRaises(ValueError):
                backing.mix_backing("instrumental", "backing", "output", gain)


if __name__ == "__main__":
    unittest.main()
