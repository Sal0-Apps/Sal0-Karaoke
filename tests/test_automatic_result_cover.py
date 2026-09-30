import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from media_covers import video_thumbnail
from audio_processor import get_effective_cpu_count


class ResultCoverTests(unittest.TestCase):
    def test_result_thumbnail_uses_opening_cover_while_source_preview_uses_later_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); video = root / 'video.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=red:size=64x36:duration=1',
                '-f', 'lavfi', '-i', 'color=blue:size=64x36:duration=3', '-filter_complex',
                '[0:v][1:v]concat=n=2:v=1:a=0[out]', '-map', '[out]', '-c:v', 'libx264', str(video)], check=True)
            with patch('media_covers.THUMBNAIL_ROOT', root / 'cache'):
                cover = video_thumbnail(video, cover=True)
                preview = video_thumbnail(video)
                self.assertNotEqual(cover, preview)
                self.assertTrue(cover.is_file())
                def color(path):
                    rgb = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
                    return rgb[:3]
                red, green, blue = color(cover); self.assertGreater(red, blue + 100)
                red, green, blue = color(preview); self.assertGreater(blue, red + 100)
                self.assertEqual(video_thumbnail(video, cover=True), cover)

    def test_explicit_cpu_cap_respects_affinity_and_does_not_repurpose_quota(self):
        with patch('audio_processor.os.cpu_count', return_value=16), patch('audio_processor.os.sched_getaffinity', return_value=set(range(8))):
            with patch.dict(os.environ, {'KARAOKE_CPU_THREADS': '3'}): self.assertEqual(get_effective_cpu_count(), 3)
            with patch.dict(os.environ, {'KARAOKE_CPU_THREADS': '32'}): self.assertEqual(get_effective_cpu_count(), 8)
            with patch.dict(os.environ, {'KARAOKE_CPU_THREADS': 'invalid'}): self.assertEqual(get_effective_cpu_count(), 8)
