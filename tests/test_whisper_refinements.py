"""Exercise Whisper decoding policy without downloading or running AI models."""
import copy
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "app"))
from whisperx_align import stabilize_word_timestamps


def segment(text=" cantar", start=1.0, end=1.4):
    word = SimpleNamespace(word=text, start=start, end=end, probability=0.92)
    return SimpleNamespace(start=start, end=end, text=text.strip(), words=[word])


class CharacterTokenizer:
    """One token per codepoint exposes the bug in character-only prompt limits."""
    def encode(self, text, add_special_tokens=False):
        return SimpleNamespace(ids=[ord(character) for character in text])

    def decode(self, tokens):
        return "".join(chr(token) for token in tokens)


class WhisperRefinementTests(unittest.TestCase):
    def setUp(self):
        self.info = SimpleNamespace(language="en", language_probability=0.91, duration=10.0)
        self.audio = np.zeros(160000, dtype=np.float32)

    def load_transcriber(self, factory):
        spec = importlib.util.spec_from_file_location("isolated_whisper_refinements", ROOT / "app/transcriber.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=factory)}):
            spec.loader.exec_module(module)
        module.load_whisper_audio = Mock(return_value=self.audio)
        module.get_model_local_dir = Mock(return_value="/local/selected-whisper")
        module.whisper_runtime_options = Mock(side_effect=lambda quality_mode="standard", cpu_threads=None, device=None: {
            "device": device or "cpu", "compute_type": "float32" if "max" in quality_mode else "int8",
            "cpu_threads": cpu_threads or 4, "num_workers": 1,
        })
        self.addCleanup(module.clear_cached_model)
        return module

    def run_transcriber(self, module, **options):
        with patch.object(module.os, "makedirs"):
            return module.transcribe_vocals("vocals.wav", **options)

    def test_prompt_and_vocabulary_share_one_token_budget(self):
        transcribe = Mock(return_value=(iter([segment()]), self.info))
        model = SimpleNamespace(transcribe=transcribe, hf_tokenizer=CharacterTokenizer(), max_length=448)
        module = self.load_transcriber(Mock(return_value=model))
        guide = " ".join("語彙" + str(index) for index in range(350))
        self.run_transcriber(module, initial_prompt=guide, guidance_retry=True)
        options = transcribe.call_args.kwargs
        tokenizer = model.hf_tokenizer
        count = sum(len(tokenizer.encode(" " + options[key]).ids)
                    for key in ("initial_prompt", "hotwords") if options[key])
        self.assertLessEqual(count, 216)
        self.assertTrue(options["initial_prompt"].startswith("語彙0"))
        self.assertGreaterEqual(options["beam_size"], 15)
        self.assertFalse(options["condition_on_previous_text"])
        self.assertNotIn("language", options)
        self.assertEqual(options["language_detection_segments"], 3)

    def test_short_guidance_and_translation_keep_existing_behavior(self):
        transcribe = Mock(return_value=(iter([segment()]), self.info))
        factory = Mock(return_value=SimpleNamespace(
            transcribe=transcribe, hf_tokenizer=CharacterTokenizer(), max_length=448))
        module = self.load_transcriber(factory)
        result, metadata = self.run_transcriber(module, initial_prompt="[00:45]cantar você cantar",
            quality_mode="max_quality", task="translate", return_info=True)
        options = transcribe.call_args.kwargs
        self.assertEqual(options["initial_prompt"], "cantar você cantar")
        self.assertEqual(options["hotwords"], "cantar você")
        self.assertEqual(options["task"], "translate")
        self.assertEqual(metadata["language"], "en")
        self.assertEqual(result[0]["words"][0]["probability"], 0.92)
        self.assertEqual(factory.call_args.kwargs["compute_type"], "float32")

    def test_lazy_vad_failure_discards_partial_attempt_and_reuses_audio(self):
        def interrupted():
            yield segment(" partial", .1, .4)
            raise RuntimeError("VAD unavailable during iteration")

        transcribe = Mock(side_effect=[(interrupted(), self.info), (iter([segment()]), self.info)])
        factory = Mock(return_value=SimpleNamespace(transcribe=transcribe))
        module = self.load_transcriber(factory)
        result = self.run_transcriber(module, enable_vad=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "cantar")
        self.assertEqual(transcribe.call_count, 2)
        self.assertTrue(transcribe.call_args_list[0].kwargs["vad_filter"])
        self.assertFalse(transcribe.call_args_list[1].kwargs["vad_filter"])
        for call in transcribe.call_args_list:
            self.assertIs(call.args[0], self.audio)
        factory.assert_called_once()

    def test_empty_vad_retries_full_audio_once_and_unfiltered_empty_does_not_retry(self):
        transcribe = Mock(side_effect=[(iter([]), self.info), (iter([]), self.info), (iter([]), self.info)])
        module = self.load_transcriber(Mock(return_value=SimpleNamespace(transcribe=transcribe)))
        self.assertEqual(self.run_transcriber(module, enable_vad=True), [])
        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(self.run_transcriber(module, enable_vad=False), [])
        self.assertEqual(transcribe.call_count, 3)

    def test_cancelled_generator_never_retries(self):
        def cancelled():
            yield segment()
            raise InterruptedError("cancelado")
        transcribe = Mock(return_value=(cancelled(), self.info))
        module = self.load_transcriber(Mock(return_value=SimpleNamespace(transcribe=transcribe)))
        with self.assertRaises(InterruptedError):
            self.run_transcriber(module, enable_vad=True)
        transcribe.assert_called_once()

    def test_revisions_reuse_one_model_and_explicit_release_reloads(self):
        transcribe = Mock(side_effect=lambda *_args, **_kwargs: (iter([segment()]), self.info))
        factory = Mock(return_value=SimpleNamespace(transcribe=transcribe))
        module = self.load_transcriber(factory)
        self.run_transcriber(module)
        self.run_transcriber(module, guidance_retry=True)
        factory.assert_called_once()
        module.clear_cached_model()
        self.run_transcriber(module)
        self.assertEqual(factory.call_count, 2)

    def test_model_load_failure_never_switches_to_medium(self):
        factory = Mock(side_effect=RuntimeError("download indisponível"))
        module = self.load_transcriber(factory)
        module.get_model_local_dir.return_value = None
        with self.assertRaisesRegex(RuntimeError, "download indisponível"):
            self.run_transcriber(module, model_size="large-v3")
        self.assertEqual(factory.call_count, 2)
        self.assertTrue(all(call.args[0] == "Systran/faster-whisper-large-v3"
                            for call in factory.call_args_list))

    def test_cpu_memory_failure_does_not_redownload_weights(self):
        factory = Mock(side_effect=RuntimeError("out of memory"))
        module = self.load_transcriber(factory)
        with self.assertRaisesRegex(RuntimeError, "out of memory"):
            self.run_transcriber(module)
        factory.assert_called_once()

    def test_older_faster_whisper_signature_omits_only_new_detection_options(self):
        module = self.load_transcriber(Mock())
        def legacy_transcribe(audio, word_timestamps=False):
            pass
        options = module._compatible_options(SimpleNamespace(transcribe=legacy_transcribe), {
            "word_timestamps": True, "language_detection_segments": 3, "language_detection_threshold": .7,
        })
        self.assertEqual(options, {"word_timestamps": True})

    def test_cuda_generator_failure_retries_same_model_on_cpu(self):
        def cuda_failure():
            yield segment(" partial", .1, .4)
            raise RuntimeError("CUDA out of memory")
        gpu = SimpleNamespace(transcribe=Mock(return_value=(cuda_failure(), self.info)))
        cpu = SimpleNamespace(transcribe=Mock(return_value=(iter([segment()]), self.info)))
        factory = Mock(side_effect=[gpu, cpu])
        module = self.load_transcriber(factory)
        module.whisper_runtime_options.side_effect = lambda **kwargs: {
            "device": kwargs.get("device") or "cuda", "compute_type": "float32",
            "cpu_threads": 4, "num_workers": 1,
        }
        result = self.run_transcriber(module, model_size="large-v3", quality_mode="max_quality")
        self.assertEqual(result[0]["text"], "cantar")
        self.assertEqual([call.args[0] for call in factory.call_args_list],
                         ["/local/selected-whisper"] * 2)
        self.assertEqual([call.kwargs["device"] for call in factory.call_args_list], ["cuda", "cpu"])
        self.assertEqual(factory.call_args.kwargs["compute_type"], "float32")

    def test_cpu_reload_failure_preserves_original_error(self):
        gpu = SimpleNamespace(transcribe=Mock(side_effect=RuntimeError("CUDA error")))
        factory = Mock(side_effect=[gpu, RuntimeError("CPU original error"), RuntimeError("CPU original error"), RuntimeError("CPU original error")])
        module = self.load_transcriber(factory)
        module.whisper_runtime_options.side_effect = lambda **kwargs: {
            "device": kwargs.get("device") or "cuda", "compute_type": "float32",
            "cpu_threads": 4, "num_workers": 1,
        }
        with self.assertRaisesRegex(RuntimeError, "CPU original error"):
            self.run_transcriber(module)


class WhisperTimestampRefinementTests(unittest.TestCase):
    def test_short_valid_syllables_pauses_and_sustained_notes_are_preserved(self):
        source = [{"start": 0, "end": 9, "text": "a cantar", "words": [
            {"word": " a", "start": .5, "end": .52},
            {"word": " cantar", "start": 3, "end": 7},
        ]}]
        before = copy.deepcopy(source)
        result = stabilize_word_timestamps(source)
        self.assertEqual(result[0]["words"], source[0]["words"])
        self.assertEqual((result[0]["start"], result[0]["end"]), (.5, 7))
        self.assertEqual(source, before)

    def test_cross_segment_overlap_updates_both_segment_bounds(self):
        source = [
            {"start": 0, "end": 1, "words": [{"word": " eu", "start": 0, "end": 1}]},
            {"start": .9, "end": 1.2, "words": [{"word": " canto", "start": .9, "end": 1.2}]},
        ]
        result = stabilize_word_timestamps(source)
        self.assertAlmostEqual(result[0]["end"], .95)
        self.assertEqual(result[0]["end"], result[0]["words"][-1]["end"])
        self.assertEqual(result[0]["end"], result[1]["start"])

    def test_words_cannot_extend_past_audio_end(self):
        source = [{"start": 9, "end": 12, "words": [
            {"word": " final", "start": 9, "end": 10.5},
            {"word": " inválida", "start": 11, "end": 12},
        ]}]
        result = stabilize_word_timestamps(source, audio_duration=10)
        self.assertEqual(len(result[0]["words"]), 1)
        self.assertEqual(result[0]["end"], 10)


if __name__ == "__main__":
    unittest.main()
