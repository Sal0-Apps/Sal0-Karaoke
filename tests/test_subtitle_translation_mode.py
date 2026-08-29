import ast
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
TRANSCRIBER = (ROOT / "app" / "transcriber.py").read_text(encoding="utf-8")
TRANSLATOR = (ROOT / "app" / "subtitle_translator.py").read_text(encoding="utf-8")
REQUIREMENTS = (ROOT / "app" / "requirements.txt").read_text(encoding="utf-8")


class SubtitleTranslationModeTests(unittest.TestCase):
    def test_third_creator_mode_has_no_background_controls(self):
        self.assertIn('id="btnCreatorSubtitle"', HTML)
        self.assertIn('id="subtitleModeForm"', HTML)
        start = HTML.index('id="subtitleModeForm"')
        end = HTML.index('<!-- Form Principal -->', start)
        subtitle_form = HTML[start:end]
        self.assertNotIn('bg_file', subtitle_form)
        self.assertNotIn('backgroundMode', subtitle_form)
        self.assertIn('id="subtitleTranslationLanguage"', subtitle_form)
        self.assertIn('id="subtitleVideoFile"', subtitle_form)

    def test_subtitle_pipeline_skips_demucs_and_preserves_original_audio(self):
        tree = ast.parse(MAIN)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_subtitle_video_pipeline"
        )
        source = ast.get_source_segment(MAIN, function)
        self.assertNotIn("separate_vocals", source)
        self.assertIn('background_mode="original_video"', source)
        self.assertIn("instrumental_path=converted_wav", source)
        self.assertIn("write_srt(segments", source)

    def test_backend_enforces_subtitle_mode_invariants(self):
        self.assertIn('subtitle_only: bool = Form(False)', MAIN)
        self.assertIn('translation_language: str = Form("pt")', MAIN)
        self.assertIn('transcribe_source = "original"', MAIN)
        self.assertIn('show_instrumental = False', MAIN)
        self.assertIn('@app.get("/api/download-subtitles")', MAIN)

    def test_whisper_supports_native_translation_and_language_metadata(self):
        ast.parse(TRANSCRIBER)
        self.assertIn('"task": "translate" if task == "translate" else "transcribe"', TRANSCRIBER)
        self.assertIn('"language": str(getattr(info, "language"', TRANSCRIBER)

    def test_local_translation_model_is_open_and_persistent(self):
        ast.parse(TRANSLATOR)
        self.assertIn('TRANSLATION_MODEL = "facebook/m2m100_418M"', TRANSLATOR)
        self.assertIn('TRANSLATION_MODEL_REVISION = "791dc1c6d300846c9a747d4bd11fcc7f369b750e"', TRANSLATOR)
        self.assertIn('TRANSLATION_MODEL_DIR = "/data/output/models/translation"', TRANSLATOR)
        self.assertIn("use_safetensors=True", TRANSLATOR)
        self.assertIn("torch==2.10.0", REQUIREMENTS)
        self.assertIn("torchaudio==2.10.0", REQUIREMENTS)
        self.assertIn("safetensors>=0.4.3,<1", REQUIREMENTS)
        self.assertIn("transformers>=4.45,<5", REQUIREMENTS)
        self.assertIn("sentencepiece>=0.2,<1", REQUIREMENTS)

    def test_srt_writer_preserves_unicode_and_timing(self):
        namespace = {"os": __import__("os")}
        tree = ast.parse(TRANSLATOR)
        selected = [
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in {"srt_timestamp", "write_srt"}
        ]
        exec(compile(ast.Module(body=selected, type_ignores=[]), "subtitle_translator.py", "exec"), namespace)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "legenda.srt"
            namespace["write_srt"](
                [{"start": 1.25, "end": 65.75, "text": "Olá, mundo!"}],
                str(destination),
            )
            content = destination.read_text(encoding="utf-8-sig")
        self.assertIn("00:00:01,250 --> 00:01:05,750", content)
        self.assertIn("Olá, mundo!", content)


if __name__ == "__main__":
    unittest.main()
