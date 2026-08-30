import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
TRANSCRIBER = (ROOT / "app" / "transcriber.py").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")


class WhisperProgressTests(unittest.TestCase):
    def test_python_sources_parse(self):
        ast.parse(MAIN)
        ast.parse(TRANSCRIBER)

    def test_transcriber_reports_progress_while_consuming_segments(self):
        self.assertIn("progress_callback=None", TRANSCRIBER)
        self.assertIn("segment_end / total_duration", TRANSCRIBER)
        self.assertIn("progress_callback(100, total_duration, total_duration)", TRANSCRIBER)

    def test_all_transcription_modes_publish_whisper_progress(self):
        self.assertIn("progress_callback=publish_subtitle_whisper_progress", MAIN)
        self.assertIn("progress_callback=publish_whisper_progress", MAIN)
        self.assertIn("progress_callback=translation_progress", MAIN)

    def test_interface_has_separate_stage_progress_bar(self):
        self.assertIn('id="stageProgressBox"', HTML)
        self.assertIn('id="stageProgressBarFill"', HTML)
        self.assertIn("data.stage_progress", HTML)
        self.assertIn("Whisper {percent}%", MAIN)


if __name__ == "__main__":
    unittest.main()
