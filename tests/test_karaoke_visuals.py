from pathlib import Path
import sys
import tempfile
import unittest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parents[1] / 'app'))
from karaoke_visuals import DEFAULTS, install_routes, load_visuals, normalize_visuals


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
