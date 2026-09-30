import ast
import difflib
import logging
import re
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "app"))
from lyrics_sync import parse_lrc, recording_matches
from karaoke_generator import generate_ass_karaoke
import tempfile
import subprocess


class HTTPError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


def load_function(name, **values):
    tree = ast.parse((ROOT / "app/main.py").read_text())
    selected = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    selected.decorator_list = []
    scope = dict(HTTPException=HTTPError, Depends=lambda _: None, get_current_user=Mock(),
                 YouTubeSearchRequest=object, re=re, difflib=difflib,
                 logger=logging.getLogger("test"), recording_matches=recording_matches, **values)
    exec(compile(ast.Module(body=[selected], type_ignores=[]), "main.py", "exec"), scope)
    return scope[name]


class AutomaticLyricsTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(artist_name="Artista", track_name="Canção", duration=180,
                           lyrics_text="Primeiro verso\nSegundo verso", has_lyrics=True,
                           synced_lyrics="[00:10.00]Primeiro verso\n[00:13.00]Segundo verso\n[00:17.00]")

    def test_requires_same_recording_and_known_duration(self):
        self.assertTrue(recording_matches("Artista - Canção (Official Video)", self.record, 180))
        for query, duration in [("Outro - Canção", 180), ("Artista - Canção ao vivo", 180),
                                ("Artista - Canção", 187), ("Canção", 180),
                                ("Artista - Canção", float("nan")), ("Artista - Canção", None)]:
            self.assertFalse(recording_matches(query, self.record, duration))

    def test_lrc_keeps_blanks_as_instrumental_boundaries(self):
        result = parse_lrc(self.record["synced_lyrics"], 180)
        self.assertEqual([(s["start"], s["end"]) for s in result], [(10, 13), (13, 17)])
        self.assertTrue(all(s["words"] == [] for s in result))

    def test_repeated_clocks_offsets_and_fraction_precision(self):
        result = parse_lrc("[offset:500]\n[00:01.5][00:08.125]Refrão\n[00:12]Fim", 20)
        self.assertEqual([s["start"] for s in result], [2, 8.625, 12.5])

    def test_invalid_or_ambiguous_lrc_returns_fallback(self):
        for text in ("Texto sem tempos", "[00:90]Erro", "[99:00]Fora da música",
                     "[00:01]A\n[00:01]B\n[00:02]C"):
            self.assertEqual(parse_lrc(text, 10), [])
        self.assertEqual(parse_lrc(self.record["synced_lyrics"], 0), [])

    def test_compatible_synced_record_wins_over_other_versions(self):
        wrong = {**self.record, "duration": 230, "synced_lyrics": ""}
        lookup = load_function("find_lyrics_automatically", search_lyrics_providers=lambda _: [wrong, self.record])
        text, metadata = lookup("Artista - Canção", 180)
        self.assertEqual(metadata["duration"], 180)
        self.assertEqual(text, self.record["lyrics_text"])
        self.assertEqual(metadata["synced_lyrics"], self.record["synced_lyrics"])

    def test_offline_provider_failure_still_allows_whisper(self):
        lookup = load_function("find_lyrics_automatically", search_lyrics_providers=lambda _: [])
        self.assertEqual(lookup("Artista - Canção", 180), ("", None))

    def test_synced_lines_animate_without_invented_word_clocks(self):
        segments = parse_lrc(self.record["synced_lyrics"], 180)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "karaoke.ass")
            generate_ass_karaoke(segments, path, show_instrumental=False)
            output = Path(path).read_text()
        self.assertIn("0:00:10.00,0:00:13.00", output)
        self.assertIn("Primeiro verso", output)
        self.assertIn("{\\kf300}Primeiro verso", output)
        self.assertIn("{\\kf400}Segundo verso", output)
        self.assertTrue(all(not s["words"] for s in segments))

    def test_synced_line_animation_survives_every_display_mode(self):
        segments = parse_lrc(self.record["synced_lyrics"], 180)
        for mode in ('syllable', 'word', 'line', 'phrase'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'karaoke.ass'
                generate_ass_karaoke(segments, str(path), subtitle_mode=mode, show_instrumental=False)
                self.assertIn("{\\kf300}Primeiro verso", path.read_text())

    def test_ffmpeg_displays_progressive_highlight_within_synced_verse(self):
        segments = parse_lrc('[00:00]First synchronized verse\n[00:01]Second verse', 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'karaoke.ass'
            generate_ass_karaoke(segments, str(path), show_instrumental=False)
            def white_pixels(time):
                raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=black:s=1280x720:r=25:d=2', '-vf', 'ass='+str(path), '-ss', str(time),
                    '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
                return sum(min(raw[i:i+3]) > 220 for i in range(0, len(raw), 3))
            self.assertGreater(white_pixels(.8), white_pixels(.2))


class YouTubeSearchTests(unittest.TestCase):
    def make_search(self, payload=None, error=None):
        ydl = Mock()
        ydl.extract_info = Mock(return_value=payload, side_effect=error)
        manager = Mock()
        manager.__enter__ = Mock(return_value=ydl)
        manager.__exit__ = Mock(return_value=False)
        factory = Mock(return_value=manager)
        function = load_function("search_youtube", yt_dlp_operation_lock=threading.Lock(),
                                 load_yt_dlp=lambda: SimpleNamespace(YoutubeDL=factory),
                                 youtube_download_options=lambda: {})
        return function, ydl, factory

    def test_search_only_returns_canonical_video_urls_without_download(self):
        search, ydl, factory = self.make_search({"entries": [None,
            {"id": "abcdef12345", "title": "Faixa", "channel": "Canal", "duration": 180},
            {"id": "../../bad", "url": "http://localhost"},
            {"id": "123456789ab", "is_live": True}]})
        result = search(SimpleNamespace(query="Artista - Canção"), {"username": "test"})
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["url"], "https://www.youtube.com/watch?v=abcdef12345")
        ydl.extract_info.assert_called_once_with("ytsearch6:Artista - Canção", download=False)
        self.assertTrue(factory.call_args.args[0]["extract_flat"])

    def test_failures_are_reported_without_internal_error_details(self):
        search, _, _ = self.make_search(error=RuntimeError("sensitive internals"))
        with self.assertRaises(HTTPError) as result:
            search(SimpleNamespace(query="Música"), {})
        self.assertEqual(result.exception.status_code, 502)
        self.assertNotIn("sensitive", str(result.exception))

    def test_blank_search_is_rejected_before_network(self):
        search, ydl, _ = self.make_search({})
        with self.assertRaises(HTTPError):
            search(SimpleNamespace(query="  "), {})
        ydl.extract_info.assert_not_called()


if __name__ == "__main__":
    unittest.main()
