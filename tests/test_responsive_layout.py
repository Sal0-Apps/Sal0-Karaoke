import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")


class ResponsiveLayoutTests(unittest.TestCase):
    def test_page_and_primary_sections_cannot_expand_the_viewport(self):
        self.assertIn("overflow-x: clip", HTML)
        self.assertIn("#createTabContent,", HTML)
        self.assertIn("#settingsTabContent,", HTML)
        self.assertIn("#libraryTabContent", HTML)
        self.assertIn("min-width: 0;", HTML)
        self.assertIn("max-width: 100%;", HTML)

    def test_creator_modes_use_shrinkable_grid_columns(self):
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", HTML)
        self.assertNotIn("grid-template-columns: repeat(3, 1fr);", HTML)

    def test_dynamic_queue_rows_have_shrinkable_content_and_actions(self):
        self.assertIn(".queue-item > *", HTML)
        self.assertIn('class="queue-actions"', HTML)
        self.assertIn("overflow-wrap: anywhere;", HTML)

    def test_fixed_auto_fit_grid_respects_narrow_cards(self):
        self.assertNotIn("minmax(320px, 1fr)", HTML)
        self.assertIn("minmax(min(320px, 100%), 1fr)", HTML)


if __name__ == "__main__":
    unittest.main()
