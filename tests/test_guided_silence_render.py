"""Strict lyric-guide display must stop with the measured singing, including previews."""
import copy
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from karaoke_generator import generate_ass_karaoke
from media_covers import filter_path


FFMPEG = os.getenv('FFMPEG_BINARY') or shutil.which('ffmpeg')


def verse(start, end, words, **extra):
    return dict(start=start, end=end, text=' '.join(word['word'].strip() for word in words),
                words=words, **extra)


def seconds(value):
    hours, minutes, rest = value.split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def events(path):
    result = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.startswith('Dialogue: '):
            continue
        fields = line.split(',', 9)
        text = re.sub(r'\{[^}]*\}', '', fields[-1])
        result.append(dict(start=seconds(fields[1]), end=seconds(fields[2]),
                           style=fields[3], text=text, raw=fields[-1]))
    return result


class StrictGuidedSilenceTests(unittest.TestCase):
    def render(self, source, folder, **options):
        path = Path(folder) / 'strict.ass'
        generate_ass_karaoke(source, str(path), strict_guide=True,
                             show_instrumental=options.pop('show_instrumental', False), **options)
        return path, events(path)

    def test_words_bound_intro_outro_and_internal_rests_for_both_preview_settings(self):
        source = [verse(0, 7, [dict(word='Canto', start=2, end=2.8),
                               dict(word=' amor', start=5, end=5.8)]),
                  verse(8, 8.8, [dict(word='Agora', start=8, end=8.8)])]
        before = copy.deepcopy(source)
        for instrumental in (False, True):
            for preview in (False, True):
                with self.subTest(instrumental=instrumental, preview=preview), tempfile.TemporaryDirectory() as folder:
                    _, rendered = self.render(source, folder, media_duration=11,
                        show_instrumental=instrumental, show_next_line_preview=preview,
                        keep_first_line_visible=True, voice_regions=[(2.1, 2.7), (5.1, 5.7), (8.1, 8.7)])
                    lyrics = [event for event in rendered if 'Instrumental' not in event['text']]
                    self.assertTrue(lyrics)
                    for event in lyrics:
                        self.assertTrue(any(left <= event['start'] < event['end'] <= right
                            for left, right in [(2.1, 2.7), (5.1, 5.7), (8.1, 8.7)]), event)
                    self.assertEqual(any(event['style'] == 'NextLine' for event in lyrics), preview)
                    self.assertEqual(any('Instrumental' in event['text'] for event in rendered), instrumental)
        self.assertEqual(source, before)

    def test_unknown_voice_falls_back_to_words_but_known_empty_voice_never_displays_lyrics(self):
        source = [verse(0, 10, [dict(word='Canto', start=3, end=4)])]
        with tempfile.TemporaryDirectory() as folder:
            _, fallback = self.render(source, folder, voice_regions=None)
            self.assertEqual([(event['start'], event['end']) for event in fallback], [(3, 4)])
            _, silent = self.render(source, folder, voice_regions=[], media_duration=10,
                                    show_next_line_preview=True, keep_first_line_visible=True)
            self.assertEqual(silent, [])
            _, notices = self.render(source, folder, voice_regions=[], media_duration=10,
                                    show_instrumental=True, show_next_line_preview=True)
            self.assertTrue(notices)
            self.assertTrue(all('Instrumental' in event['text'] for event in notices))

    def test_small_energy_holes_do_not_flicker_or_anticipate_a_later_word(self):
        source = [verse(0, 4, [dict(word='Canto', start=1, end=2),
                              dict(word=' amor', start=3, end=3.5)])]
        vocals = [(1.005, 1.2), (1.22, 1.4), (1.42, 1.995), (2.4, 2.42), (3.1, 3.2)]
        with tempfile.TemporaryDirectory() as folder:
            _, rendered = self.render(source, folder, voice_regions=vocals)
            self.assertEqual([(event['start'], event['end']) for event in rendered], [(1.01, 1.99), (3.1, 3.2)])
            self.assertTrue(all(event['start'] >= 1.005 and event['end'] <= 3.2 for event in rendered))

    def test_parent_span_clamps_stale_word_and_character_clocks_without_mutating_them(self):
        source = [verse(2, 3, [dict(word='Canto', start=0, end=5,
            alignment_chars=[dict(text='C', start=0, end=5)])], synced_line=True)]
        before = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as folder:
            _, rendered = self.render(source, folder, voice_regions=[(0, 10)])
            self.assertEqual([(event['start'], event['end']) for event in rendered], [(2, 3)])
        self.assertEqual(source, before)

    def test_strict_guide_does_not_extend_a_verse_to_the_following_one(self):
        source = [verse(1, 2, [dict(word='Canto', start=1, end=2, lyric_line_break=True)]),
                  verse(5, 6, [dict(word='Agora', start=5, end=6, lyric_line_break=True)])]
        with tempfile.TemporaryDirectory() as folder:
            _, rendered = self.render(source, folder)
            self.assertEqual([(event['start'], event['end']) for event in rendered], [(1, 2), (5, 6)])
            legacy = Path(folder) / 'legacy.ass'
            generate_ass_karaoke(source, str(legacy), show_instrumental=False)
            self.assertEqual(events(legacy)[0]['end'], 5)

    @unittest.skipUnless(FFMPEG, 'FFmpeg with libass is required for pixel verification')
    def test_real_ffmpeg_frames_hide_all_lyrics_and_previews_in_intro_internal_silence_and_tail(self):
        import numpy as np
        source = [verse(0, 7, [dict(word='CANTO', start=2, end=2.8),
                              dict(word=' AMOR', start=5, end=5.8)]),
                  verse(8, 8.8, [dict(word='AGORA', start=8, end=8.8)])]
        clocks = [.5, 2.04, 2.3, 3.5, 5.3, 6.5, 8.3, 9.5]
        frame_indices = [round(clock * 25) for clock in clocks]
        selection = '+'.join(f'eq(n,{frame})' for frame in frame_indices)
        for instrumental in (False, True):
            for preview in (False, True):
                with self.subTest(instrumental=instrumental, preview=preview), tempfile.TemporaryDirectory() as folder:
                    path, _ = self.render(source, folder, media_duration=11, font_size=60,
                        subtitle_mode='phrase', text_color_hex='#FF0000',
                        show_instrumental=instrumental, show_next_line_preview=preview,
                        keep_first_line_visible=True, voice_regions=[(2.1, 2.7), (5.1, 5.7), (8.1, 8.7)],
                        visual_settings=dict(instrumental_color='#00FF00', countdown_seconds=1))
                    raw = subprocess.check_output([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i',
                        'color=black:s=640x360:r=25:d=11', '-vf',
                        "ass='" + filter_path(path) + "',select='" + selection + "'",
                        '-fps_mode', 'vfr', '-frames:v', str(len(clocks)), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
                    frames = np.frombuffer(raw, dtype=np.uint8).reshape(len(clocks), -1, 3).astype(np.int16)
                    for clock, pixels in zip(clocks, frames):
                        red = np.count_nonzero((pixels[:, 0] > 35) &
                            (pixels[:, 0] > pixels[:, 1] * 1.5) & (pixels[:, 0] > pixels[:, 2] * 1.5))
                        expected = clock in (2.3, 5.3, 8.3)
                        self.assertEqual(red > 10, expected, f'Lyric leak/absence at {clock}s: {red} red pixels')
                        if clock in (.5, 3.5, 6.5, 9.5):
                            green = np.count_nonzero((pixels[:, 1] > 80) &
                                (pixels[:, 1] > pixels[:, 0] * 1.5) & (pixels[:, 1] > pixels[:, 2] * 1.5))
                            self.assertEqual(green > 10, instrumental, f'Instrumental visibility at {clock}s')


if __name__ == '__main__':
    unittest.main()
