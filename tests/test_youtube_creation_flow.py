import ast
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).parents[1]
HTML = (ROOT / "app" / "templates" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / 'app'))
from reprocess_cache import youtube_identity
import process_manager


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


class QueuedYouTubePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.library=self.root/'library';self.library.mkdir();self.output=self.root/'output'
        self.url='https://youtu.be/abcdefghijk';self.title='Artista - Música'
        self.meta={'youtube_url':self.url,'source_type':'youtube','input_ext':'.mp4',
                   'original_filename':'Vídeo do YouTube','has_bg':True,'bg_ext':'.png','lyrics_text':'Guia'}
        (self.cache/'cache_meta.json').write_text(json.dumps(self.meta))
        (self.cache/'original_bg.png').write_bytes(b'background')
        (self.cache/'lyrics_guide.txt').write_text('Guia')
        self.state={'original_filename':'Vídeo do YouTube','status':'processing'}
        self.updates=[]
        def update(status,step,progress,**options):
            self.updates.append((status,step,options));self.state.update(status=status,**options)
        def download(url,cache_dir,**callbacks):
            callbacks['cancel_callback']();callbacks['progress_callback'](45,'Transferindo')
            media=Path(cache_dir)/'original_input.webm';media.write_bytes(b'complete media')
            return str(media),self.title
        self.download=Mock(side_effect=download);self.subtitle=Mock()
        self.scope=dict(os=os,json=json,shutil=shutil,time=time,logger=logging.getLogger('youtube-queue-test'),
            processing_lock=threading.Lock(),state_lock=threading.Lock(),state=self.state,
            get_user_paths=lambda _:dict(cache=str(self.cache),output=str(self.output),library=str(self.library)),
            get_notification_targets=lambda _:[],load_stage_checkpoints=lambda _:dict(completed_stages={}),
            persist_active_processing_seconds=lambda _,value:value,
            load_external_url_config=lambda:{},notify_targets=Mock(),telegram_notice=lambda *args:args,
            telegram_escape=str,update_state=update,update_process_summary=Mock(),
            update_queued_source=Mock(),youtube_identity=youtube_identity,download_youtube=self.download,
            run_subtitle_srt_pipeline=self.subtitle,StagePauseRequested=type('StagePauseRequested',(Exception,),{}))
        function=next(node for node in ast.parse(MAIN).body if isinstance(node,ast.FunctionDef) and node.name=='run_pipeline')
        exec(compile(ast.Module(body=[function],type_ignores=[]),'youtube-pipeline','exec'),self.scope)
        self.addCleanup(process_manager.cancel_event.clear)

    def run_pipeline(self,save=True):
        self.scope['run_pipeline'](input_audio_path=str(self.cache/'original_input.mp4'),
            youtube_url=self.url,owner_user={'username':'alice','role':'user'},subtitle_only=True,
            save_to_library=save,input_bg_path=str(self.cache/'original_bg.png'))

    def test_worker_downloads_then_preserves_inputs_saves_library_and_persists_real_path(self):
        self.run_pipeline()
        self.download.assert_called_once();self.subtitle.assert_called_once()
        media=str(self.cache/'original_input.webm')
        self.assertEqual(self.subtitle.call_args.kwargs['input_media_path'],media)
        self.assertEqual(self.subtitle.call_args.kwargs['orig_name'],self.title)
        self.scope['update_queued_source'].assert_called_once_with(str(self.cache),media,self.title)
        self.scope['update_process_summary'].assert_called_once_with(title=self.title)
        meta=json.loads((self.cache/'cache_meta.json').read_text())
        self.assertEqual(meta['input_ext'],'.webm');self.assertEqual(meta['download_quality_version'],2)
        self.assertEqual(meta['lyrics_text'],'Guia');self.assertTrue(meta['has_bg'])
        self.assertEqual((self.cache/'original_bg.png').read_bytes(),b'background')
        self.assertEqual((self.cache/'lyrics_guide.txt').read_text(),'Guia')
        self.assertEqual((self.library/'videos'/(self.title+'.webm')).read_bytes(),b'complete media')
        self.assertTrue(any(step=='Downloading YouTube' and opts.get('stage_progress')==45 for _,step,opts in self.updates))
        self.assertFalse(self.scope['processing_lock'].locked())

    def test_cached_transfer_is_reused_and_save_to_library_can_be_disabled(self):
        self.meta.update(original_filename=self.title,input_ext='.webm',download_quality_version=2)
        (self.cache/'cache_meta.json').write_text(json.dumps(self.meta))
        (self.cache/'original_input.webm').write_bytes(b'cached media')
        self.run_pipeline(save=False)
        self.download.assert_not_called();self.subtitle.assert_called_once()
        self.assertEqual(self.subtitle.call_args.kwargs['orig_name'],self.title)
        self.assertFalse((self.library/'videos').exists())
        self.assertTrue((self.cache/'original_bg.png').is_file())

    def test_failed_or_canceled_transfer_preserves_the_source_and_does_not_render(self):
        for error in [RuntimeError('YouTube indisponível'),InterruptedError('Cancelado pelo usuário.')]:
            with self.subTest(error=error):
                self.download.side_effect=error;self.run_pipeline()
                self.subtitle.assert_not_called()
                self.assertFalse(self.scope['processing_lock'].locked())
                self.assertEqual(json.loads((self.cache/'cache_meta.json').read_text())['youtube_url'],self.url)
                self.assertTrue((self.cache/'original_bg.png').is_file())
                self.assertEqual(self.state['status'],'idle' if isinstance(error,InterruptedError) else 'error')

    def test_incomplete_media_without_a_completed_download_marker_is_not_reused(self):
        (self.cache/'original_input.mp4').write_bytes(b'incomplete download')
        self.run_pipeline(save=False)
        self.download.assert_called_once();self.subtitle.assert_called_once()


if __name__ == "__main__":
    unittest.main()
