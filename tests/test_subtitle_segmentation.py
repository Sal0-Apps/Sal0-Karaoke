import ast
import copy
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
    def test_guide_corrects_misheard_words_between_confirmed_phrases(self):
        words = make_words(['eu', 'quero', 'gastar', 'com', 'você', 'nesta', 'noite'])
        original = [{'start': 0, 'end': 3.5, 'words': words, 'text': ''}]
        result = align_lyrics('eu quero cantar com você nesta noite', original)
        self.assertEqual(result[0]['words'][2]['word'], ' cantar')
        self.assertEqual([(w['start'], w['end']) for w in result[0]['words']],
                         [(w['start'], w['end']) for w in words])
        self.assertEqual(original[0]['words'][2]['word'], ' gastar')

    def test_guide_does_not_insert_missing_words_or_copy_an_unrelated_lyric(self):
        words = make_words(['fala', 'outra', 'coisa', 'hoje'])
        result = align_lyrics('eu quero cantar com você nesta noite',
                              [{'start':0,'end':2,'words':words}])
        self.assertEqual(result[0]['words'], words)

    def test_repeated_choruses_keep_their_existing_word_clocks(self):
        words = make_words(['eu','quero','gastar','com','você','eu','quero','gastar','com','você'])
        result = align_lyrics('eu quero cantar com você\neu quero cantar com você',
                              [{'start':0,'end':5,'words':words}])
        self.assertEqual([w['word'].strip() for w in result[0]['words']],
                         'eu quero cantar com você eu quero cantar com você'.split())
        self.assertEqual([w['start'] for w in result[0]['words']], [w['start'] for w in words])

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
        self.assertTrue(all(segment['end'] - segment['start'] <= 14 for segment in result))
        self.assertEqual([word for segment in result for word in segment['words']], words)

    def test_display_limits_never_split_me_deu_between_pages(self):
        text = 'Prefiro ter você a meu lado e lembrar com saudade o retratinho que você me deu'
        words = make_words(text.split(), step=.45)
        original = [dict(start=0, end=8, text=text, words=words)]
        before = copy.deepcopy(original)
        for words_limit, chars_limit in ((0, 0), (4, 18), (1, 3), (6, 40)):
            with self.subTest(limits=(words_limit, chars_limit)):
                result = karaoke_generator.split_and_wrap_segments(original, words_limit, chars_limit)
                self.assertEqual([segment['text'] for segment in result], [text])
        self.assertEqual(original, before)

    def test_whisper_only_follows_sung_phrases_without_guide_markers(self):
        phrases = ['Achei numa caixinha de lembranças',
                   'Um presente de alguém que está ausente de mim',
                   'Prefiro ter você a meu lado',
                   'E lembrar com saudade o retratinho que você me deu']
        words = make_words(' '.join(phrases).split(), step=.7)
        for word in words:
            word['end'] = word['start'] + .55
        # ASR segments can themselves stop in the middle of a sung phrase.
        segments = [dict(words=words[:8]), dict(words=words[8:25]), dict(words=words[25:])]
        result = karaoke_generator.split_and_wrap_segments(segments)
        self.assertEqual([segment['text'] for segment in result], phrases)
        self.assertEqual([word for segment in result for word in segment['words']], words)

    def test_asr_boundary_cannot_orphan_me_deu_in_next_verse(self):
        first = 'Prefiro ter você a meu lado e lembrar com saudade o retratinho que você me deu'
        second = 'Prefiro ter você a meu lado'
        words = make_words((first + ' ' + second).split(), step=.45)
        for boundary in (14, 15):
            with self.subTest(asr_boundary=boundary):
                segments = [dict(words=words[:boundary]), dict(words=words[boundary:])]
                result = karaoke_generator.split_and_wrap_segments(segments, 6, 40)
                self.assertEqual([segment['text'] for segment in result], [first, second])

    def test_long_confirmed_guide_line_is_not_cut_by_asr_pauses_or_display_limits(self):
        words = make_words('Quando a música começa eu canto até o fim e sigo com você até o amanhecer'.split(), step=1)
        words[-1]['lyric_line_break'] = True
        result = karaoke_generator.split_and_wrap_segments([dict(words=words)], 3, 15)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['words'], words)

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
