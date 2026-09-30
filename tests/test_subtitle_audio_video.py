import ast
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from subtitle_video import media_has_motion_video, render_audio_subtitle_video


class AudioSubtitleVideoTests(unittest.TestCase):
    def test_attached_album_cover_is_audio_not_motion_video(self):
        with patch('subtitle_video.subprocess.run', return_value=Mock(stdout=json.dumps({'streams':[
            {'codec_type':'audio'}, {'codec_type':'video','disposition':{'attached_pic':1}}]}))):
            self.assertFalse(media_has_motion_video('music.mp3'))
        with patch('subtitle_video.subprocess.run', return_value=Mock(stdout=json.dumps({'streams':[
            {'codec_type':'video','disposition':{'attached_pic':0}}]}))):
            self.assertTrue(media_has_motion_video('video.mkv'))

    def test_ffmpeg_creates_mp4_with_audio_and_visible_subtitles(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); audio=root/'audio.wav'; captions=root/"a ' caption.srt"; video=root/'final.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1','-y',str(audio)],check=True)
            captions.write_text('1\n00:00:00,000 --> 00:00:01,000\nOlá, Victor!\n',encoding='utf-8')
            def runner(command, **kwargs):
                subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE);return True
            render_audio_subtitle_video(audio,captions,video,1,runner=runner)
            self.assertTrue(media_has_motion_video(video))
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
            self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
            self.assertAlmostEqual(float(info['format']['duration']),1,delta=.1)
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-ss','0.5','-frames:v','1','-f','rawvideo','-pix_fmt','gray','-'])
            self.assertGreater(max(raw),180, 'White subtitle text must be rendered on the dark background')
            self.assertFalse((root/'final.rendering.mp4').exists())

    def test_pipeline_keeps_srt_and_sends_video_only_for_audio(self):
        source=(ROOT/'app/main.py').read_text(); tree=ast.parse(source)
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_subtitle_srt_pipeline')
        for has_video in (False,True):
            with self.subTest(has_video=has_video), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); cache=root/'cache'; cache.mkdir(); output=root/'out'; library=root/'library'; (library/'history').mkdir(parents=True)
                (cache/'subtitle_source.mp3').write_bytes(b'audio')
                (cache/'subtitle_segments_original.json').write_text(json.dumps([{'start':0,'end':1,'text':'Hello'}]))
                (cache/'subtitle_info_original.json').write_text(json.dumps({'language':'en','cache_signature':{'whisper_model':'medium','enable_vad':True,'transcription_preset':'standard'}}))
                def save_srt(path,*args):shutil.copy2(path,library/'history'/'original.srt');return 'original.srt'
                def render(audio,subtitles,destination,*args,**kwargs):
                    kwargs['progress_callback'](50);kwargs['progress_callback'](100)
                    Path(destination).write_bytes(b'video')
                def save_video(path,*args):shutil.copy2(path,library/'history'/'video.mp4');return 'video.mp4'
                state=Mock();documents=Mock();videos=Mock();metadata=Mock()
                ns={'os':os,'json':json,'shutil':shutil,'logger':logging.getLogger('test'),
                    'get_file_duration':lambda path:1,'stage_checkpoint':lambda *args:{},'save_stage_checkpoint':Mock(),
                    'notify_targets':Mock(),'telegram_notice':lambda *parts:' '.join(parts),'telegram_escape':str,
                    'update_state':state,'cover_full_media_timeline':lambda segments,duration:segments,
                    'write_srt':lambda segments,path:Path(path).write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n'),
                    'save_srt_result':save_srt,'create_public_download':lambda owner,name:name+'-token',
                    'media_has_motion_video':lambda path:has_video,'render_audio_subtitle_video':render,
                    'save_video_to_history':save_video,'save_result_metadata':metadata,'send_documents_to_targets':documents,'send_video_to_targets':videos}
                exec(compile(ast.Module(body=[function],type_ignores=[]),'pipeline','exec'),ns)
                with patch('process_manager.check_cancelled'):
                    ns['run_subtitle_srt_pipeline']('source', 'song','medium',True,'standard',False,'original',{'username':'owner'},str(cache),str(output),str(library),[])
                self.assertEqual(state.call_args.kwargs['result_kind'],'subtitles' if has_video else 'subtitle_video')
                self.assertEqual(videos.call_count,0 if has_video else 1)
                if not has_video:
                    self.assertTrue(any(c.kwargs.get('stage_progress')==50 for c in state.call_args_list))
                    self.assertTrue(any(c.kwargs.get('stage_progress')==100 for c in state.call_args_list))
                    notices = [c for c in ns['notify_targets'].call_args_list if 'Vídeo legendado do áudio' in c.args[1]]
                    self.assertEqual(len(notices), 1)
                self.assertEqual(documents.call_args.args[1][0]['public_download_token'],'original.srt-token')
                self.assertTrue((library/'history'/'original.srt').is_file())
                self.assertEqual(metadata.call_args.args[2],'original.srt' if has_video else 'video.mp4')
