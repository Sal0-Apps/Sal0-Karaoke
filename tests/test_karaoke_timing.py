import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from karaoke_generator import generate_ass_karaoke, insert_instrumental_breaks
from lyric_alignment import AudioEvidence, clean_segments
from media_covers import filter_path
from karaoke_visuals import DEFAULTS


def verse(start, end, words):
    return dict(start=start, end=end, text=' '.join(w['word'].strip() for w in words), words=words,
                synced_line=True, animation_words=words)


class TimingTests(unittest.TestCase):
    def test_instrumental_uses_word_clocks_inside_a_guide_verse_and_covers_outro(self):
        source = [verse(0, 12, [dict(word='Canto', start=3, end=4), dict(word='outra vez', start=8, end=9)])]
        before = copy.deepcopy(source)
        result = insert_instrumental_breaks(source, 12)
        rests = [s for s in result if s.get('instrumental')]
        self.assertTrue(rests)
        for left, right in [(0, 3), (4, 8), (9, 12)]:
            current = [s for s in rests if s['rest_start'] == left]
            self.assertEqual(current[0]['start'], left)
            self.assertEqual(current[-1]['end'], right)
            self.assertTrue(all(a['end'] == b['start'] for a, b in zip(current, current[1:])))
        self.assertEqual([s['text'] for s in rests if s['rest_start'] == 9], ['Instrumental'])
        for word in source[0]['words']:
            self.assertFalse(any(min(s['end'], word['end']) > max(s['start'], word['start']) for s in rests))
        self.assertEqual(source, before)

    def test_short_rest_adapts_countdown_and_breaths_do_not_create_cues(self):
        source = [verse(0, 10, [dict(word='A', start=.2, end=1), dict(word='B', start=3.4, end=4),
                                     dict(word='C', start=4.6, end=5)])]
        rests = [s for s in insert_instrumental_breaks(source) if s.get('instrumental')]
        self.assertEqual([s['text'] for s in rests], ['Instrumental', 'Instrumental (2)', 'Instrumental (1)'])
        self.assertTrue(all(1 <= s['start'] < s['end'] <= 3.4 for s in rests))

    def test_detected_singing_without_a_recognized_word_blocks_false_instrumental(self):
        source = [verse(0, 10, [dict(word='A', start=0, end=1), dict(word='B', start=8, end=9)])]
        result = insert_instrumental_breaks(source, 10, voice_regions=[(1, 8)])
        self.assertFalse(any(s.get('instrumental') for s in result))

    def test_overlapping_voice_and_lyric_named_instrumental_never_become_rests(self):
        a = verse(0, 5, [dict(word='Instrumental', start=0, end=5)])
        b = verse(2, 6, [dict(word='cantado', start=2, end=6)])
        self.assertFalse(any(s.get('instrumental') for s in insert_instrumental_breaks([b, a], 6)))

    def test_admin_controls_gap_and_countdown(self):
        source = [verse(7, 8, [dict(word='Canto', start=7, end=8)])]
        result = insert_instrumental_breaks(source, visual_settings=dict(countdown_seconds=5, min_instrumental_gap=4))
        self.assertEqual([s['text'] for s in result[:3]], ['Instrumental', 'Instrumental (5)', 'Instrumental (4)'])

    def test_large_early_clock_is_trimmed_to_supported_voice_without_cutting_audio(self):
        audio = np.zeros(16000 * 6, dtype=np.float32)
        audio[:48000] = .0005 * np.sin(np.arange(48000) * .1)  # Demucs leakage.
        audio[48000:64000] = .1 * np.sin(np.arange(16000) * .1)
        source = [verse(0, 4, [dict(word='Canto', start=0, end=4)])]
        result, _ = clean_segments(source, AudioEvidence(audio), voice_regions=[(3, 4)])
        self.assertEqual(result[0]['words'][0]['start'], 3)
        self.assertEqual(len(audio), 16000 * 6)
        self.assertEqual(source[0]['words'][0]['start'], 0)

    def test_no_artificial_lead_in_before_sound(self):
        audio = np.zeros(16000 * 3, dtype=np.float32)
        audio[16000:32000] = .1
        source = [verse(.4, 2, [dict(word='Canto', start=.4, end=2)])]
        result, _ = clean_segments(source, AudioEvidence(audio))
        self.assertEqual(result[0]['words'][0]['start'], 1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
    def test_rendered_characters_never_light_up_before_the_parent_word(self):
        words = [dict(word='MMMM', start=2, end=2.8, alignment_chars=[
            dict(text='M', start=.3+i*.2, end=2.2+i*.2) for i in range(4)])]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'timing.ass'
            generate_ass_karaoke([verse(0, 3, words)], str(target), font_size=60,
                                 text_color_hex='#FFFF00', show_instrumental=False, visual_settings=DEFAULTS)
            for clock, expected in [(1.5, False), (2.5, True)]:
                data = subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=black:s=640x360:r=25:d=3', '-vf', "ass='"+filter_path(target)+"'",
                    '-ss', str(clock), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
                pixels = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3)
                lit = np.count_nonzero((pixels[:, 0] > 170) & (pixels[:, 1] > 170) & (pixels[:, 2] < 100))
                self.assertEqual(lit > 10, expected, f'Premature/absent highlight at {clock}: {lit}')

    def test_progress_graphics_and_classic_style_use_the_same_clocks(self):
        source = [verse(4, 6, [dict(word='Canto', start=4, end=6)])]
        with tempfile.TemporaryDirectory() as folder:
            modern, classic = [Path(folder) / name for name in ('modern.ass', 'classic.ass')]
            generate_ass_karaoke(source, str(modern), media_duration=9, visual_settings=DEFAULTS)
            generate_ass_karaoke(source, str(classic), media_duration=9,
                                 visual_settings=dict(animation_style='classic', instrumental_style='classic',
                                                      instrumental_color='#FF0000'))
            self.assertIn(r'\p1', modern.read_text())
            self.assertNotIn(r'\p1', classic.read_text())
            self.assertIn(r'\1c&H000000FF\2c&H000000FF}Instrumental', classic.read_text())
            self.assertIn('0:00:04.00,0:00:06.00', modern.read_text())
            self.assertIn('0:00:04.00,0:00:06.00', classic.read_text())


if __name__ == '__main__':
    unittest.main()
