"""Render the reported long-verse/next-line overlap in all display positions."""
import copy
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from karaoke_generator import generate_ass_karaoke
from lyrics_sync import anchor_synced_animation


CURRENT = "And if the words float up to the surface, I'll keep them down"
FOLLOWING = "This is the first time I know I don't want the crown"


class SyncedPreviewLayoutTests(unittest.TestCase):
    def fixture(self):
        verses = [dict(start=0, end=5, text=CURRENT), dict(start=5, end=10, text=FOLLOWING)]
        local = [dict(words=[dict(word='incorrect', start=.2 + i * .25, end=.4 + i * .25)
                             for i in range(len(CURRENT.split()))])]
        return anchor_synced_animation(verses, local)

    def test_reported_overlap_is_fixed_without_cropping_or_changing_provider_data(self):
        segments = self.fixture()
        original = copy.deepcopy(segments)
        for position in ('top', 'middle', 'bottom'):
            for size in (72, 120):
                with self.subTest(position=position, size=size), tempfile.TemporaryDirectory() as folder:
                    target = Path(folder) / 'pair.ass'
                    generate_ass_karaoke(segments, str(target), font_size=size,
                        text_position=position, show_next_line_preview=True, show_instrumental=False)
                    content = target.read_text()
                    events = [line for line in content.splitlines() if line.startswith('Dialogue:')]
                    self.assertEqual(len(events), 3)
                    for event, expected in zip(events[:2], (CURRENT, FOLLOWING)):
                        displayed = re.sub(r'\{[^}]*\}', '', event.split(',',9)[-1]).replace(r'\N', '')
                        self.assertEqual(displayed, expected)
                        self.assertIn('0:00:00.00,0:00:05.00', event)
                    bounds = []
                    for style in ('Default', 'NextLine'):
                        isolated = '\n'.join(line for line in content.splitlines()
                            if not line.startswith('Dialogue:') or f',{style},' in line)
                        target.write_text(isolated)
                        raw = subprocess.check_output(['ffmpeg','-v','error','-f','lavfi','-i',
                            'color=black:s=1280x720:r=25:d=1','-vf','ass='+str(target),
                            '-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'])
                        mask = np.frombuffer(raw, dtype=np.uint8).reshape(720,1280,3).max(axis=2) > 35
                        y, x = np.where(mask)
                        self.assertGreater(len(x), 100)
                        self.assertGreater(x.min(), 25)
                        self.assertLess(x.max(), 1255)
                        self.assertGreater(y.min(), 25)
                        self.assertLess(y.max(), 695)
                        bounds.append((y.min(), y.max()))
                    self.assertGreater(bounds[1][0] - bounds[0][1], 10)
        self.assertEqual(segments, original)

    def test_extreme_word_and_character_limits_keep_every_word_in_the_provider_interval(self):
        segments = self.fixture()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'wrapped.ass'
            generate_ass_karaoke(segments, str(target), font_size=80, words_per_line=1,
                max_chars_line=3, show_next_line_preview=True, text_position='middle', show_instrumental=False)
            event = next(line for line in target.read_text().splitlines() if line.startswith('Dialogue:'))
            self.assertEqual(re.sub(r'\{[^}]*\}', '', event.split(',',9)[-1]).replace(r'\N', ''), CURRENT)
            self.assertIn('0:00:00.00,0:00:05.00', event)
            self.assertNotIn(r'\h', event)
            self.assertNotIn(r'\clip', event)


if __name__ == '__main__':
    unittest.main()
