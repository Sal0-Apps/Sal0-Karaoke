import ast
import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MAIN_PATH = ROOT / "app" / "main.py"
HTML_PATH = ROOT / "app" / "templates" / "index.html"
MAIN = MAIN_PATH.read_text(encoding="utf-8")
HTML = HTML_PATH.read_text(encoding="utf-8")
ANDROID = (ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "sal0" / "karaoke" / "MainActivity.java").read_text(encoding="utf-8")


def load_filename_builder():
    tree = ast.parse(MAIN)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "karaoke_download_filename"
    )
    namespace = {"os": os, "re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(MAIN_PATH), "exec"), namespace)
    return namespace["karaoke_download_filename"]


class ResultDownloadTests(unittest.TestCase):
    def test_filename_keeps_song_title_and_adds_karaoke(self):
        build = load_filename_builder()
        self.assertEqual(build("Minha Música.mp3"), "Minha Música - Karaokê.mp4")
        self.assertEqual(build("AC/DC: Live.mp4"), "ACDC Live - Karaokê.mp4")
        self.assertEqual(build("Canção - Karaokê.mp4"), "Canção - Karaokê.mp4")

    def test_final_endpoint_and_history_share_the_filename_builder(self):
        self.assertIn("dest_filename = karaoke_download_filename(orig_name)", MAIN)
        self.assertIn("download_name = karaoke_download_filename(orig_name)", MAIN)

    def test_button_uses_a_direct_authenticated_download(self):
        self.assertIn("link.href = `/api/download?token=${encodeURIComponent(authToken)}", HTML)
        self.assertNotIn("sal0_karaoke_video_final.mp4", HTML)

    def test_all_server_downloads_publish_utf8_attachment_names(self):
        self.assertIn("def attachment_file_response", MAIN)
        self.assertIn("filename*=UTF-8", MAIN)
        self.assertGreaterEqual(MAIN.count("attachment_file_response("), 6)

    def test_android_prefers_server_filename_and_avoids_overwrite(self):
        self.assertIn("resolveDownloadFileName(download)", ANDROID)
        self.assertIn('Pattern.compile("(?i)filename\\\\*', ANDROID)
        self.assertIn("URLDecoder.decode", ANDROID)
        self.assertIn("uniqueDownloadFileName", ANDROID)
        self.assertIn("setAllowedOverMetered(true)", ANDROID)

    def test_large_telegram_video_uses_temporary_preview_and_original_link(self):
        self.assertIn("def compress_video_for_telegram", MAIN)
        self.assertIn('compressed_target = 46 * 1024 * 1024', MAIN)
        self.assertIn('"-pass", "1"', MAIN)
        self.assertIn('"-pass", "2"', MAIN)
        self.assertIn("prévia compactada", MAIN)
        self.assertIn("arquivo original sem compressão", MAIN)


if __name__ == "__main__":
    unittest.main()
