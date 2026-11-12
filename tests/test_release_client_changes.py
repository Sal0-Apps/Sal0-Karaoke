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

    def test_retry_keeps_an_explicitly_versioned_android_release(self):
        build = 'val appVersionName = providers.gradleProperty("VERSION_NAME").orElse("12.7.9")'
        paths = ['tests/test_v8_queue_and_admin_results.py']
        self.assertEqual(module.client_changes(paths, release_version='12.7.9', android_build=build), (True, False))
        self.assertEqual(module.client_changes(paths, release_version='12.7.10', android_build=build), (False, False))

    def test_windows_authorizer_change_builds_only_windows(self):
        self.assertEqual(module.client_changes(['app/youtube_desktop_oauth.py']), (False, True))
