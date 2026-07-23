import ast
import re
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
    namespace = {"re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(MAIN_PATH), "exec"), namespace)
    return namespace["EASY_MODE_DEFAULTS"], namespace["normalize_easy_mode_config"]


class EasyModeConfigTests(unittest.TestCase):
    def test_requested_defaults_are_kept(self):
        defaults, normalize = load_normalizer()
        config = normalize()

        self.assertEqual(defaults["whisper_model"], "large-v3-turbo")
        self.assertEqual(config["font_size"], 50)
        self.assertEqual(config["transcription_preset"], "difficult")
        self.assertEqual(config["transcribe_source"], "original")
        self.assertEqual(config["text_color"], "#00FFFF")
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
        self.assertEqual(config["text_color"], "#00FFFF")
        self.assertEqual(config["text_position"], "bottom")
        self.assertEqual(config["subtitle_mode"], "syllable")
        self.assertEqual(config["background_mode"], "original")
        self.assertEqual(config["lyrics_mode"], "auto")
        self.assertEqual(config["words_per_line"], 30)
        self.assertEqual(config["max_chars_line"], 0)

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
        self.assertIn("switcher.append(admin ? advancedButton : easyButton", html)
        self.assertIn("setCreatorMode(easyModeConfig.enabled && !admin ? 'easy' : 'advanced')", html)


if __name__ == "__main__":
    unittest.main()
