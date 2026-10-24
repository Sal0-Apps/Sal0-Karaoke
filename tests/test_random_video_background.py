import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from video_renderer import random_background_start, render_karaoke_video


class RandomBackgroundTests(unittest.TestCase):
    def test_long_background_uses_full_song_excerpt_within_bounds(self):
        with patch('video_renderer.get_file_duration', return_value=100), patch('video_renderer.random.uniform', return_value=42) as choose:
            self.assertEqual(random_background_start('background.mp4', 30), 42)
            choose.assert_called_once_with(0.0, 70.0)

    def test_short_equal_invalid_backgrounds_start_at_zero(self):
        for length in (0, -1, 10, 30, float('nan'), float('inf')):
            with self.subTest(length=length), patch('video_renderer.get_file_duration', return_value=length), patch('video_renderer.random.uniform') as choose:
                self.assertEqual(random_background_start('background.mp4', 30), 0)
                choose.assert_not_called()
        with patch('video_renderer.get_file_duration', side_effect=RuntimeError('probe failed')):
            self.assertEqual(random_background_start('background.mp4', 30), 0)

    def test_each_render_chooses_a_new_offset_and_original_video_never_seeks(self):
        with tempfile.TemporaryDirectory() as directory:
            bg=Path(directory)/'bg.mp4';bg.touch()
            commands=[]
            with patch('video_renderer.get_file_duration', side_effect=lambda path: 100 if Path(path)==bg else 30), patch('video_renderer.check_has_video', return_value=True), patch('video_renderer.random.uniform', side_effect=[12,45]), patch('video_renderer.run_ffmpeg_with_logging', side_effect=lambda cmd, **_: commands.append(cmd)):
                for _ in range(2):
                    render_karaoke_video('audio.wav', None, str(Path(directory)/'out.mp4'), background_image_path=str(bg))
                render_karaoke_video('audio.wav', None, str(Path(directory)/'original.mp4'), original_video_path=str(bg), background_mode='original_video')
            self.assertEqual(commands[0][commands[0].index('-ss')+1], '12.000')
            self.assertEqual(commands[1][commands[1].index('-ss')+1], '45.000')
            self.assertLess(commands[0].index('-ss'), commands[0].index('-i'))
            self.assertNotIn('-ss', commands[2])
            for command in commands:
                self.assertEqual(command[command.index('-t')+1], '30.000')
                self.assertIn('audio.wav', command)

    def test_real_ffmpeg_seeks_only_background_preserving_audio_and_subtitle_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bg=root/'bg.mp4';audio=root/'audio.wav';captions=root/'captions.srt';output=root/'out.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=160x90:r=10:d=2','-f','lavfi','-i','color=blue:s=160x90:r=10:d=2','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-c:v','libx264',str(bg)],check=True)
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1',str(audio)],check=True)
            captions.write_text('1\n00:00:00,000 --> 00:00:00,800\nVisible at the start\n')
            with patch('video_renderer.random.uniform', return_value=2.5):
                render_karaoke_video(str(audio),str(captions),str(output),background_image_path=str(bg))
            pixel=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-ss','0.1','-frames:v','1','-vf','crop=2:2:0:0','-f','rawvideo','-pix_fmt','rgb24','-'])
            self.assertGreater(pixel[2],pixel[0]+100, 'Background must start in the blue excerpt')
            frame=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-ss','0.1','-frames:v','1','-f','rawvideo','-pix_fmt','gray','-'])
            self.assertGreater(max(frame),200, 'Subtitle clock must still start at zero')
            pcm=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-f','s16le','-ac','1','-ar','16000','-'])
            self.assertGreater(len(pcm),30000, 'Audio must retain the full song duration')
