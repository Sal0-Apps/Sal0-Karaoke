import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "app"))
import whisper_models as models


class WhisperModelDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sizes = patch.dict(models.MINIMUM_MODEL_BYTES, {key: 4 for key in models.MODEL_REPOSITORIES})
        self.sizes.start()
        self.addCleanup(self.sizes.stop)

    def model(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "model.bin").write_bytes(b"weights")
        (directory / "config.json").write_text(json.dumps({"alignment_heads": []}))
        return directory

    def locate(self, name):
        return models.get_model_local_dir(name, [self.root])

    def test_huggingface_snapshot_and_direct_persistent_directory(self):
        snapshot = self.model(self.root / "models--Systran--faster-whisper-medium" / "snapshots" / "revision")
        self.assertEqual(self.locate("medium"), str(snapshot))
        direct = self.model(self.root / "small")
        self.assertEqual(self.locate("small"), str(direct))

    def test_missing_invalid_config_and_truncated_weights_are_not_downloaded(self):
        directory = self.model(self.root / "medium")
        (directory / "config.json").unlink()
        self.assertIsNone(self.locate("medium"))
        (directory / "config.json").write_text("unfinished")
        self.assertIsNone(self.locate("medium"))
        (directory / "config.json").write_text("{}")
        (directory / "model.bin").write_bytes(b"x")
        self.assertIsNone(self.locate("medium"))

    def test_tiny_and_base_are_distinct_and_turbo_is_not_large_v3(self):
        tiny = self.model(self.root / "faster-whisper-tiny")
        turbo = self.model(self.root / "faster-whisper-large-v3-turbo")
        self.assertEqual(self.locate("tiny"), str(tiny))
        self.assertIsNone(self.locate("base"))
        self.assertIsNone(self.locate("large-v3"))
        self.assertEqual(self.locate("turbo"), str(turbo))
        base = self.model(self.root / "faster-whisper-base")
        self.assertEqual(self.locate("base"), str(base))

    def test_pytorch_weights_are_not_treated_as_ctranslate2(self):
        directory = self.model(self.root / "medium")
        (directory / "model.bin").rename(directory / "pytorch_model.bin")
        self.assertIsNone(self.locate("medium"))

    def test_large_v2_and_model_directory_as_root(self):
        directory = self.model(self.root / "faster-whisper-large-v2")
        self.assertEqual(models.get_model_local_dir("large-v2", [directory]), str(directory))


if __name__ == "__main__":
    unittest.main()
