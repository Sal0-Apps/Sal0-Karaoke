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
        formats = ".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.mp4,.mkv,.avi,.mov,.webm,.m4v"
        self.assertIn(f'id="easyAudioFile" accept="{formats}" multiple', HTML)
        self.assertIn(f'id="audioFile" name="audio_file" accept="{formats}" multiple', HTML)

    def test_queue_is_persistent_and_uses_isolated_job_directories(self):
        self.assertIn('PROCESSING_QUEUE_FILE = "/data/output/processing_queue.json"', MAIN)
        self.assertIn('PROCESSING_QUEUE_ROOT = "/data/output/queue_jobs"', MAIN)
        self.assertIn('cache_dir = os.path.join(PROCESSING_QUEUE_ROOT, job_id, "cache")', MAIN)
        self.assertIn('@app.get("/api/queue")', MAIN)
        self.assertIn('position = enqueue_processing_job(job)', MAIN)
        self.assertIn("ensure_processing_queue_capacity", MAIN)
        self.assertIn("remove_finished_queue_cache", MAIN)

    def test_queue_contains_only_active_jobs_and_is_hidden_for_one_video(self):
        self.assertIn('ACTIVE_QUEUE_STATUSES = {"queued", "processing"}', MAIN)
        self.assertIn('processing_queue.remove(job)', MAIN)
        self.assertIn('job.get("status") in ACTIVE_QUEUE_STATUSES', MAIN)
        self.assertIn('id="queueCard" style="display: none;"', HTML)
        self.assertIn("activeJobs.length > 1 || (adminCanControl && processingQueuePaused)", HTML)
        self.assertIn("if (activeJobs.length <= 1 && !processingQueuePaused)", HTML)
        self.assertNotIn("queueResultUrl", HTML)

    def test_queue_accepts_owner_and_admin_but_blocks_other_profiles(self):
        tree = ast.parse(MAIN)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "ensure_processing_queue_access"
        )
        source = ast.get_source_segment(MAIN, function)
        self.assertIn("is_admin(current_user)", source)
        self.assertIn('active_job.get("owner_username") != current_user.get("username")', source)
        self.assertIn("status_code=409", source)
        self.assertNotIn("youtube_url", source)
        self.assertIn("ensure_processing_queue_access(", MAIN)
        self.assertIn("data.owned_by_current_user || currentUser?.role === 'admin'", HTML)
        self.assertIn('id="queueAddProcessCard"', HTML)
        self.assertIn('id="btnToggleQueueCreation"', HTML)
        self.assertIn("setCreatorMode(currentCreatorMode)", HTML)
        self.assertIn("switcher.style.display = creationUiLocked ? 'none' : 'grid';", HTML)
        self.assertIn("arquivos, links, Biblioteca e qualquer um dos três modos", HTML)

    def test_active_progress_stays_exclusively_in_create_tab(self):
        self.assertNotIn("display: flex !important", HTML)
        self.assertIn("setActiveProcessLayout(true)", HTML)
        self.assertIn("setActiveProcessLayout(false)", HTML)
        self.assertIn("createTabContent.classList.contains('has-active-process') ? 'flex' : 'block'", HTML)

    def test_finished_jobs_do_not_block_the_next_queue_item(self):
        self.assertIn("promote_queue_cache_in_background", MAIN)
        self.assertIn("daemon=True", MAIN)
        self.assertIn('if job_cache and os.path.isdir(job_cache) and not pipeline.get("subtitle_only")', MAIN)
        self.assertIn('raise RuntimeError("O processador não foi liberado pelo trabalho anterior.")', MAIN)

    def test_duplicate_admin_results_panel_is_not_rendered(self):
        self.assertIn('@app.get("/api/admin/results")', MAIN)
        self.assertIn('@app.get("/api/admin/results/{owner_key}/{filename}")', MAIN)
        self.assertNotIn('id="adminResultsSection"', HTML)
        self.assertNotIn("Resultados de todos os perfis", HTML)
        self.assertNotIn("fetchAdminResults()", HTML)

    def test_background_upload_button_uses_the_standard_primary_color(self):
        start = HTML.index('id="libBgUploadForm"')
        end = HTML.index('</form>', start)
        form = HTML[start:end]
        self.assertIn('class="btn-primary"', form)
        self.assertNotIn('#ec4899', form)

    def test_release_metadata_is_9_0_2(self):
        self.assertIn("Sal0 Karaokê v9.0.2", HTML)
        self.assertIn('.orElse("9.0.2")', ANDROID_BUILD)
        self.assertIn('.orElse("90002")', ANDROID_BUILD)
        self.assertIn("-PVERSION_CODE=90002", WORKFLOW)
        self.assertIn("sal0-karaoke:9.0.2", COMPOSE)
        self.assertIn('org.opencontainers.image.version="9.0.2"', DOCKERFILE)

    def test_generated_icon_is_committed_for_web_and_android(self):
        self.assertTrue((ROOT / "app" / "templates" / "app-icon-v8.png").is_file())
        self.assertTrue((ROOT / "android" / "app" / "src" / "main" / "res" / "drawable-nodpi" / "app_icon_v8.png").is_file())


if __name__ == "__main__":
    unittest.main()
