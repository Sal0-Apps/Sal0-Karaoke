"""Readable verses stay stable across word gaps; 12.7 instrumental notices remain optional."""
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


def verse(start, end, words):
    animation = [dict(word) for word in words]
    for index, word in enumerate(animation):
        word['word'] = (' ' if index else '') + word['word'].strip()
    return dict(start=start, end=end, text=' '.join(word['word'].strip() for word in words),
                words=words, animation_words=animation, synced_line=True)


def seconds(value):
    hours, minutes, rest = value.split(':')
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def events(path):
    result = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('Dialogue: '):
            fields = line.split(',', 9)
            if r'\p1' in fields[-1]:
                continue  # Vector instrumental meters are not lyric text events.
            result.append(dict(start=seconds(fields[1]), end=seconds(fields[2]), style=fields[3],
                text=' '.join(re.sub(r'\{[^}]*\}', '', fields[-1]).replace(r'\N', ' ').split()), raw=fields[-1]))
    return result


class StableVerseDisplayTests(unittest.TestCase):
    def render(self, source, folder, **options):
        path = Path(folder) / 'stable.ass'
        generate_ass_karaoke(source, str(path),
            show_instrumental=options.pop('show_instrumental', False), **options)
        return path, events(path)

    def nine_words(self):
        return verse(3, 9, [dict(word=text, start=3 + index * .7, end=3.2 + index * .7)
            for index, text in enumerate('UM DOIS TRES QUATRO CINCO SEIS SETE OITO NOVE'.split())])

    def test_nine_word_verse_is_one_event_despite_natural_gaps_and_short_vocal_regions(self):
        source = [self.nine_words()]
        before = copy.deepcopy(source)
        pulses = [(word['start'] + .05, word['start'] + .07) for word in source[0]['words']]
        for instrumental in (False, True):
            for vocals in (None, [], pulses):
                with self.subTest(instrumental=instrumental, vocals=vocals), tempfile.TemporaryDirectory() as folder:
                    _, rendered = self.render(source, folder, media_duration=10,
                        show_instrumental=instrumental, voice_regions=vocals,
                        visual_settings=dict(min_instrumental_gap=4))
                    lyrics = [event for event in rendered if 'Instrumental' not in event['text']]
                    self.assertEqual([(event['start'], event['end']) for event in lyrics], [(3, 9)])
                    self.assertEqual(lyrics[0]['text'], source[0]['text'])
        self.assertEqual(source, before)

    def test_only_long_instrumental_rests_split_the_verse_when_notices_are_enabled(self):
        source = [verse(5, 13, [dict(word='ANTES', start=5, end=6), dict(word='DEPOIS', start=12, end=13)])]
        with tempfile.TemporaryDirectory() as folder:
            _, uninterrupted = self.render(source, folder, media_duration=18,
                show_instrumental=False, visual_settings=dict(min_instrumental_gap=4))
            self.assertEqual([(event['start'], event['end']) for event in uninterrupted], [(5, 13)])
            _, with_rests = self.render(source, folder, media_duration=18,
                show_instrumental=True, visual_settings=dict(min_instrumental_gap=4))
            lyrics = [event for event in with_rests if 'Instrumental' not in event['text']]
            self.assertEqual([(event['start'], event['end']) for event in lyrics], [(5, 6), (12, 13)])
            for start, end in [(0, 5), (6, 12), (13, 18)]:
                rests = [event for event in with_rests if 'Instrumental' in event['text']
                    and start <= event['start'] < event['end'] <= end]
                self.assertTrue(rests)
                self.assertFalse(any(max(start, event['start']) < min(end, event['end']) for event in lyrics))

    def test_preview_and_persistent_intro_keep_their_12_7_opt_in_behavior(self):
        source = [verse(5, 6, [dict(word='PRIMEIRO', start=5, end=6)]),
                  verse(12, 13, [dict(word='SEGUINTE', start=12, end=13)])]
        with tempfile.TemporaryDirectory() as folder:
            _, plain = self.render(source, folder, show_instrumental=True,
                media_duration=18, visual_settings=dict(min_instrumental_gap=4))
            self.assertFalse(any(event['style'] == 'NextLine' for event in plain))
            self.assertFalse(any(event['start'] < 5 and event['text'] == 'PRIMEIRO' for event in plain))
            _, preview = self.render(source, folder, show_instrumental=True,
                show_next_line_preview=True, media_duration=18, visual_settings=dict(min_instrumental_gap=4))
            self.assertTrue(any(event['style'] == 'NextLine' for event in preview))
            _, persistent = self.render(source, folder, show_instrumental=True,
                keep_first_line_visible=True, media_duration=18, visual_settings=dict(min_instrumental_gap=4))
            self.assertTrue(any(event['start'] == 0 and event['end'] == 5
                and event['text'] == 'PRIMEIRO' for event in persistent))

    def frames(self, path, clocks, duration):
        import numpy as np
        selection = '+'.join(f'eq(n,{round(clock * 25)})' for clock in clocks)
        raw = subprocess.check_output([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i',
            f'color=black:s=640x360:r=25:d={duration}', '-vf',
            "ass='" + filter_path(path) + "',select='" + selection + "'",
            '-fps_mode', 'vfr', '-frames:v', str(len(clocks)), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        return np.frombuffer(raw, dtype=np.uint8).reshape(len(clocks), -1, 3).astype(np.int16)

    def lyric_pixels(self, pixels):
        import numpy as np
        red = (pixels[:, 0] > 60) & (pixels[:, 0] > pixels[:, 1] * 1.4) & (pixels[:, 0] > pixels[:, 2] * 1.4)
        white = (pixels.min(axis=1) > 120) & ((pixels.max(axis=1) - pixels.min(axis=1)) < 35)
        return np.count_nonzero(red | white)

    @unittest.skipUnless(FFMPEG, 'FFmpeg with libass is required for pixel verification')
    def test_real_frames_do_not_blink_between_nine_words_for_both_instrumental_settings(self):
        source = [self.nine_words()]
        clocks = [2, 3.12, 3.4, 4.12, 4.8, 6.2, 7.6, 8.65, 9.4]
        for instrumental in (False, True):
            for mode in ('phrase', 'syllable'):
                with self.subTest(instrumental=instrumental, mode=mode), tempfile.TemporaryDirectory() as folder:
                    path, _ = self.render(source, folder, media_duration=10, font_size=48,
                        subtitle_mode=mode, text_color_hex='#FF0000', show_instrumental=instrumental,
                        voice_regions=[(word['start'] + .05, word['start'] + .07) for word in source[0]['words']],
                        visual_settings=dict(min_instrumental_gap=4, instrumental_color='#00FF00'))
                    for clock, pixels in zip(clocks, self.frames(path, clocks, 10)):
                        self.assertEqual(self.lyric_pixels(pixels) > 10, 3 <= clock < 9,
                            f'Verse blink/early display at {clock}s')

    @unittest.skipUnless(FFMPEG, 'FFmpeg with libass is required for pixel verification')
    def test_real_frames_hide_only_enabled_long_instrumental_rests(self):
        source = [verse(5, 13, [dict(word='ANTES', start=5, end=6), dict(word='DEPOIS', start=12, end=13)])]
        clocks = [1, 5.5, 8, 12.5, 16]
        for instrumental in (False, True):
            with self.subTest(instrumental=instrumental), tempfile.TemporaryDirectory() as folder:
                path, _ = self.render(source, folder, media_duration=18, font_size=60,
                    subtitle_mode='phrase', text_color_hex='#FF0000', show_instrumental=instrumental,
                    visual_settings=dict(min_instrumental_gap=4, instrumental_color='#00FF00'))
                for clock, pixels in zip(clocks, self.frames(path, clocks, 18)):
                    expected = clock in (5.5, 12.5) or (clock == 8 and not instrumental)
                    self.assertEqual(self.lyric_pixels(pixels) > 10, expected,
                        f'Unexpected verse visibility at {clock}s')


if __name__ == '__main__':
    unittest.main()
