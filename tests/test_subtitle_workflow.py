"""Captioning defaults, translation selection, rendering and Telegram delivery."""
import ast
import html
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
from subtitle_settings import load_subtitle_settings, normalize_subtitle_settings, save_subtitle_settings
from subtitle_video import render_subtitle_video
from test_automatic_lyrics_and_search import load_function, HTTPError


class SubtitleSettingsTests(unittest.TestCase):
    def test_separate_defaults_and_saved_original_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'defaults.json')
            self.assertEqual(load_subtitle_settings(path)['video_subtitle_source'], 'translated')
            save_subtitle_settings(path, {'video_subtitle_source':'original', 'text_color':'#ffcc00',
                                        'background_file':'fundo.mp4', 'background_owner':'admin'})
            result = load_subtitle_settings(path)
            self.assertEqual(result['video_subtitle_source'], 'original')
            self.assertEqual(result['text_color'], '#FFCC00')
            self.assertEqual(result['background_owner'], 'admin')
            self.assertEqual(list(Path(directory).glob('.subtitle-settings-*')), [])

    def test_invalid_visuals_and_paths_do_not_reach_ffmpeg(self):
        settings = normalize_subtitle_settings({'text_color':"red,evil=1", 'box_opacity':200,
            'background_file':'../other.mp4', 'font_size':0, 'text_position':'left'})
        self.assertEqual(settings['text_color'], '#FFFFFF')
        self.assertEqual(settings['box_opacity'], 100)
        self.assertEqual(settings['font_size'], 12)
        self.assertEqual(settings['background_file'], '')
        self.assertEqual(settings['text_position'], 'bottom')

    def test_only_admin_can_change_global_defaults(self):
        guard = Mock(side_effect=HTTPError(403, 'Somente administrador'))
        save = load_function('save_subtitle_mode_config', SubtitleModeModel=object,
                             require_admin=guard, save_subtitle_settings=Mock())
        with self.assertRaises(HTTPError): save({}, {'role':'user'})
        save.__globals__['save_subtitle_settings'].assert_not_called()

    def test_background_owner_is_not_exposed(self):
        get = load_function('get_subtitle_mode_config', load_subtitle_settings=lambda _:
            {'background_owner':'admin', 'background_file':'fundo.mp4'}, SUBTITLE_MODE_FILE='settings')
        self.assertNotIn('background_owner', get({'role':'user'}))


class SubtitlePipelineTests(unittest.TestCase):
    def run_pipeline(self, preference='translated', target='pt-BR', failed=False, checkpoint=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        cache = root / 'cache'; cache.mkdir()
        output = root / 'output'; output.mkdir()
        history = root / 'library/history'; history.mkdir(parents=True)
        segments = [{'start':.3,'end':.7,'text':'Hello world'}]
        (cache / 'subtitle_segments_original.json').write_text(json.dumps(segments))
        (cache / 'subtitle_info_original.json').write_text(json.dumps({'language':'en', 'cache_signature':
            {'whisper_model':'medium','enable_vad':True,'transcription_preset':'difficult',
             'whisper_audio_version':2,'whisper_quality_mode':'max_quality'}}))
        checkpoints = {}
        if checkpoint:
            (history / 'own.srt').write_text('My own original')
            (output / 'final_subtitles_original.srt').write_text('Other task subtitles')
            checkpoints['subtitle_original_ready'] = {'filename':'own.srt'}
        def save_srt(path, title, library, language):
            name = language + '.srt'
            shutil.copy2(path, history / name)
            return name
        def translate(original, translated, **kwargs):
            if failed: raise RuntimeError('Tradução indisponível')
            Path(translated).write_text('Olá, mundo')
        rendered = []
        def render(source, subtitles, result, duration, **kwargs):
            rendered.append((Path(subtitles).read_text(), kwargs))
            Path(result).write_bytes(b'mp4')
        state = Mock(); delivery = Mock()
        pipeline = load_function('run_subtitle_srt_pipeline', os=os, json=json, shutil=shutil,
            normalize_subtitle_settings=normalize_subtitle_settings, get_file_duration=lambda _:1,
            stage_checkpoint=lambda _, stage:checkpoints.get(stage,{}), save_stage_checkpoint=Mock(),
            update_state=state, update_process_summary=Mock(), notify_targets=Mock(),
            telegram_notice=lambda *parts:' '.join(parts), telegram_escape=html.escape,
            cover_full_media_timeline=lambda segments, duration:segments,
            write_srt=lambda segments,path:Path(path).write_text(segments[0]['text']),
            save_srt_result=save_srt, translate_subtitle_file=translate,
            create_public_download=lambda owner,name:name + '-token',
            media_has_motion_video=lambda _:True, render_subtitle_video=render,
            save_video_to_history=lambda *args,**kwargs:'Video - Legendado.mp4',
            save_result_metadata=Mock(), send_video_to_targets=delivery,
            send_documents_to_targets=Mock())
        with patch('process_manager.check_cancelled'):
            pipeline('source.mp4','Lecture','medium',True,'difficult',False,target,{'username':'owner'},
                     str(cache),str(output),str(root / 'library'),[],subtitle_settings={'video_subtitle_source':preference})
        return rendered, state.call_args.kwargs, delivery, pipeline.__globals__

    def test_translated_subtitles_are_burned_by_default(self):
        rendered, state, delivery, _ = self.run_pipeline()
        self.assertEqual(rendered[0][0], 'Olá, mundo')
        self.assertEqual(state['subtitle_language'], 'pt-BR')
        self.assertEqual([d['label'] for d in delivery.call_args.kwargs['subtitle_downloads']], ['SRT original','Vídeo','SRT traduzido'])

    def test_admin_original_preference_keeps_translated_download(self):
        rendered, state, delivery, _ = self.run_pipeline(preference='original')
        self.assertEqual(rendered[0][0], 'Hello world')
        self.assertEqual(state['subtitle_language'], 'en')
        self.assertEqual(state['translated_subtitle_filename'], 'pt-BR.srt')
        self.assertEqual(len(delivery.call_args.kwargs['subtitle_downloads']), 3)

    def test_translation_failure_still_creates_video_with_original(self):
        rendered, state, delivery, scope = self.run_pipeline(failed=True)
        self.assertEqual(rendered[0][0], 'Hello world')
        self.assertEqual(state['result_kind'], 'subtitle_video')
        self.assertEqual(state['translated_subtitle_filename'], '')
        self.assertIn('indisponível', state['translation_error'])
        self.assertEqual(len(delivery.call_args.kwargs['subtitle_downloads']), 2)
        scope['send_documents_to_targets'].assert_not_called()

    def test_no_translation_uses_original_and_reports_its_language(self):
        rendered, state, _, _ = self.run_pipeline(target='original')
        self.assertEqual(rendered[0][0], 'Hello world')
        self.assertEqual(state['subtitle_language'], 'en')

    def test_resume_never_uses_another_tasks_working_srt(self):
        rendered, _, _, _ = self.run_pipeline(target='original', checkpoint=True)
        self.assertEqual(rendered[0][0], 'My own original')


class SubtitleRenderingTests(unittest.TestCase):
    def test_real_original_video_image_audio_duration_and_style(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source.mp4'; result = root / 'captioned.mp4'
            srt = root / 'text.srt'; srt.write_text('1\n00:00:00,400 --> 00:00:01,200\nLegenda traduzida\n')
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=blue:s=320x180:r=25:d=2',
                '-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-c:a','aac',str(source)],check=True)
            commands = []
            def runner(command, **kwargs):
                commands.append(command)
                subprocess.run(command,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                return True
            render_subtitle_video(source,srt,result,2,runner=runner,settings={'text_color':'#FF0000','box_opacity':70})
            info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(result)]))
            video=next(s for s in info['streams'] if s['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(320,180))
            self.assertTrue(any(s['codec_type']=='audio' for s in info['streams']))
            self.assertAlmostEqual(float(info['format']['duration']),2,delta=.1)
            self.assertEqual(commands[0][commands[0].index('-map')+1], '0:v:0')
            self.assertNotIn('-ss',commands[0])
            frame=subprocess.check_output(['ffmpeg','-v','error','-ss','0.7','-i',str(result),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
            pixels=list(zip(frame[::3],frame[1::3],frame[2::3]))
            self.assertGreater(sum(b>180 and r<50 for r,g,b in pixels), 320*180*.5)
            self.assertGreater(sum(r>150 and g<100 and b<100 for r,g,b in pixels), 30)

    def test_audio_background_never_supplies_the_audio_track(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); srt=root/'s.srt';srt.write_text('1\n00:00:00,000 --> 00:00:02,000\nText\n')
            background=root/'bg.mp4';background.write_bytes(b'background')
            def runner(command,**kwargs):
                self.assertIn('-stream_loop',command)
                maps=[command[i+1] for i,value in enumerate(command) if value=='-map']
                self.assertEqual(maps,['1:v:0','0:a:0'])
                Path(command[-1]).write_bytes(b'mp4')
                return True
            with patch('subtitle_video.media_has_motion_video',side_effect=[False,True]):
                render_subtitle_video('speech.wav',srt,root/'result.mp4',2,runner=runner,background=background)


class SubtitleTelegramTests(unittest.TestCase):
    def test_owner_and_admin_share_one_preview_encoding(self):
        delivered=[]
        def compress(source,destination,*args,**kwargs):
            Path(destination).write_bytes(b'preview');return True
        encode=Mock(side_effect=compress)
        def send(**kwargs):
            path=kwargs['prepared_preview']
            self.assertEqual(Path(path).read_bytes(),b'preview')
            delivered.append(path)
        delivery=load_function('send_video_to_targets',tempfile=tempfile,os=os,update_state=Mock(),
            compress_video_for_telegram=encode,send_telegram_video_flow=send)
        delivery([{'telegram_token':'one','telegram_chat_id':'owner'},
                  {'telegram_token':'two','telegram_chat_id':'admin'}], 'original.mp4','Speech','Speech.mp4',
                 'token','http://local','https://remote',subtitle_downloads=[])
        encode.assert_called_once()
        self.assertEqual(delivered[0],delivered[1])
        self.assertFalse(Path(delivered[0]).exists())

    def setup_flow(self, compression=True, request_error=False):
        posts=[]
        def post(url, **kwargs):
            if request_error: raise RuntimeError('network')
            posts.append((url,kwargs['data'],kwargs['files']['video'][1].read()))
            return Mock(status_code=200)
        def compress(source,destination,target,**kwargs):
            self.assertEqual(kwargs['max_video_kbps'],1800)
            Path(destination).write_bytes(b'compressed')
            return compression
        fallback=Mock(return_value=True)
        flow=load_function('send_telegram_video_flow', os=os,tempfile=tempfile,
            format_processing_duration=lambda _: '1 min',telegram_escape=lambda x:html.escape(str(x),quote=True),
            telegram_notice=lambda icon,title,*parts:title+'\n'+'\n'.join(parts),update_state=Mock(),
            compress_video_for_telegram=compress,requests=Mock(post=post),_send_telegram_notification_worker=fallback)
        return flow,posts,fallback

    def deliver(self,flow,root):
        full=root/'full.mp4';full.write_bytes(b'original')
        return flow('bot','chat',str(full),'A <speech>','full.mp4','video-token',
            'http://192.168.1.2:7860','https://example.org',42,
            subtitle_downloads=[{'label':label,'public_download_token':token} for label,token in
                                [('SRT original','original-token'),('Vídeo','video-token'),('SRT traduzido','translated-token')]],
            embedded_subtitle='tradução (pt-BR)')

    def test_one_compressed_attachment_with_all_six_links(self):
        flow,posts,fallback=self.setup_flow()
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(self.deliver(flow,Path(directory)))
            self.assertEqual((Path(directory)/'full.mp4').read_bytes(),b'original')
        self.assertEqual(len(posts),1)
        url,data,body=posts[0]
        self.assertTrue(url.endswith('/sendVideo'))
        self.assertEqual(body,b'compressed')
        self.assertEqual(data['caption'].count('<a href='),6)
        self.assertIn('Vídeo legendado concluído',data['caption'])
        self.assertNotIn('Karaokê',data['caption'])
        self.assertIn('A &lt;speech&gt;',data['caption'])
        fallback.assert_not_called()

    def test_failure_keeps_all_download_links_in_fallback(self):
        for compression,error in ((False,False),(True,True)):
            with self.subTest(compression=compression,error=error), tempfile.TemporaryDirectory() as directory:
                flow,_,fallback=self.setup_flow(compression, error)
                self.assertTrue(self.deliver(flow,Path(directory)))
                self.assertEqual(fallback.call_args.args[2].count('<a href='),6)

    def test_compression_cancel_is_propagated_without_sending_a_completion(self):
        flow,posts,fallback=self.setup_flow()
        flow.__globals__['compress_video_for_telegram']=Mock(side_effect=InterruptedError('cancelled'))
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(InterruptedError):
            self.deliver(flow,Path(directory))
        self.assertEqual(posts,[])
        fallback.assert_not_called()

    def test_real_two_pass_preview_preserves_duration_and_full_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);full=root/'full.mp4';preview=root/'preview.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=640x360:r=25:d=3',
                '-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-crf','16','-c:a','aac',str(full)],check=True)
            original=full.read_bytes();progress=[]
            compress=load_function('compress_video_for_telegram',os=os,tempfile=tempfile,get_file_duration=lambda _:3)
            self.assertTrue(compress(str(full),str(preview),128*1024,max_video_kbps=1800,progress_callback=progress.append))
            self.assertEqual(full.read_bytes(),original)
            self.assertLessEqual(preview.stat().st_size,128*1024)
            duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(preview)]))
            self.assertAlmostEqual(duration,3,delta=.1)
            self.assertIn(0,progress);self.assertIn(100,progress)
