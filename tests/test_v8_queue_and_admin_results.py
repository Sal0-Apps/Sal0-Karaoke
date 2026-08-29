import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
ANDROID_BUILD = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github" / "workflows" / "docker-publish.yml").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "app" / "Dockerfile").read_text(encoding="utf-8")


class VersionEightQueueTests(unittest.TestCase):
    def test_backend_and_interface_syntax_sources_are_present(self):
        ast.parse(MAIN)
        self.assertIn('id="processingQueueList"', HTML)
        self.assertIn("submitProcessBatch(formData, audioFiles)", HTML)

    def test_upload_inputs_accept_multiple_files(self):
        self.assertIn('id="easyAudioFile" accept=".mp3,.wav,.flac,.m4a,.mp4,.mkv,.avi" multiple', HTML)
        self.assertIn('id="audioFile" name="audio_file" accept=".mp3,.wav,.flac,.m4a,.mp4,.mkv,.avi" multiple', HTML)

    def test_queue_is_persistent_and_uses_isolated_job_directories(self):
        self.assertIn('PROCESSING_QUEUE_FILE = "/data/output/processing_queue.json"', MAIN)
        self.assertIn('PROCESSING_QUEUE_ROOT = "/data/output/queue_jobs"', MAIN)
        self.assertIn('cache_dir = os.path.join(PROCESSING_QUEUE_ROOT, job_id, "cache")', MAIN)
        self.assertIn('@app.get("/api/queue")', MAIN)
        self.assertIn('position = enqueue_processing_job(job)', MAIN)
        self.assertIn("ensure_processing_queue_capacity", MAIN)
        self.assertIn("remove_finished_queue_cache", MAIN)

    def test_admin_has_explicit_cross_profile_results(self):
        self.assertIn('@app.get("/api/admin/results")', MAIN)
        self.assertIn('@app.get("/api/admin/results/{owner_key}/{filename}")', MAIN)
        self.assertIn('id="adminResultsSection"', HTML)
        self.assertIn("fetchAdminResults()", HTML)

    def test_version_is_8_for_web_android_and_release_build(self):
        self.assertIn("Sal0 Karaokê v8.0.0", HTML)
        self.assertIn('.orElse("8.0.0")', ANDROID_BUILD)
        self.assertIn('.orElse("80000")', ANDROID_BUILD)
        self.assertIn("-PVERSION_CODE=80000", WORKFLOW)
        self.assertIn("sal0-karaoke:8.0.0", COMPOSE)
        self.assertIn('org.opencontainers.image.version="8.0.0"', DOCKERFILE)

    def test_generated_icon_is_committed_for_web_and_android(self):
        self.assertTrue((ROOT / "app" / "templates" / "app-icon-v8.png").is_file())
        self.assertTrue((ROOT / "android" / "app" / "src" / "main" / "res" / "drawable-nodpi" / "app_icon_v8.png").is_file())


if __name__ == "__main__":
    unittest.main()
