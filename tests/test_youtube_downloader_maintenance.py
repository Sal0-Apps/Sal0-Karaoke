import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "app" / "Dockerfile").read_text(encoding="utf-8")
REQUIREMENTS = (ROOT / "app" / "requirements.txt").read_text(encoding="utf-8")


class YouTubeDownloaderMaintenanceTests(unittest.TestCase):
    def test_backend_remains_valid_python(self):
        ast.parse(MAIN)

    def test_image_installs_current_youtube_requirements(self):
        self.assertIn("yt-dlp[default]", REQUIREMENTS)
        self.assertIn("deno_target", DOCKERFILE)
        self.assertIn('pip install --no-cache-dir --upgrade --pre "yt-dlp[default]"', DOCKERFILE)

    def test_downloads_use_retries_and_validate_the_output(self):
        self.assertIn('"fragment_retries": 10', MAIN)
        self.assertIn('"extractor_retries": 5', MAIN)
        self.assertIn('find_downloaded_file(cache_dir, "original_input")', MAIN)
        self.assertIn('find_downloaded_file(cache_dir, "bg_yt_raw")', MAIN)

    def test_admin_can_install_a_persistent_update(self):
        self.assertIn('YT_DLP_RUNTIME_DIR = "/data/output/yt_dlp_runtime"', MAIN)
        self.assertIn('@app.post("/api/youtube-tools/update")', MAIN)
        self.assertIn('require_admin(current_user)', MAIN)
        self.assertIn('"yt-dlp[default]"', MAIN)
        self.assertIn('id="btnUpdateYoutubeTools"', HTML)
        self.assertIn('fetchYoutubeToolsStatus()', HTML)


if __name__ == "__main__":
    unittest.main()
