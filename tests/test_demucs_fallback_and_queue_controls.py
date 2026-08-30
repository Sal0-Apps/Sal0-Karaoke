import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

import audio_processor


MAIN = (APP / "main.py").read_text(encoding="utf-8")
HTML = (APP / "templates" / "index.html").read_text(encoding="utf-8")


class FakeProcess:
    def __init__(self, returncode, lines):
        self.returncode = returncode
        self.stdout = iter(lines)
        self.pid = 123

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode = -15


class DemucsFallbackAndQueueTests(unittest.TestCase):
    def test_demucs_retries_with_lower_memory_model_and_preserves_diagnostics(self):
        commands = []
        fake_manager = types.SimpleNamespace(
            cancel_event=threading.Event(),
            check_cancelled=lambda: None,
            set_active_process=lambda process: None,
            clear_active_process=lambda: None,
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            source = Path(temporary_dir) / "song.wav"
            source.touch()

            def fake_popen(command, **kwargs):
                commands.append(command)
                model = command[command.index("--model") + 1]
                if "--segment" not in command:
                    return FakeProcess(1, ["RuntimeError: insufficient resources\n"])
                output = Path(command[command.index("--output") + 1]) / model / source.stem
                output.mkdir(parents=True)
                (output / "vocals.wav").touch()
                (output / "no_vocals.wav").touch()
                return FakeProcess(0, ["100%\n"])

            updates = []
            with patch.dict(sys.modules, {"process_manager": fake_manager}), patch.object(
                audio_processor.subprocess, "Popen", side_effect=fake_popen
            ):
                vocals, instrumental = audio_processor.separate_vocals(
                    str(source),
                    temporary_dir,
                    update_callback=lambda *args, **kwargs: updates.append((args, kwargs)),
                )

        self.assertEqual(
            [command[command.index("--model") + 1] for command in commands],
            ["htdemucs_ft", "htdemucs_ft"],
        )
        self.assertIn("--segment", commands[1])
        self.assertTrue(vocals.endswith("vocals.wav"))
        self.assertTrue(instrumental.endswith("no_vocals.wav"))
        self.assertTrue(any("mesmo modelo de alta precisão" in update[1].get("stage_detail", "") for update in updates))

    def test_queue_removal_wakes_worker_and_cleanup_is_non_blocking(self):
        self.assertIn('target=cleanup_queue_cache_in_background', MAIN)
        self.assertIn('name=f"queue-remove-{job_id}"', MAIN)
        self.assertIn("processing_queue_event.set()", MAIN)

    def test_queue_can_be_reordered_from_interface(self):
        self.assertIn('@app.patch("/api/queue/{job_id}/position")', MAIN)
        self.assertIn("eligible_indexes", MAIN)
        self.assertIn("processing_queue[current_index], processing_queue[target_index]", MAIN)
        self.assertIn("async function moveQueuedJob", HTML)
        self.assertIn("Mover para cima", HTML)
        self.assertIn("Mover para baixo", HTML)

    def test_queue_pause_is_persistent_and_admin_controlled(self):
        self.assertIn('PROCESSING_QUEUE_CONTROL_FILE = "/data/output/processing_queue_control.json"', MAIN)
        self.assertIn('@app.post("/api/queue/pause")', MAIN)
        self.assertIn('@app.post("/api/queue/resume")', MAIN)
        self.assertIn("require_admin(current_user)", MAIN)
        self.assertIn("if processing_queue_paused:", MAIN)
        self.assertIn("load_processing_queue_control()", MAIN)
        self.assertIn("async function toggleProcessingQueuePause", HTML)
        self.assertIn("Pausar ao concluir etapa", HTML)

    def test_stage_checkpoints_preserve_expensive_results(self):
        self.assertIn('class StagePauseRequested(Exception):', MAIN)
        self.assertIn('"stage_checkpoints.json"', MAIN)
        self.assertIn('"audio_extracted"', MAIN)
        self.assertIn('"vocals_separated"', MAIN)
        self.assertIn('"transcription_ready"', MAIN)
        self.assertIn('"subtitle_transcription_reviewed"', MAIN)
        self.assertIn('"subtitles_generated"', MAIN)
        self.assertIn('"video_rendered"', MAIN)
        self.assertIn('queue_status = "queued"', MAIN)
        self.assertIn("Checkpoint salvo — é seguro reiniciar o servidor", HTML)

    def test_telegram_reports_automatic_lyrics_result(self):
        self.assertIn("letra-guia encontrada para", MAIN)
        self.assertIn("nenhuma letra-guia foi encontrada para", MAIN)
        self.assertIn("o processamento seguirá somente com o Whisper", MAIN)
        self.assertIn("letra-guia manual recebida para", MAIN)
        self.assertIn("será processado sem letra-guia", MAIN)

    def test_telegram_completion_reports_total_processing_time(self):
        self.assertIn("def format_processing_duration", MAIN)
        self.assertIn("active_processing_seconds", MAIN)
        self.assertIn("Tempo total de processamento", MAIN)
        self.assertIn("processing_seconds", MAIN)

    def test_mobile_process_summary_wraps_complete_values(self):
        self.assertIn(".process-summary { grid-template-columns: 1fr; }", HTML)
        self.assertIn("white-space: normal;", HTML)
        self.assertIn("overflow-wrap: anywhere;", HTML)


if __name__ == "__main__":
    unittest.main()
