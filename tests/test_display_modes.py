"""Verify real libass layout and each advertised animation mode."""
import copy
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from karaoke_generator import generate_ass_karaoke
from lyrics_sync import anchor_synced_animation
from video_renderer import render_karaoke_video, run_ffmpeg_with_logging


def frame(path, time=0.5):
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
        'color=black:s=1280x720:r=25:d=5', '-vf', 'ass=' + str(path), '-ss', str(time),
        '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
    return np.frombuffer(raw, dtype=np.uint8).reshape(720, 1280, 3)


class DisplayModeTests(unittest.TestCase):
    def test_whisper_current_and_preview_have_separate_regions_in_every_position(self):
        texts = ("And if the words float up to the surface, I'll keep them down",
                 "This is the first time I know I don't want the crown")
        segments = [dict(start=0, end=5, text=texts[0], words=[]),
                    dict(start=5, end=10, text=texts[1], words=[])]
        for position in ('top', 'middle', 'bottom'):
            with self.subTest(position=position), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'captions.ass'
                generate_ass_karaoke(copy.deepcopy(segments), str(path), font_size=120,
                    show_instrumental=False, text_position=position, show_next_line_preview=True)
                output = path.read_text()
                bounds = []
                for style in ('Default', 'NextLine'):
                    path.write_text('\n'.join(line for line in output.splitlines()
                        if not line.startswith('Dialogue:') or f',{style},' in line))
                    y, x = np.where(frame(path).max(axis=2) > 35)
                    self.assertGreater(x.min(), 25)
                    self.assertLess(x.max(), 1255)
                    self.assertGreater(y.min(), 25)
                    self.assertLess(y.max(), 695)
                    bounds.append((y.min(), y.max()))
                self.assertGreater(bounds[1][0] - bounds[0][1], 10)

    def test_word_mode_changes_whole_word_at_start_and_syllable_mode_sweeps(self):
        segments = anchor_synced_animation([dict(start=0, end=3, text='Longword next')],
            [dict(words=[dict(word='irrelevant', start=.2, end=1.2),
                         dict(word='incorrect', start=1.8, end=2.5)])])
        for mode in ('word', 'syllable'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'mode.ass'
                generate_ass_karaoke(segments, str(path), subtitle_mode=mode, show_instrumental=False)
                def white(time):
                    return np.count_nonzero(frame(path, time).min(axis=2) > 220)
                before, early, later, pause = [white(time) for time in (.1, .4, 1.1, 1.6)]
                self.assertEqual(before, 0)
                self.assertGreater(early, 100)
                self.assertEqual(later, pause)
                if mode == 'word':
                    self.assertEqual(early, later)
                else:
                    self.assertGreater(later, early)

    def test_static_modes_preserve_source_and_do_not_change_with_local_word_times(self):
        text = '  Original source,  intact!  '
        segments = anchor_synced_animation([dict(start=0, end=3, text=text)],
            [dict(words=[dict(word='wrong', start=.2, end=1.2)])])
        for mode in ('line', 'phrase'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'static.ass'
                generate_ass_karaoke(segments, str(path), subtitle_mode=mode, show_instrumental=False)
                event = next(line for line in path.read_text().splitlines() if line.startswith('Dialogue:'))
                self.assertEqual(re.sub(r'\{[^}]*\}', '', event.split(',', 9)[-1]).replace(r'\N', ''), text)
                self.assertNotIn(r'\kt', event)
                self.assertTrue(np.array_equal(frame(path, .1), frame(path, 1.6)))

    def test_persistent_first_verse_is_not_duplicated_by_countdown_or_preview(self):
        for position in ('top', 'middle', 'bottom'):
            with self.subTest(position=position), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'intro.ass'
                generate_ass_karaoke([dict(start=5, end=8, text='Entire first verse', words=[], synced_line=True)],
                    str(path), font_size=120, words_per_line=1, max_chars_line=3,
                    text_position=position, keep_first_line_visible=True, show_next_line_preview=True)
                events = [line for line in path.read_text().splitlines() if line.startswith('Dialogue:')]
                first = [line for line in events if 'Entire' in line]
                self.assertEqual(len(first), 2)  # one intro and the canonical singing interval
                self.assertIn('0:00:00.00,0:00:05.00', first[0])
                # Render countdown and intro independently to verify nonoverlapping glyphs.
                output = path.read_text(); bounds = []
                for label in ('Entire', 'Instrumental'):
                    path.write_text('\n'.join(line for line in output.splitlines()
                        if not line.startswith('Dialogue:') or label in line))
                    y, _ = np.where(frame(path, 3.5).max(axis=2) > 35)
                    bounds.append((y.min(), y.max()))
                self.assertGreater(bounds[0][0] - bounds[1][1], 10)

    def test_solid_color_does_not_fall_back_to_an_uploaded_image(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); audio = root / 'song.wav'; image = root / 'red.png'; output = root / 'out.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=1', str(audio)], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=160x90',
                            '-frames:v', '1', '-threads', '1', str(image)], check=True)
            render_karaoke_video(str(audio), '', str(output), background_image_path=str(image), background_mode='color')
            pixel = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(output), '-frames:v', '1',
                '-vf', 'crop=2:2:0:0', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'])
            self.assertLess(max(pixel), 10)

    def test_invalid_duration_is_rejected_before_starting_ffmpeg(self):
        for duration in (0, float('nan'), float('inf')):
            with self.subTest(duration=duration), patch('video_renderer.get_file_duration', return_value=duration), \
                    patch('video_renderer.subprocess.Popen') as launch, self.assertRaises(ValueError):
                render_karaoke_video('input.wav', '', 'output.mp4')
            launch.assert_not_called()

    def test_failed_progress_observer_cannot_leave_a_process_or_pipe_open(self):
        original = subprocess.Popen
        started = []
        def launch(*args, **kwargs):
            process = original(*args, **kwargs)
            started.append(process)
            return process
        def failed_observer(_):
            raise RuntimeError('observer failed')
        with patch('video_renderer.subprocess.Popen', side_effect=launch), self.assertRaisesRegex(RuntimeError, 'observer failed'):
            run_ffmpeg_with_logging([sys.executable, '-c', 'import time; time.sleep(30)'], progress_callback=failed_observer)
        self.assertIsNotNone(started[0].poll())
        self.assertTrue(started[0].stdout.closed)


if __name__ == '__main__':
    unittest.main()
