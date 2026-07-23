import ast
import difflib
import importlib.util
import logging
import re
import tempfile
import unittest
import unicodedata
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "app" / "karaoke_generator.py"
SPEC = importlib.util.spec_from_file_location("karaoke_generator", MODULE_PATH)
karaoke_generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(karaoke_generator)


def load_lyrics_alignment_functions():
    main_path = Path(__file__).parents[1] / "app" / "main.py"
    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"clean_word", "align_lyrics"}
    ]
    namespace = {
        "re": re,
        "difflib": difflib,
        "unicodedata": unicodedata,
        "logger": logging.getLogger("test"),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(main_path), "exec"), namespace)
    return namespace["align_lyrics"]


align_lyrics = load_lyrics_alignment_functions()


def make_words(texts, start=0.0, step=0.5):
    return [
        {"word": f" {text}", "start": start + index * step, "end": start + index * step + 0.4}
        for index, text in enumerate(texts)
    ]


class SubtitleSegmentationTests(unittest.TestCase):
    def test_lyrics_lines_become_natural_verse_boundaries(self):
        words = make_words(["eu", "canto", "este", "verso", "e", "depois", "vem", "outro"])
        transcription = [
            {"start": 0, "end": 1.9, "text": "", "words": words[:4]},
            {"start": 2, "end": 3.9, "text": "", "words": words[4:]},
        ]

        guided = align_lyrics("eu canto este verso\ne depois vem outro", transcription)
        result = karaoke_generator.split_and_wrap_segments(guided, 0, 0, True)

        self.assertEqual([len(segment["words"]) for segment in result], [4, 4])

    def test_whisper_boundary_does_not_cut_a_short_verse(self):
        words = make_words(["eu", "quero", "cantar", "este", "verso", "inteiro", "com", "voce"])
        words[-1]["lyric_line_break"] = True
        segments = [
            {"start": 0, "end": 1.9, "text": "", "words": words[:4]},
            {"start": 2, "end": 3.9, "text": "", "words": words[4:]},
        ]

        result = karaoke_generator.split_and_wrap_segments(segments, 0, 0, True)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["words"]), 8)

    def test_official_lyric_line_is_kept_as_one_verse(self):
        first = make_words(["quando", "a", "musica", "comeca", "eu", "canto", "ate", "o", "fim"])
        second = make_words(["depois", "vem", "outro", "verso"], start=4.6)
        first[-1]["lyric_line_break"] = True
        second[-1]["lyric_line_break"] = True
        segments = [{"start": 0, "end": 6.5, "text": "", "words": first + second}]

        result = karaoke_generator.split_and_wrap_segments(segments, 0, 0, True)

        self.assertEqual([len(segment["words"]) for segment in result], [9, 4])

    def test_hard_limit_still_prevents_a_giant_block(self):
        words = make_words([f"palavra{index}" for index in range(32)])
        segments = [{"start": 0, "end": 16, "text": "", "words": words}]

        result = karaoke_generator.split_and_wrap_segments(segments, 0, 0, False)

        self.assertGreater(len(result), 1)
        self.assertTrue(all(len(segment["words"]) <= 15 for segment in result))

    def test_display_continues_until_the_next_verse(self):
        first = make_words(["primeiro", "verso"])
        second = make_words(["segundo", "verso"], start=3.0)
        segments = [
            {"start": 0, "end": 0.9, "text": "", "words": first},
            {"start": 3, "end": 3.9, "text": "", "words": second},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "lyrics.ass"
            karaoke_generator.generate_ass_karaoke(
                segments,
                str(output),
                show_instrumental=False,
                break_on_punctuation=False,
            )
            ass_text = output.read_text(encoding="utf-8")

        self.assertIn("Dialogue: 0,0:00:00.00,0:00:03.00", ass_text)


if __name__ == "__main__":
    unittest.main()
