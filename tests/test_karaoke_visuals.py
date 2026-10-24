from pathlib import Path
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from karaoke_visuals import DEFAULTS, install_routes, load_visuals, normalize_visuals
from karaoke_generator import generate_ass_karaoke, insert_instrumental_breaks
from media_covers import create_video_cover, filter_path
import numpy as np


class VisualSettingsTests(unittest.TestCase):
    def test_only_administrators_can_read_and_change_shared_style(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'karaoke_animation.json'
            user = dict(role='user')
            def admin(current):
                if current['role'] != 'admin':
                    raise HTTPException(403, 'admin only')
            app = FastAPI()
            install_routes(app, lambda: user, admin, path)
            client = TestClient(app)
            self.assertEqual(client.get('/api/admin/karaoke-visuals').status_code, 403)
            self.assertEqual(client.post('/api/admin/karaoke-visuals', json=DEFAULTS).status_code, 403)
            self.assertFalse(path.exists())
            user['role'] = 'admin'
            self.assertEqual(client.get('/api/admin/karaoke-visuals').json(), DEFAULTS)
            custom = dict(DEFAULTS, countdown_seconds=5, min_instrumental_gap=4.5, instrumental_color='#facc15')
            response = client.post('/api/admin/karaoke-visuals', json=custom)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(load_visuals(path), custom)
            bad = client.post('/api/admin/karaoke-visuals', json=dict(custom, countdown_seconds=100))
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(load_visuals(path), custom)

    def test_bad_values_cannot_inject_ass_or_expand_time_without_bounds(self):
        for value in (dict(instrumental_color=r'\t(0,0)'), dict(animation_style='unknown'),
                      dict(min_instrumental_gap=float('nan')), dict(countdown_seconds=True),
                      dict(highlight_glow='false'), dict(unexpected=True)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_visuals(value)

    def test_new_options_survive_save_and_old_configuration_keeps_its_style(self):
        custom = dict(DEFAULTS, animation_style='pulse', instrumental_style='dots',
                      instrumental_text='Prepare-se', instrumental_size=125, countdown_seconds=0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'visuals.json'
            path.write_text(json.dumps(custom))
            self.assertEqual(load_visuals(path), custom)
            old = dict(animation_style='classic', highlight_glow=False, instrumental_style='classic',
                       instrumental_color='#facc15', min_instrumental_gap=4, countdown_seconds=5)
            path.write_text(json.dumps(old))
            loaded = load_visuals(path)
            self.assertEqual({key: loaded[key] for key in old}, old)
            self.assertEqual(loaded['instrumental_text'], 'Instrumental')
        for value in (dict(instrumental_text='{\\pos(0,0)}'), dict(instrumental_text='A\nB'),
                      dict(instrumental_text=' '), dict(instrumental_text='A'*41),
                      dict(instrumental_size=True), dict(instrumental_size=151), dict(countdown_seconds=-1)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_visuals(value)


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class RenderedVisualTests(unittest.TestCase):
    def frame(self, path, time):
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'color=black:s=640x360:r=25:d=5', '-vf', "ass='"+filter_path(path)+"'",
            '-ss', str(time), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
        return np.frombuffer(raw, dtype=np.uint8).reshape(360,640,3)

    def test_bonnie_phrase_transition_is_readable_on_the_first_frame(self):
        # The supplied result flashes at verse changes (e.g. 00:21.5).
        # Reproduce the same two-line to active-verse transition without ASR.
        source = [dict(start=0,end=2,text='You make this world a little wild',words=[]),
                  dict(start=2,end=5,text='And we shout through crowded streets',words=[])]
        original = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bonnie.ass'
            generate_ass_karaoke(source, str(path), font_size=52, text_position='middle',
                show_next_line_preview=True, show_instrumental=False, visual_settings=DEFAULTS)
            first, later = self.frame(path, 2), self.frame(path, 2.12)
            self.assertGreater(np.count_nonzero(first.max(axis=2) > 150), 500)
            self.assertTrue(np.array_equal(first, later), 'The verse must not fade from invisible.')
        self.assertEqual(source, original)

    def test_new_effects_are_distinct_and_never_light_up_before_singing(self):
        source = [dict(start=0,end=4,text='Bonnie and Clyde',synced_line=True,
            animation_words=[dict(word='Bonnie',start=.8,end=2),dict(word=' and Clyde',start=2.5,end=3.8)])]
        original = copy.deepcopy(source)
        renders = {}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'effect.ass'
            for style in ('classic','smooth','pulse','outline','instant'):
                generate_ass_karaoke(source,str(path),font_size=60,show_instrumental=False,
                    text_color_hex='#FFFF00',visual_settings=dict(animation_style=style))
                before, active = self.frame(path,.72), self.frame(path,.88)
                def lit(pixels):
                    return np.count_nonzero((pixels[:,:,0]>120)&(pixels[:,:,1]>120)&(pixels[:,:,2]<90))
                self.assertEqual(lit(before),0,style)
                self.assertGreater(lit(active),20,style)
                renders[style] = active
                self.assertIn('0:00:00.00,0:00:04.00',path.read_text())
        self.assertEqual(len({pixels.tobytes() for pixels in renders.values()}),5)
        self.assertEqual(source,original)

    def test_every_instrumental_style_keeps_preview_separate_and_resumes_at_same_time(self):
        source = [dict(start=4,end=5,text='Next sung line',words=[],synced_line=True)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'rest.ass'
            for style in ('classic','progress','dots','countdown'):
                for position in ('top','middle','bottom'):
                    settings = dict(instrumental_style=style,instrumental_text='Prepare-se',instrumental_size=150)
                    rests = insert_instrumental_breaks(source,5,settings)
                    self.assertEqual(rests[0]['start'],0)
                    self.assertEqual([r for r in rests if r.get('instrumental')][-1]['end'],4)
                    generate_ass_karaoke(source,str(path),font_size=60,text_position=position,
                        show_next_line_preview=True,visual_settings=settings)
                    content = path.read_text()
                    self.assertIn('0:00:04.00,0:00:05.00',content)
                    bounds=[]
                    for name in ('Default','NextLine'):
                        path.write_text('\n'.join(line for line in content.splitlines()
                            if not line.startswith('Dialogue:') or f',{name},' in line))
                        y,x=np.where(self.frame(path,2.5).max(axis=2)>40)
                        self.assertGreater(len(x),100)
                        self.assertGreater(x.min(),10); self.assertLess(x.max(),630)
                        self.assertGreater(y.min(),10); self.assertLess(y.max(),350)
                        bounds.append((y.min(),y.max()))
                    self.assertGreater(bounds[1][0]-bounds[0][1],5,(style,position,bounds))

    def test_countdown_can_be_disabled_without_hiding_preview_or_shortening_rest(self):
        source = [dict(start=4,end=5,text='Next verse',words=[],synced_line=True)]
        settings = dict(countdown_seconds=0,instrumental_text='Solo')
        rests = [r for r in insert_instrumental_breaks(source,5,settings) if r.get('instrumental')]
        self.assertEqual([(r['start'],r['end'],r['text']) for r in rests],[(0,4,'Solo')])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'solo.ass'
            generate_ass_karaoke(source,str(path),show_next_line_preview=True,visual_settings=settings)
            self.assertIn(',NextLine,',path.read_text())

    @unittest.skipUnless(Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc').is_file(), 'Noto CJK required')
    def test_yuqi_title_uses_cjk_glyphs_instead_of_missing_character_boxes(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'yuqi.png'
            commands=[]
            def run(command):
                commands.append(command)
                subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            create_video_cover(None,'宋雨琦 (YUQI) - Bonnie & Clyde',output,run)
            self.assertGreater(output.stat().st_size,1000)
            self.assertIn('NotoSansCJK-Bold.ttc',commands[0][commands[0].index('-vf')+1])
