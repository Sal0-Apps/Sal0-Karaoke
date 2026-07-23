import ast
import unittest
from pathlib import Path


MAIN_PATH = Path(__file__).parents[1] / "app" / "main.py"


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
    namespace = {}
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

    def test_invalid_admin_values_are_safely_normalized(self):
        _, normalize = load_normalizer()
        config = normalize({"whisper_model": "unknown", "font_size": 999, "transcription_preset": "x"})

        self.assertEqual(config["whisper_model"], "large-v3-turbo")
        self.assertEqual(config["font_size"], 72)
        self.assertEqual(config["transcription_preset"], "difficult")

    def test_easy_mode_forces_automatic_no_review_pipeline(self):
        tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
        process_function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "process_karaoke"
        )
        easy_block = next(
            node for node in process_function.body
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "easy_mode"
        )
        constants = {}
        for node in easy_block.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if isinstance(node.value, ast.Constant):
                    constants[node.targets[0].id] = node.value.value

        self.assertEqual(constants["lyrics_mode"], "auto")
        self.assertFalse(constants["pause_for_editing"])
        self.assertFalse(constants["enable_correction"])
        self.assertTrue(constants["save_to_library"])


if __name__ == "__main__":
    unittest.main()
