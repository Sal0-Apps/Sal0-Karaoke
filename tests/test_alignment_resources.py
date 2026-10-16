from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from lyric_alignment import AudioEvidence


class AudioEvidenceResourceTests(unittest.TestCase):
    def test_reduced_allocation_keeps_the_same_silence_decisions(self):
        random = np.random.default_rng(42)
        for duration in (1, 320, 16000, 16123):
            for gain in (1e-7, .1, 1.):
                audio = random.normal(size=duration).astype(np.float32) * gain
                audio[:duration // 3] = 0
                evidence = AudioEvidence(audio)
                padded = np.pad(audio, (0, (-len(audio)) % evidence.hop))
                frames = padded.reshape(-1, evidence.hop)
                original = np.sqrt(np.mean(frames.astype(np.float64)**2, axis=1))
                np.testing.assert_allclose(evidence.rms, original, rtol=1e-12, atol=0)
                threshold = max(1e-8, float(np.quantile(original, .98)) * .005)
                np.testing.assert_array_equal(evidence.active, original > threshold)


if __name__ == '__main__':
    unittest.main()
