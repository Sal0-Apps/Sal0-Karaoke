"""Draft editing and background downloading cannot alter other queued jobs."""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'app'))
from lyric_drafts import read_draft, write_draft, clear_draft
from subtitle_settings import load_subtitle_settings
from test_automatic_lyrics_and_search import load_function
from test_easy_mode_config import load_normalizer


class QueueLyricsTests(unittest.TestCase):
    def test_save_and_clear_only_affect_the_selected_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'saved_lyrics.txt').write_text('Processing legacy text')
            write_draft(directory,'upload:A','Guide A')
            snapshot=json.loads(json.dumps({'pipeline':{'lyrics_text':read_draft(directory,'upload:A')['lyrics_text']}}))
            write_draft(directory,'upload:B','Guide B')
            clear_draft(directory,'upload:B')
            self.assertEqual(read_draft(directory,'upload:A')['lyrics_text'],'Guide A')
            self.assertEqual(read_draft(directory,'upload:B')['lyrics_text'],'')
            self.assertEqual(snapshot['pipeline']['lyrics_text'],'Guide A')
            write_draft(directory,'upload:A','Changed after enqueue')
            self.assertEqual(snapshot['pipeline']['lyrics_text'],'Guide A')
            self.assertEqual((root/'saved_lyrics.txt').read_text(),'Processing legacy text')

    def test_drafts_for_different_users_and_same_filename_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            first=str(Path(directory)/'first');second=str(Path(directory)/'second')
            write_draft(first,'library:same.mp4','First user')
            write_draft(second,'library:same.mp4','Second user')
            clear_draft(first,'library:same.mp4')
            self.assertEqual(read_draft(second,'library:same.mp4')['lyrics_text'],'Second user')

    def test_concurrent_source_saves_do_not_lose_either_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            threads=[threading.Thread(target=write_draft,args=(directory,f'source:{i}',f'Guide {i}')) for i in range(10)]
            for thread in threads:thread.start()
            for thread in threads:thread.join()
            self.assertEqual([read_draft(directory,f'source:{i}')['lyrics_text'] for i in range(10)], [f'Guide {i}' for i in range(10)])

    def make_submitter(self,root):
        paths={key:str(root/key) for key in ('cache','library','output')}
        for key in paths:Path(paths[key]).mkdir()
        for folder in ('videos','photos','history'):(Path(paths['library'])/folder).mkdir()
        jobs=[]
        def enqueue(job):jobs.append(json.loads(json.dumps(job)));return len(jobs)
        _,normalize=load_normalizer()
        submit=load_function('process_karaoke', Form=lambda value:value, File=lambda value:value, UploadFile=object,
            youtube_publisher=SimpleNamespace(publication_options=lambda *args:None),ensure_processing_queue_access=Mock(),ensure_processing_queue_capacity=Mock(),
            normalize_translation_language=lambda x:x,SUPPORTED_TARGET_LANGUAGES={'original','pt-BR'},
            get_user_paths=lambda _:paths,uuid=uuid,os=os,json=json,shutil=shutil,time=time,
            PROCESSING_QUEUE_ROOT=str(root/'jobs'),enqueue_processing_job=enqueue,
            load_easy_mode_config=lambda:normalize({'background_mode':'original'}),
            SUBTITLE_MODE_FILE=str(root/'srt.json'),load_subtitle_settings=load_subtitle_settings,
            stage_subtitle_background=Mock(return_value=None))
        return submit,jobs

    def test_selected_automatic_guide_survives_quick_defaults_and_queue_serialization(self):
        with tempfile.TemporaryDirectory() as directory:
            submit,jobs=self.make_submitter(Path(directory))
            for title,guide in (('A.mp4','Guide A'),('B.mp4','Guide B')):
                submit(current_user={'username':'owner','role':'user'},
                    audio_file=SimpleNamespace(filename=title,file=io.BytesIO(b'media')),
                    easy_mode=True,lyrics_text=guide,lyrics_mode='auto',lyrics_selected=True,
                    lyrics_source_key='upload:'+title)
            self.assertEqual([job['pipeline']['lyrics_text'] for job in jobs],['Guide A','Guide B'])
            self.assertTrue(all(job['pipeline']['lyrics_mode']=='manual' for job in jobs))
            self.assertNotEqual(jobs[0]['pipeline']['cache_dir'],jobs[1]['pipeline']['cache_dir'])
            self.assertEqual(Path(jobs[0]['pipeline']['cache_dir'],'lyrics_guide.txt').read_text(),'Guide A')

    def test_subtitle_settings_are_snapshotted_at_enqueue_and_background_is_staged_after_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);submit,jobs=self.make_submitter(root)
            (root/'srt.json').write_text(json.dumps({'text_color':'#FF0000'}))
            def stage(settings,cache):
                path=Path(cache)/'subtitle_background.png';path.write_bytes(b'picture');return str(path)
            submit.__globals__['stage_subtitle_background']=stage
            submit(current_user={'username':'owner','role':'user'},audio_file=SimpleNamespace(filename='speech.mp4',file=io.BytesIO(b'media')),
                   subtitle_only=True,lyrics_text='not karaoke',translation_language='original')
            (root/'srt.json').write_text(json.dumps({'text_color':'#00FF00'}))
            job=jobs[0]['pipeline']
            self.assertEqual(job['subtitle_settings']['text_color'],'#FF0000')
            self.assertEqual(Path(job['subtitle_background_path']).read_bytes(),b'picture')
            self.assertEqual(job['lyrics_text'],'')
            self.assertEqual(jobs[0]['process_summary']['mode'],'Legendar vídeo')

    def test_default_original_and_explicit_vocal_sources_are_snapshotted_per_job(self):
        with tempfile.TemporaryDirectory() as directory:
            submit,jobs=self.make_submitter(Path(directory))
            def enqueue(title, **options):
                submit(current_user={'username':'owner','role':'user'},
                    audio_file=SimpleNamespace(filename=title,file=io.BytesIO(b'media')),
                    keep_backing_vocals=True, **options)
            enqueue('quick.mp4', easy_mode=True, transcribe_source='vocals')
            enqueue('default.mp4')
            enqueue('explicit.mp4', transcribe_source='vocals')
            self.assertEqual([job['pipeline']['transcribe_source'] for job in jobs],
                             ['original','original','vocals'])
            self.assertTrue(all(job['pipeline']['keep_backing_vocals'] for job in jobs))
            self.assertIn('Áudio original', jobs[0]['process_summary']['model'])
            self.assertIn('Voz principal isolada', jobs[2]['process_summary']['model'])


class BackgroundDownloadTests(unittest.TestCase):
    def test_running_job_does_not_block_background_download(self):
        statuses={};thread=Mock()
        start=load_function('download_bg_youtube_preset',YouTubePresetModel=object,
            processing_lock=Mock(locked=lambda:True),uuid=uuid,yt_preset_statuses=statuses,
            youtube_status_key=lambda user,kind:user['username']+':'+kind,
            threading=SimpleNamespace(Thread=thread),run_bg_youtube_download_bg=Mock())
        result=start(SimpleNamespace(youtube_url='https://youtu.be/abcdefghijk'),{'username':'owner'})
        self.assertEqual(result['status'],'started')
        self.assertEqual(len(result['download_id']),32)
        self.assertEqual(thread.call_args.kwargs['args'][2],result['download_id'])
        thread.return_value.start.assert_called_once()

    def test_temporary_files_status_and_cancel_are_independent_of_the_active_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);cache=root/'cache';cache.mkdir();output=root/'output';output.mkdir()
            (cache/'bg_yt_raw.mp4').write_bytes(b'active background')
            (cache/'analysis.json').write_text('active analysis')
            statuses={'owner:background':{'download_id':'second'}}
            def download(url,staging):
                self.assertNotEqual(staging,str(cache))
                raw=Path(staging)/'bg_yt_no_audio.mp4';raw.write_bytes(url.encode());return str(raw),'Same title'
            worker=load_function('run_bg_youtube_download_bg',os=os,tempfile=tempfile,uuid=uuid,shutil=shutil,
                get_user_paths=lambda _:{'cache':str(cache),'output':str(output),'library':str(root/'library')},
                yt_preset_statuses=statuses,youtube_status_key=lambda *args:'owner:background',download_bg_youtube=download)
            worker('first video',{'username':'owner'},'first')
            self.assertEqual(statuses['owner:background']['download_id'],'second')
            worker('second video',{'username':'owner'},'second')
            first=statuses['owner:background:first'];second=statuses['owner:background:second']
            self.assertEqual((first['status'],second['status']),('done','done'))
            self.assertNotEqual(first['filename'],second['filename'])
            self.assertEqual((root/'library/photos'/first['filename']).read_bytes(),b'first video')
            self.assertEqual((root/'library/photos'/second['filename']).read_bytes(),b'second video')
            self.assertEqual((cache/'bg_yt_raw.mp4').read_bytes(),b'active background')
            self.assertEqual((cache/'analysis.json').read_text(),'active analysis')
            self.assertEqual(list(output.glob('background-download-*')),[])
