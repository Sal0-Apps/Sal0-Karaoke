import importlib.util
import unittest
from pathlib import Path

path = Path(__file__).parents[1] / '.github/scripts/release_clients.py'
spec = importlib.util.spec_from_file_location('release_clients', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ClientReleaseTests(unittest.TestCase):
    def test_server_only_release_does_not_rebuild_clients(self):
        self.assertEqual(module.client_changes(['VERSION','app/main.py','app/lyrics_sync.py',
            'app/karaoke_generator.py','.github/workflows/docker-publish.yml',
            'android/README.md']), (False, False))

    def test_native_android_change_builds_only_android(self):
        self.assertEqual(module.client_changes(['android/app/src/main/MainActivity.kt']), (True, False))
        self.assertEqual(module.client_changes(['android/app/build.gradle.kts']), (True, False))

    def test_windows_authorizer_change_builds_only_windows(self):
        self.assertEqual(module.client_changes(['app/youtube_desktop_oauth.py']), (False, True))
