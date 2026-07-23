import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")


class YouTubeCreationFlowTests(unittest.TestCase):
    def test_create_modes_use_links_without_predownload_buttons(self):
        self.assertNotIn('id="btnDownloadYoutube"', HTML)
        self.assertNotIn('id="btnDownloadBgYoutube"', HTML)
        self.assertIn('name="youtube_url"', HTML)
        self.assertIn("prepareYoutubeBackground(backgroundUrl", HTML)
        self.assertIn("formData.set('library_bg', filename)", HTML)

    def test_download_controls_live_in_library(self):
        for control_id in (
            "libAudioYoutubeUrl",
            "btnLibDownloadYoutube",
            "libBgYoutubeUrl",
            "btnLibDownloadBgYoutube",
        ):
            self.assertIn(f'id="{control_id}"', HTML)

    def test_every_youtube_input_has_title_identification(self):
        for input_id in (
            "youtubeUrl",
            "bgYoutubeUrl",
            "easyYoutubeUrl",
            "easyBgYoutubeUrl",
            "libAudioYoutubeUrl",
            "libBgYoutubeUrl",
        ):
            self.assertIn(f"['{input_id}'", HTML)
        self.assertIn("fetchYoutubeMetadata(url)", HTML)

    def test_processing_summary_tracks_lyrics_model_and_background(self):
        self.assertIn('id="processSummary"', HTML)
        self.assertIn("renderProcessSummary(data.process_summary || {})", HTML)
        self.assertIn('"process_summary": {}', MAIN)
        self.assertIn('update_process_summary(lyrics="Letra-guia + Whisper")', MAIN)
        self.assertIn('update_process_summary(lyrics="Somente Whisper")', MAIN)


if __name__ == "__main__":
    unittest.main()
