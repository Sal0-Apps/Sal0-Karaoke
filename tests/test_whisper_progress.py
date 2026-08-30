import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
TRANSCRIBER = (ROOT / "app" / "transcriber.py").read_text(encoding="utf-8")
RENDERER = (ROOT / "app" / "video_renderer.py").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")


class WhisperProgressTests(unittest.TestCase):
    def test_python_sources_parse(self):
        ast.parse(MAIN)
        ast.parse(TRANSCRIBER)
        ast.parse(RENDERER)

    def test_transcriber_reports_progress_while_consuming_segments(self):
        self.assertIn("progress_callback=None", TRANSCRIBER)
        self.assertIn("segment_end / total_duration", TRANSCRIBER)
        self.assertIn("progress_callback(100, total_duration, total_duration)", TRANSCRIBER)

    def test_all_transcription_modes_publish_whisper_progress(self):
        self.assertIn("progress_callback=publish_subtitle_whisper_progress", MAIN)
        self.assertIn("progress_callback=publish_whisper_progress", MAIN)
        self.assertIn("progress_callback=translation_progress", MAIN)

    def test_video_rendering_reports_current_stage_and_total_progress(self):
        self.assertIn('"-progress", "pipe:1", "-nostats"', RENDERER)
        self.assertIn('line_str.startswith("out_time_ms=")', RENDERER)
        self.assertIn("progress_callback=publish_render_progress", MAIN)
        self.assertIn("95 + round(percent * 0.03)", MAIN)

    def test_interface_has_one_total_bar_and_compact_stage_percentage(self):
        self.assertIn('id="progressBarFill"', HTML)
        self.assertIn('aria-label="Progresso total do processo"', HTML)
        self.assertNotIn('id="stageProgressBox"', HTML)
        self.assertNotIn('id="stageProgressBarFill"', HTML)
        self.assertNotIn('id="timeline"', HTML)
        self.assertIn("data.stage_progress", HTML)
        self.assertIn("overallProgress", HTML)
        self.assertIn("currentStageProgress", HTML)
        self.assertIn("% da etapa atual", HTML)
        self.assertIn("Whisper {percent}%", MAIN)


if __name__ == "__main__":
    unittest.main()
