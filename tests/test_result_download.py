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


if __name__ == "__main__":
    unittest.main()
