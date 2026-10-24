"""Exercise the end of real audio/video streams, including interrupted output."""
import json
import ast
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1]/'app'))
from video_renderer import render_karaoke_video
from audio_processor import extract_audio
from media_integrity import complete_audio_cache, invalidate_audio_derivatives, media_durations, require_duration
import process_manager as pm
from test_automatic_lyrics_and_search import load_function
from subtitle_video import render_subtitle_video
from youtube_download_access import DownloadAccessError


class CompleteSongTests(unittest.TestCase):
    def test_srt_video_keeps_the_original_duration_when_audio_ends_before_the_picture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.mp4';captions=root/'captions.srt';output=root/'result.mp4'
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=160x90:d=4',
                '-f','lavfi','-i','sine=duration=1','-c:v','libx264','-c:a','aac',str(source)],check=True)
            captions.write_text('1\n00:00:02,000 --> 00:00:03,800\nComplete timeline\n')
            render_subtitle_video(str(source),str(captions),str(output),4)
            require_duration(output,4,kinds=('audio','video'))

    def test_youtube_partial_download_is_retried_and_never_left_as_an_accepted_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/'cache';cache.mkdir();full=root/'full.wav';short=root/'short.wav'
            for path,duration in ((full,4),(short,1)):
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=duration={duration}',str(path)],check=True)
            guide=cache/'lyrics_guide.txt';guide.write_text('Preserved guide')
            options=load_function('youtube_download_options',YtDlpLogAdapter=Mock)
            calls=[]
            def transfer(module,url,selected):
                self.assertIs(selected['skip_unavailable_fragments'],False)
                calls.append(selected)
                shutil.copy2(short if len(calls)==1 else full,cache/'original_input.wav')
                return {'title':'Complete song','duration':4}
            downloader=load_function('download_youtube',os=os,yt_dlp_operation_lock=threading.Lock(),
                load_yt_dlp=lambda:object(),youtube_download_options=options,extract_youtube_info=transfer,
                find_downloaded_file=load_function('find_downloaded_file',os=os),
                DownloadAccessError=DownloadAccessError,media_durations=media_durations,require_duration=require_duration)
            path,title=downloader('https://youtu.be/abcdefghijk',str(cache))
            self.assertEqual(len(calls),2);self.assertEqual(title,'Complete song');require_duration(path,4)
            self.assertEqual(guide.read_text(),'Preserved guide')
            def always_partial(*args):
                shutil.copy2(short,cache/'original_input.wav')
                return {'duration':4}
            downloader.__globals__['extract_youtube_info']=always_partial
            with self.assertRaisesRegex(RuntimeError,'Resultado incompleto'):
                downloader('https://youtu.be/abcdefghijk',str(cache))
            self.assertEqual(list(cache.glob('original_input.*')),[])
            self.assertEqual(guide.read_text(),'Preserved guide')

    def test_original_video_ending_early_keeps_frames_through_the_end_of_the_song(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, instrumental, result = root/'source.mp4', root/'instrumental.wav', root/'result.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:s=160x90:r=25:d=1',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', str(instrumental)], check=True)
            captions = root/'captions.srt'
            captions.write_text('1\n00:00:02,500 --> 00:00:03,800\nEnd of the complete song\n')
            render_karaoke_video(str(instrumental), str(captions), str(result), original_video_path=str(source),
                background_mode='original_video', cover_title='Complete song')
            media = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(result)]))
            for stream_type in ('audio', 'video'):
                stream = next(item for item in media['streams'] if item['codec_type'] == stream_type)
                self.assertAlmostEqual(float(stream['duration']), 7, delta=.15, msg=stream_type+' must include the whole song and cover')
            frame = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', '6.2', '-i', str(result),
                '-frames:v', '1', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'])
            self.assertGreater(max(frame), 200, 'Late lyrics must keep advancing after the original video ends')

    def test_successful_ffmpeg_exit_with_a_short_stream_cannot_replace_a_good_result(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio, partial, final = root/'audio.wav', root/'partial.mp4', root/'final.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=duration=4', str(audio)], check=True)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:s=160x90:d=1',
                '-f', 'lavfi', '-i', 'sine=duration=4', '-c:v', 'libx264', '-c:a', 'aac', str(partial)], check=True)
            final.write_bytes(b'previous complete result')
            with patch('video_renderer.run_ffmpeg_with_logging', side_effect=lambda command, **_:shutil.copy2(partial,command[-1])):
                with self.assertRaisesRegex(RuntimeError, 'Resultado incompleto'):
                    render_karaoke_video(str(audio), '', str(final), background_mode='solid_black')
            self.assertEqual(final.read_bytes(), b'previous complete result')
            self.assertEqual(list(root.glob('.karaoke-*')), [])

    def test_partial_audio_cache_is_rebuilt_without_erasing_the_guide_or_human_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cache = root/'cache'; cache.mkdir()
            original, short = root/'original.wav', root/'short.wav'
            for path, duration in ((original, 4), (short, 1)):
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'sine=duration={duration}', str(path)], check=True)
            for name in ('original_converted.wav', 'vocals.wav', 'instrumental.wav'):
                shutil.copy2(short,cache/name)
            preserved = {'lyrics_guide.txt':'Complete guide', 'reviewed_segments.json':'[{"text":"Confirmed manually"}]'}
            for name, content in {**preserved,'transcribed_segments.json':'[]','guided_whisper_lyrics.json':'{}'}.items():
                (cache/name).write_text(content)
            (cache/'stage_checkpoints.json').write_text(json.dumps({'completed_stages':{
                'transcription_reviewed':{},'subtitles_generated':{},'video_rendered':{}}}))
            def separate(converted, output, **kwargs):
                voice, music = Path(output)/'voice.wav', Path(output)/'music.wav'
                shutil.copy2(converted,voice); shutil.copy2(converted,music)
                return str(voice), str(music)
            extraction, separation = Mock(wraps=extract_audio), Mock(side_effect=separate)
            pipeline = next(node for node in ast.parse((Path(__file__).parents[1]/'app/main.py').read_text()).body
                if isinstance(node,ast.FunctionDef) and node.name=='run_pipeline')
            stage = next(node for node in ast.walk(pipeline) if isinstance(node,ast.With)
                and any(isinstance(item.optional_vars,ast.Name) and item.optional_vars.id=='tmpdir' for item in node.items))
            body = stage.body[:next(index for index,node in enumerate(stage.body)
                if isinstance(node,ast.FunctionDef) and node.name=='publish_render_progress')]
            scope = dict(logger=logging.getLogger('complete-song'),cache_dir=str(cache),input_audio_path=str(original),
                tmpdir=folder,os=os,shutil=shutil,tempfile=tempfile,pm=pm,telegram_targets=[],
                keep_backing_vocals=False,transcribe_source='original',update_state=Mock(),notify_targets=Mock(),
                telegram_notice=lambda *args:args,save_stage_checkpoint=Mock(),extract_audio=extraction,
                separate_vocals=separation,media_durations=media_durations,require_duration=require_duration,
                complete_audio_cache=complete_audio_cache,invalidate_audio_derivatives=invalidate_audio_derivatives)
            code = compile(ast.Module(body=body,type_ignores=[]),'audio-stage','exec')
            pm.cancel_event.clear(); exec(code,scope)
            self.assertEqual(extraction.call_count,1);self.assertEqual(separation.call_count,1)
            for name in ('original_converted.wav','vocals.wav','instrumental.wav'):
                require_duration(cache/name,4)
            for name,content in preserved.items():self.assertEqual((cache/name).read_text(),content)
            self.assertFalse((cache/'guided_whisper_lyrics.json').exists())
            self.assertFalse((cache/'transcribed_segments.json').exists())
            checkpoints = json.loads((cache/'stage_checkpoints.json').read_text())['completed_stages']
            self.assertIn('transcription_reviewed',checkpoints);self.assertNotIn('video_rendered',checkpoints)
            exec(code,scope)
            self.assertEqual(extraction.call_count,1);self.assertEqual(separation.call_count,1)
