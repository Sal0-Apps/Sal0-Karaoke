import ast
import logging
import os
import random
import re
import shutil
import tempfile
import unittest
from pathlib import Path


MAIN_PATH = Path(__file__).parents[1] / "app" / "main.py"
HTML_PATH = Path(__file__).parents[1] / "app" / "templates" / "index.html"


def load_normalizer():
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "EASY_MODE_DEFAULTS"
            for target in node.targets
        ):
            nodes.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_easy_mode_config":
            nodes.append(node)
    namespace = {"re": re, "os": os}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MAIN_PATH), "exec"), namespace)
    return namespace["EASY_MODE_DEFAULTS"], namespace["normalize_easy_mode_config"]


def load_random_background_stager(owner_library: Path, user_library: Path):
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "QUICK_BACKGROUND_STAGE_PREFIX"
            for target in node.targets
        ):
            nodes.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "stage_quick_random_background":
            nodes.append(node)

    namespace = {
        "os": os,
        "random": random,
        "shutil": shutil,
        "logger": logging.getLogger("test"),
        "user_from_username": lambda username: {"username": username, "role": "admin"} if username == "admin" else None,
        "is_admin": lambda user: user.get("role") == "admin",
        "get_user_paths": lambda user: {
            "library": str(owner_library if user.get("role") == "admin" else user_library)
        },
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MAIN_PATH), "exec"), namespace)
    return namespace["stage_quick_random_background"]


class EasyModeConfigTests(unittest.TestCase):
    def test_requested_defaults_are_kept(self):
        defaults, normalize = load_normalizer()
        config = normalize()

        self.assertEqual(defaults["whisper_model"], "large-v3-turbo")
        self.assertEqual(config["font_size"], 50)
        self.assertEqual(config["transcription_preset"], "difficult")
        self.assertEqual(config["transcribe_source"], "vocals")
        self.assertEqual(config["text_color"], "#008080")
        self.assertEqual(config["text_position"], "middle")
        self.assertEqual(config["background_mode"], "random_library")
        self.assertEqual(config["random_backgrounds"], [])
        self.assertEqual(config["subtitle_mode"], "syllable")
        self.assertEqual(config["lyrics_mode"], "auto")
        self.assertTrue(config["show_next_line_preview"])
        self.assertFalse(config["enable_correction"])
        self.assertTrue(config["save_to_library"])

    def test_invalid_admin_values_are_safely_normalized(self):
        _, normalize = load_normalizer()
        config = normalize({
            "whisper_model": "unknown", "font_size": 999, "transcription_preset": "x",
            "text_color": "cyan", "text_position": "left", "subtitle_mode": "giant",
            "background_mode": "cloud", "lyrics_mode": "off", "words_per_line": 99,
            "max_chars_line": -8,
        })

        self.assertEqual(config["whisper_model"], "large-v3-turbo")
        self.assertEqual(config["font_size"], 72)
        self.assertEqual(config["transcription_preset"], "difficult")
        self.assertEqual(config["text_color"], "#008080")
        self.assertEqual(config["text_position"], "middle")
        self.assertEqual(config["subtitle_mode"], "syllable")
        self.assertEqual(config["background_mode"], "random_library")
        self.assertEqual(config["lyrics_mode"], "auto")
        self.assertEqual(config["words_per_line"], 30)
        self.assertEqual(config["max_chars_line"], 0)

    def test_random_background_names_are_sanitized_and_limited(self):
        _, normalize = load_normalizer()
        names = ["show.mp4", "../capa.jpg", ".hidden.png", "show.mp4"] + [
            f"fundo-{index}.webm" for index in range(120)
        ]
        config = normalize({"random_backgrounds": names})

        self.assertEqual(config["random_backgrounds"][:2], ["show.mp4", "capa.jpg"])
        self.assertNotIn(".hidden.png", config["random_backgrounds"])
        self.assertEqual(len(config["random_backgrounds"]), 100)

    def test_easy_mode_applies_the_complete_admin_profile_server_side(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
        process_function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "process_karaoke"
        )
        easy_block = next(
            node for node in process_function.body
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "easy_mode"
        )
        config_assignments = {}
        constants = {}
        for node in easy_block.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if isinstance(node.value, ast.Constant):
                    constants[node.targets[0].id] = node.value.value
                if (
                    isinstance(node.value, ast.Subscript)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "easy_config"
                    and isinstance(node.value.slice, ast.Constant)
                ):
                    config_assignments[node.targets[0].id] = node.value.slice.value

        expected = {
            "whisper_model", "font_size", "text_color", "text_position", "subtitle_mode",
            "words_per_line", "max_chars_line", "break_on_punctuation", "enable_vad",
            "transcription_preset", "show_instrumental", "transcribe_source",
            "show_next_line_preview", "lyrics_mode", "enable_correction",
            "keep_first_line_visible", "save_to_library", "only_remove_vocals",
        }
        self.assertTrue(expected.issubset(config_assignments.keys()))
        self.assertFalse(constants["pause_for_editing"])

    def test_admin_interface_exposes_every_easy_mode_setting(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        expected_ids = {
            "easyModeEnabled", "easyModeModel", "easyModePreset", "easyModeSource",
            "easyModeEnableVad", "easyModeLyricsMode", "easyModeSubtitleMode",
            "easyModeFontSize", "easyModeTextColor", "easyModeTextPosition",
            "easyModeWordsPerLine", "easyModeMaxCharsLine", "easyModeNextPreview",
            "easyModeFirstLine", "easyModeBackgroundMode", "easyModeBreakPunctuation",
            "easyModeInstrumental", "easyModeCorrection", "easyModeSaveLibrary",
            "easyModeOnlyVocals",
        }
        self.assertTrue(all(f'id="{field_id}"' in html for field_id in expected_ids))
        self.assertIn('id="easyModeRandomBackgroundList"', html)
        self.assertIn("setCreatorMode(easyModeConfig.enabled ? 'easy' : 'advanced')", html)
        self.assertNotIn("switcher.append(admin ? advancedButton : easyButton", html)

    def test_quick_mode_is_primary_and_uses_direct_source_choices(self):
        html = HTML_PATH.read_text(encoding="utf-8")

        self.assertIn("let currentCreatorMode = 'easy';", html)
        self.assertIn("let easyAudioMode = 'youtube';", html)
        self.assertIn("⚡ Modo Rápido", html)
        self.assertIn('<span class="creator-mode-title">Detalhado</span>', html)
        self.assertIn('id="easyYoutubeUrl"', html)
        self.assertIn('id="easyAudioFile"', html)
        self.assertIn('id="easyLibraryAudio"', html)
        self.assertNotIn('id="easyAudioUploadTab"', html)
        self.assertIn("formData.set('easy_background_choice'", html)

    def test_random_collection_is_private_and_staged_server_side(self):
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn('config.pop("random_backgrounds", None)', source)
        self.assertIn('config.pop("random_background_owner", None)', source)
        self.assertIn("def stage_quick_random_background", source)
        self.assertIn('QUICK_BACKGROUND_STAGE_PREFIX = ".quick_random_background"', source)
        self.assertIn("random.choice(candidates)", source)

    def test_random_background_is_copied_to_a_hidden_user_slot(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            owner_library = root / "owner"
            user_library = root / "user"
            (owner_library / "photos").mkdir(parents=True)
            (user_library / "photos").mkdir(parents=True)
            (owner_library / "photos" / "palco.mp4").write_bytes(b"background")
            stale = user_library / "photos" / ".quick_random_background.jpg"
            stale.write_bytes(b"old")

            stage = load_random_background_stager(owner_library, user_library)
            staged_name, display_name = stage(
                {"random_background_owner": "admin", "random_backgrounds": ["palco.mp4"]},
                {"username": "cantor", "role": "user"},
            )

            self.assertEqual(staged_name, ".quick_random_background.mp4")
            self.assertEqual(display_name, "palco")
            self.assertEqual((user_library / "photos" / staged_name).read_bytes(), b"background")
            self.assertFalse(stale.exists())

    def test_all_file_inputs_support_drag_and_drop(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        expected_bindings = {
            "['easyAudioUploadBox', 'easyAudioFile']",
            "['easyBackgroundUploadBox', 'easyBgFile']",
            "['audioUploadArea', 'audioFile']",
            "['bgUploadArea', 'bgFile']",
            "['libAudioUploadArea', 'libAudioFile']",
            "['libBgUploadArea', 'libBgFile']",
        }

        self.assertTrue(all(binding in html for binding in expected_bindings))
        self.assertIn("function bindFileDropZone", html)
        self.assertIn("const transfer = new DataTransfer();", html)
        self.assertIn("input.dispatchEvent(new Event('change'", html)
        self.assertIn(".is-dragging", html)

    def test_status_polling_stays_current_without_overlapping_requests(self):
        html = HTML_PATH.read_text(encoding="utf-8")
        source = MAIN_PATH.read_text(encoding="utf-8")

        self.assertIn("let statusRequestInFlight = false;", html)
        self.assertIn("function scheduleStatusPoll", html)
        self.assertIn("authFetch('/api/status', { cache: 'no-store' })", html)
        self.assertIn("document.addEventListener('visibilitychange'", html)
        self.assertIn("window.addEventListener('focus'", html)
        self.assertNotIn("setInterval(fetchStatus", html)
        self.assertLess(
            html.index("await fetchStatus();", html.index("const isAuthenticated")),
            html.index("await fetchEasyModeConfig();", html.index("const isAuthenticated")),
        )
        self.assertGreaterEqual(html.count("setCreationUiLocked(true);"), 5)
        self.assertIn('response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"', source)


if __name__ == "__main__":
    unittest.main()
