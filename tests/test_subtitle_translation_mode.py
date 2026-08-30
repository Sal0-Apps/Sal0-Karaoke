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
AUDIO_PROCESSOR = (ROOT / "app" / "audio_processor.py").read_text(encoding="utf-8")


class SubtitleTranslationModeTests(unittest.TestCase):
    def test_srt_results_are_sent_as_telegram_documents_with_download_links(self):
        self.assertIn("def send_telegram_document_flow", MAIN)
        self.assertIn("/sendDocument", MAIN)
        self.assertIn("send_documents_to_targets(", MAIN)
        self.assertIn("translated_public_token", MAIN)
        self.assertIn("/api/public/download/", MAIN)

    def test_third_creator_mode_accepts_audio_or_video_and_has_no_visual_controls(self):
        self.assertIn('id="btnCreatorSubtitle"', HTML)
        self.assertIn('id="subtitleModeForm"', HTML)
        start = HTML.index('id="subtitleModeForm"')
        end = HTML.index('<!-- Form Principal -->', start)
        subtitle_form = HTML[start:end]
        self.assertNotIn('bg_file', subtitle_form)
        self.assertNotIn('backgroundMode', subtitle_form)
        self.assertIn('id="subtitleTranslationLanguage"', subtitle_form)
        self.assertIn('id="subtitleVideoFile"', subtitle_form)
        self.assertIn('accept="audio/*,video/*', subtitle_form)
        self.assertNotIn('id="subtitleVisualMode"', subtitle_form)
        self.assertNotIn('id="subtitleTextPosition"', subtitle_form)
        self.assertIn('Gerar arquivos SRT', subtitle_form)

    def test_subtitle_pipeline_returns_only_srt_and_normalizes_media_to_mp3(self):
        tree = ast.parse(MAIN)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_subtitle_srt_pipeline"
        )
        source = ast.get_source_segment(MAIN, function)
        self.assertNotIn("separate_vocals", source)
        self.assertNotIn("render_karaoke_video", source)
        self.assertNotIn("generate_ass_karaoke", source)
        self.assertNotIn("final_karaoke.mp4", source)
        self.assertIn("extract_audio_mp3(input_media_path, normalized_mp3)", source)
        self.assertIn("final_subtitles_original.srt", source)
        self.assertIn("final_subtitles_translated.srt", source)
        self.assertIn('result_kind="subtitles"', source)
        self.assertIn("def extract_audio_mp3", AUDIO_PROCESSOR)
        self.assertIn('"-map", "0:a:0"', AUDIO_PROCESSOR)
        self.assertIn('"-codec:a", "libmp3lame"', AUDIO_PROCESSOR)

    def test_original_srt_survives_optional_translation_failure(self):
        original_save = MAIN.index("original_filename = save_srt_result(")
        translation_try = MAIN.index("if translation_language != \"original\":", original_save)
        self.assertLess(original_save, translation_try)
        self.assertIn("except Exception as exc:", MAIN[translation_try:])
        self.assertIn("A tradução opcional falhou; o SRT original foi preservado.", MAIN)
        self.assertIn('"original": "original_subtitle_filename"', MAIN)
        self.assertIn('"translated": "translated_subtitle_filename"', MAIN)
        self.assertIn('id="btnDownloadOriginalSubtitles"', HTML)
        self.assertIn('id="btnDownloadTranslatedSubtitles"', HTML)
        self.assertIn("data.translation_error", HTML)

    def test_backend_enforces_subtitle_mode_invariants(self):
        self.assertIn('subtitle_only: bool = Form(False)', MAIN)
        self.assertIn('translation_language: str = Form("pt")', MAIN)
        self.assertIn('transcribe_source = "original"', MAIN)
        self.assertIn('show_instrumental = False', MAIN)
        self.assertIn('@app.get("/api/download-subtitles")', MAIN)
        self.assertIn('task="transcribe"', MAIN)

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
        self.assertIn("low_cpu_mem_usage=False", TRANSLATOR)
        self.assertIn('model.to(torch.device("cpu"))', TRANSLATOR)
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

    def test_srt_timeline_covers_media_from_start_to_finish_without_gaps(self):
        namespace = {}
        tree = ast.parse(TRANSLATOR)
        selected = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "cover_full_media_timeline"
        )
        exec(compile(ast.Module(body=[selected], type_ignores=[]), "subtitle_translator.py", "exec"), namespace)
        covered = namespace["cover_full_media_timeline"](
            [
                {"start": 3.0, "end": 5.0, "text": "Primeira"},
                {"start": 8.0, "end": 10.0, "text": "Segunda"},
            ],
            20.0,
        )
        self.assertEqual(covered[0]["start"], 0.0)
        self.assertEqual(covered[0]["end"], covered[1]["start"])
        self.assertEqual(covered[-1]["end"], 20.0)


if __name__ == "__main__":
    unittest.main()
