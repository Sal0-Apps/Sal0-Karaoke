"""Exercise retained batches through the actual authenticated routes, without AI models."""
import ast
import copy
import io
import json
import logging
import mimetypes
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
from unittest.mock import Mock, patch

from fastapi import FastAPI, Depends, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'app'))
import queue_cache
from processing_validation import validate_processing_options, validate_review_segments, canonical_review_segments
from reprocess_cache import copy_reusable_inputs, youtube_identity
from subtitle_settings import load_subtitle_settings, normalize_subtitle_settings
from lyric_guide import prepare_lyrics_guide


class ImmediateThread:
    def __init__(self, target, args=(), **kwargs): self.target, self.args = target, args
    def start(self): self.target(*self.args)


class QueueCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.user = {'username':'alice','role':'user'}
        app=FastAPI()
        def user(): return dict(self.user)
        self.scope=dict(app=app, BaseModel=BaseModel, Depends=Depends, File=File, Form=Form, UploadFile=UploadFile,
            HTTPException=HTTPException, FileResponse=FileResponse, Response=Response,
            get_current_user=user, is_admin=lambda u:u.get('role')=='admin',
            get_user_paths=self.paths, queue_cache=queue_cache, canonical_review_segments=canonical_review_segments,
            validate_processing_options=validate_processing_options,validate_review_segments=validate_review_segments,
            os=os,json=json,shutil=shutil,time=time,uuid=uuid,mimetypes=mimetypes,
            logger=logging.getLogger('queue-cache-tests'),
            threading=SimpleNamespace(Thread=ImmediateThread),
            processing_queue=[],processing_queue_lock=threading.RLock(),processing_queue_event=threading.Event(),
            processing_queue_paused=False,ACTIVE_QUEUE_STATUSES=queue_cache.ACTIVE,
            legacy_cache_promotion_lock=threading.RLock(),
            PROCESSING_QUEUE_FILE=str(self.root/'queue.json'),PROCESSING_QUEUE_ROOT=str(self.root/'jobs'),
            ensure_processing_queue_access=Mock(), normalize_translation_language=lambda v:v,
            SUPPORTED_TARGET_LANGUAGES={'pt-BR','original'}, prepare_lyrics_guide=prepare_lyrics_guide,
            copy_reusable_inputs=copy_reusable_inputs,youtube_identity=youtube_identity,
            youtube_publisher=SimpleNamespace(publication_options=lambda *args,**kwargs:None,replacement_for=lambda _:None),
            SUBTITLE_MODE_FILE=str(self.root/'subtitles.json'),load_subtitle_settings=load_subtitle_settings,
            normalize_subtitle_settings=normalize_subtitle_settings, stage_subtitle_background=Mock(return_value=None),
            check_has_video=lambda p:str(p).endswith('.mp4'),get_random_default_background=lambda:None)
        names={'save_processing_queue_unlocked','load_processing_queue','public_queue_job','enqueue_processing_job',
            'retire_queue_batch','ensure_processing_queue_capacity','active_queue_pipeline_for_user','cached_queue_job',
            'queue_cache_dir_for_user','remove_finished_queue_cache','get_processing_queue','remove_queued_job',
            'get_cache_info','get_cached_background','get_cached_audio','get_queue_cache','public_cached_queue_job','get_queue_cache_job','get_queue_cache_segments',
            'save_queue_cache_segments','reprocess_queue_cache_job','clear_queue_cache','process_karaoke','processing_queue_worker'}
        tree=ast.parse((ROOT/'app/main.py').read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in {'EditWordModel','EditSegmentModel','ContinueProcessModel'}
            or isinstance(n,ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'queue-routes','exec'),self.scope)
        self.client=TestClient(app);self.addCleanup(self.client.close)
        self.queue=self.scope['processing_queue']

    def paths(self,user):
        base=self.root/user['username'];paths={key:str(base/key) for key in ('cache','library','output')}
        for path in paths.values(): Path(path).mkdir(parents=True,exist_ok=True)
        for name in ('history','videos','photos'): (base/'library'/name).mkdir(exist_ok=True)
        return paths

    def job(self,id,status='done',owner='alice',subtitle=False):
        paths=self.paths({'username':owner}); cache=self.root/'jobs'/id/'cache';cache.mkdir(parents=True)
        (cache/'original_input.mp4').write_bytes(id.encode())
        (cache/'cache_meta.json').write_text(json.dumps({'input_ext':'.mp4','original_filename':id,'audio_filename':id+'.mp4','lyrics_text':'Guia '+id}))
        segments=[{'start':10,'end':13,'text':'Texto '+id,'words':[{'word':'Texto ','start':10.2,'end':10.5},{'word':id,'start':11.7,'end':12.5}]}]
        (cache/'transcribed_segments.json').write_text(json.dumps(segments))
        pipeline=dict(input_audio_path=str(cache/'original_input.mp4'),cache_dir=str(cache),library_dir=paths['library'],
            output_dir=paths['output'],owner_user={'username':owner,'role':'user'},background_mode='original',
            whisper_model='medium',font_size=32,text_color='#00FFFF',text_position='bottom',subtitle_mode='word',
            transcription_preset='karaoke',lyrics_mode='manual',lyrics_text='Guia '+id,subtitle_only=subtitle,
            subtitle_settings=normalize_subtitle_settings({'font_size':36}) if subtitle else None)
        item=dict(id=id,title=id,status=status,owner_username=owner,owner_role='user',batch_id=owner+'-batch',pipeline=pipeline,
                  process_summary={'mode':'Legendar vídeo' if subtitle else 'Modo Detalhado'})
        self.queue.append(item);return item

    def test_clear_entire_exhausted_queue_preserves_results_and_other_profiles(self):
        owned = [self.job(name, status) for name,status in [('A','done'),('E','error'),('C','cancelled'),('R','removed'),('V','replaced')]]
        bob = self.job('BOB','processing',owner='bob')
        self.user['role'] = 'admin'; self.scope['processing_queue_paused'] = True
        paths = self.paths(self.user); legacy = Path(paths['cache'])
        (legacy/'draft.json').write_text('draft')
        previews=legacy/'thumbnails';previews.mkdir();(previews/'other-profile.jpg').write_bytes(b'library preview')
        for suffix in ('.previous','.promoting'):
            folder=Path(str(legacy)+suffix);folder.mkdir();(folder/'old.wav').write_bytes(b'old')
        history=Path(paths['library'])/'history'/'finished.mp4';history.write_bytes(b'permanent result')
        original=Path(paths['library'])/'videos'/'original.mp4';original.write_bytes(b'permanent source')
        background=Path(paths['library'])/'photos'/'background.png';background.write_bytes(b'permanent background')
        self.scope['youtube_publisher'].replacement_for = Mock(side_effect=AssertionError('publication must remain intact'))
        self.scope['save_processing_queue_unlocked']()
        response = self.client.delete('/api/queue-cache')
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['removed'],5)
        self.assertEqual([j['id'] for j in self.queue],['BOB'])
        self.assertEqual([j['id'] for j in json.loads((self.root/'queue.json').read_text())],['BOB'])
        for item in owned:self.assertFalse(Path(item['pipeline']['cache_dir']).exists())
        self.assertTrue(Path(bob['pipeline']['cache_dir']).is_dir());self.assertEqual(list(legacy.iterdir()),[previews])
        self.assertEqual((previews/'other-profile.jpg').read_bytes(),b'library preview')
        self.assertFalse(Path(str(legacy)+'.previous').exists());self.assertFalse(Path(str(legacy)+'.promoting').exists())
        self.assertEqual(history.read_bytes(),b'permanent result');self.assertEqual(original.read_bytes(),b'permanent source')
        self.assertEqual(background.read_bytes(),b'permanent background');self.assertTrue(self.scope['processing_queue_paused'])
        self.assertEqual(self.client.get('/api/queue-cache/A/segments').status_code,404)
        again=self.client.delete('/api/queue-cache');self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(again.json()['removed'],0)

    def test_clear_is_blocked_while_owned_work_is_queued_processing_or_still_canceling(self):
        active=self.job('A','queued');self.scope['save_processing_queue_unlocked']()
        for status,cancel in [('queued',False),('processing',False),('processing',True)]:
            with self.subTest(status=status,cancel=cancel):
                active['status']=status;active['cancel_requested']=cancel
                response=self.client.delete('/api/queue-cache')
                self.assertEqual(response.status_code,409,response.text)
                self.assertTrue(Path(active['pipeline']['cache_dir']).is_dir())
                self.assertEqual(self.queue,[active])

    def test_failed_clear_persistence_does_not_delete_any_cache(self):
        a=self.job('A');self.scope['save_processing_queue_unlocked']()
        self.scope['save_processing_queue_unlocked']=Mock(side_effect=OSError('disk full'))
        response=self.client.delete('/api/queue-cache')
        self.assertEqual(response.status_code,503,response.text)
        self.assertTrue(Path(a['pipeline']['cache_dir']).is_dir());self.assertEqual(self.queue,[a])
        self.assertEqual(json.loads((self.root/'queue.json').read_text())[0]['id'],'A')

    def test_partial_cleanup_failure_keeps_queue_available_for_retry(self):
        a=self.job('A');b=self.job('B');self.scope['save_processing_queue_unlocked']()
        root_b=Path(b['pipeline']['cache_dir']).parent;remove=shutil.rmtree
        def fail(path,*args,**kwargs):
            if Path(path)==root_b:raise PermissionError('busy file')
            return remove(path,*args,**kwargs)
        with patch.object(shutil,'rmtree',side_effect=fail):response=self.client.delete('/api/queue-cache')
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual([j['id'] for j in self.queue],['A','B'])
        self.assertEqual(len(json.loads((self.root/'queue.json').read_text())),2)
        self.assertFalse(Path(a['pipeline']['cache_dir']).exists());self.assertTrue(root_b.is_dir())
        response=self.client.delete('/api/queue-cache');self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.queue,[]);self.assertFalse(root_b.exists())

    def test_invalid_record_cannot_clear_directories_outside_the_queue_root(self):
        a=self.job('A')
        for id in ('../../alice/library','.','..','../jobs/A'):
            with self.subTest(id=id):
                a['id']=id;response=self.client.delete('/api/queue-cache')
                self.assertEqual(response.status_code,409,response.text)
                self.assertTrue(Path(a['pipeline']['cache_dir']).is_dir());self.assertEqual(self.queue,[a])

    def test_cleanup_unlinks_owned_symlink_without_deleting_another_profiles_files(self):
        a=self.job('A');bob=self.job('BOB','processing',owner='bob')
        root=Path(a['pipeline']['cache_dir']).parent;shutil.rmtree(root)
        bob_root=Path(bob['pipeline']['cache_dir']).parent;root.symlink_to(bob_root,target_is_directory=True)
        response=self.client.delete('/api/queue-cache')
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(root.is_symlink());self.assertTrue(bob_root.is_dir())
        self.assertEqual((bob_root/'cache'/'original_input.mp4').read_bytes(),b'BOB')

    def test_revisions_and_live_items_are_displayed_before_finished_rows_without_changing_fifo(self):
        self.job('A');self.job('E','error');self.job('Q1','queued');self.job('BOB','queued',owner='bob')
        self.job('Q2','queued');self.job('LIVE','processing');self.job('C','cancelled')
        initial=[j['id'] for j in self.queue]
        visible=self.client.get('/api/queue?include_completed=true').json()['jobs']
        self.assertEqual([j['id'] for j in visible],['LIVE','Q1','Q2','A','E','C'])
        self.assertEqual([j.get('position') for j in visible[:3]],[None,1,3])
        self.assertEqual([j['id'] for j in self.queue],initial)
        revision=self.client.post('/api/queue-cache/A/reprocess');self.assertEqual(revision.status_code,200,revision.text)
        id=revision.json()['job_id']
        visible=self.client.get('/api/queue?include_completed=true').json()['jobs']
        self.assertEqual([j['id'] for j in visible],['LIVE','Q1','Q2',id,'A','E','C'])
        self.assertEqual(visible[3]['position'],4)
        self.assertEqual([j['id'] for j in self.queue],initial+[id])
        self.assertEqual([j['id'] for j in self.client.get('/api/queue-cache').json()['jobs']],['LIVE','Q1','Q2',id,'A','E','C'])

    def test_queue_and_settings_do_not_load_complete_transcriptions(self):
        a = self.job('A'); self.job('B', 'queued')
        self.job('BOB', owner='bob')
        availability = queue_cache.has_segments
        def available(cache):
            self.assertFalse(self.scope['processing_queue_lock']._is_owned())
            return availability(cache)
        with patch.object(queue_cache, 'has_segments', side_effect=available), patch.object(queue_cache, 'read_segments', side_effect=AssertionError('full transcription in list/settings')):
            for route in ('/api/queue?include_completed=true', '/api/queue-cache'):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual([job['id'] for job in response.json()['jobs']], ['B', 'A'])
                self.assertTrue(all(job['has_segments'] for job in response.json()['jobs']))
            settings = self.client.get('/api/queue-cache/A?include_segments=false')
            self.assertEqual(settings.status_code, 200, settings.text)
            self.assertNotIn('segments', settings.json())
            self.assertEqual(settings.json()['options']['font_size'], 32)
        (Path(a['pipeline']['cache_dir']) / 'transcribed_segments.json').write_text('[]')
        (Path(a['pipeline']['cache_dir']) / 'lyrics_guide_cache.json').write_text(json.dumps({'signature':'x'*64,'segments':[],'report':{}}))
        self.assertFalse(next(job for job in self.client.get('/api/queue?include_completed=true').json()['jobs'] if job['id']=='A')['has_segments'])

    def test_editor_reads_only_selected_segments_without_publication_lookup_or_queue_lock(self):
        self.job('A'); self.job('BOB', owner='bob')
        self.scope['youtube_publisher'].replacement_for = Mock(side_effect=AssertionError('unneeded publication lookup'))
        original = queue_cache.read_segments
        def read(cache):
            self.assertFalse(self.scope['processing_queue_lock']._is_owned())
            return original(cache)
        with patch.object(queue_cache, 'read_segments', side_effect=read) as reader:
            response = self.client.get('/api/queue-cache/A/segments')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['segments'][0]['text'], 'Texto A')
            reader.assert_called_once()
        self.assertEqual(self.client.get('/api/queue-cache/BOB/segments').status_code, 403)

    def test_preview_probes_once_per_unchanged_file(self):
        self.job('A')
        probe = Mock(return_value=True); self.scope['check_has_video'] = probe
        self.assertTrue(self.client.get('/api/cache_info?job_id=A').json()['bg_is_video'])
        self.assertEqual(self.client.get('/api/cache/background?job_id=A').content, b'A')
        probe.assert_called_once()
        source = Path(self.queue[0]['pipeline']['input_audio_path']); source.write_bytes(b'changed')
        self.assertTrue(self.client.get('/api/cache_info?job_id=A').json()['bg_is_video'])
        self.assertEqual(probe.call_count, 2)

    def test_quick_revision_keeps_saved_settings_despite_changed_profile(self):
        a = self.job('A')
        a['process_summary']['mode'] = 'Modo Rápido'
        a['pipeline'].update(font_size=41, text_color='#123456', text_position='top', subtitle_mode='line',
            background_mode='image', enable_correction=True, keep_backing_vocals=False, backing_vocals_volume=37,
            words_per_line=4, max_chars_line=22, show_instrumental=False, transcribe_source='vocals',
            show_next_line_preview=True, keep_first_line_visible=True)
        a['creation_options'] = {'save_to_library':False, 'pause_for_editing':False}
        cache = Path(a['pipeline']['cache_dir']); (cache/'original_bg.png').write_bytes(b'background')
        meta = json.loads((cache/'cache_meta.json').read_text()); meta.update(has_bg=True, bg_ext='.png', bg_filename='Fundo A.png')
        (cache/'cache_meta.json').write_text(json.dumps(meta))
        self.scope['load_easy_mode_config'] = Mock(side_effect=AssertionError('current profile must not override revision'))
        settings = self.client.get('/api/queue-cache/A?include_segments=false').json()['options']
        self.assertEqual(settings['background_filename'], 'Fundo A.png')
        result = self.client.post('/api/queue-cache/A/reprocess')
        self.assertEqual(result.status_code, 200, result.text)
        revised = self.queue[-1]
        for key in ('font_size','text_color','text_position','subtitle_mode','background_mode','keep_backing_vocals',
                    'backing_vocals_volume','words_per_line','max_chars_line','show_instrumental','transcribe_source',
                    'show_next_line_preview','keep_first_line_visible'):
            self.assertEqual(revised['pipeline'][key], a['pipeline'][key], key)
        self.assertFalse(revised['pipeline']['enable_correction']) # Save-and-render skips another review pause.
        self.assertFalse(revised['creation_options']['save_to_library'])
        self.assertEqual(Path(revised['pipeline']['input_bg_path']).read_bytes(), b'background')
        data = {key:str(value).lower() if isinstance(value,bool) else str(value) for key,value in settings.items() if value is not None and not isinstance(value,dict)}
        data.update(cache_job_id='A', font_size='48', lyrics_text='Guia alterada', enable_correction='true')
        result = self.client.post('/api/process', data=data)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.queue[-1]['pipeline']['font_size'],48)
        self.assertEqual(self.queue[-1]['pipeline']['lyrics_text'],'Guia alterada')
        self.assertTrue(self.queue[-1]['pipeline']['enable_correction'])

    def test_finished_cache_survives_disk_restart_and_does_not_appear_as_pending(self):
        a=self.job('A');b=self.job('B','error')
        self.scope['save_processing_queue_unlocked']();self.scope['load_processing_queue']()
        self.assertEqual([j['status'] for j in self.scope['processing_queue']],['done','error'])
        self.assertEqual(self.client.get('/api/queue').json()['jobs'],[])
        self.assertEqual([j['id'] for j in self.client.get('/api/queue-cache').json()['jobs']],['A','B'])
        self.assertEqual([j['id'] for j in self.client.get('/api/queue?include_completed=true').json()['jobs']],['A','B'])
        self.assertTrue(Path(a['pipeline']['cache_dir']).is_dir());self.assertTrue(Path(b['pipeline']['cache_dir']).is_dir())

    def test_new_source_only_rotates_after_current_queue_is_exhausted(self):
        a=self.job('A');b=self.job('B','queued');bob=self.job('BOB',owner='bob')
        result=self.client.post('/api/process',files={'audio_file':('C.mp4',b'C','video/mp4')})
        self.assertEqual(result.status_code,200,result.text)
        c=next(j for j in self.queue if j['id']==result.json()['job_id']);self.assertEqual(c['batch_id'],b['batch_id'])
        self.assertTrue(Path(a['pipeline']['cache_dir']).exists())
        for j in self.queue:
            if j['owner_username']=='alice':j['status']='done'
        history=Path(a['pipeline']['library_dir'])/'history'/'result.mp4';history.write_bytes(b'result')
        nextresult=self.client.post('/api/process',files={'audio_file':('D.mp4',b'D','video/mp4')})
        self.assertEqual(nextresult.status_code,200,nextresult.text)
        self.assertFalse(Path(a['pipeline']['cache_dir']).exists());self.assertFalse(Path(b['pipeline']['cache_dir']).exists())
        self.assertTrue(Path(bob['pipeline']['cache_dir']).exists());self.assertTrue(history.exists())
        self.assertEqual(len([j for j in self.queue if j['owner_username']=='alice']),1)
        self.assertEqual([j['id'] for j in self.client.get('/api/queue?include_completed=true').json()['jobs']],[nextresult.json()['job_id']])

    def test_draft_and_reprocess_are_bound_to_a_while_b_is_active(self):
        a=self.job('A');b=self.job('B','processing');self.job('BOB',owner='bob')
        detail=self.client.get('/api/queue-cache/A').json();segments=detail['segments'];segments[0]['text']='Texto corrigido'
        response=self.client.patch('/api/queue-cache/A/segments',json={'segments':segments})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([(w['start'],w['end']) for w in response.json()['segments'][0]['words']],[(10.2,10.5),(11.7,12.5)])
        result=self.client.post('/api/queue-cache/A/reprocess')
        self.assertEqual(result.status_code,200,result.text)
        replay=next(j for j in self.queue if j['id']==result.json()['job_id'])
        self.assertEqual(replay['batch_id'],a['batch_id']);self.assertEqual(replay['revision_of'],'A')
        newcache=Path(replay['pipeline']['cache_dir'])
        self.assertEqual((newcache/'original_input.mp4').read_bytes(),b'A')
        self.assertEqual(json.loads((newcache/'review_draft.json').read_text())[0]['text'],'Texto corrigido')
        self.assertEqual(self.client.get('/api/cache/audio?job_id=A').content,b'A')
        self.assertEqual(b['status'],'processing')
        self.assertEqual(self.client.get('/api/cache/audio?job_id=BOB').status_code,403)
        self.assertEqual(self.client.patch('/api/queue-cache/B/segments',json={'segments':segments}).status_code,409)

    def test_reprocess_finished_queue_does_not_rotate_and_queued_edit_replaces_slot(self):
        a=self.job('A');result=self.client.post('/api/queue-cache/A/reprocess');self.assertEqual(result.status_code,200,result.text)
        replay=self.queue[-1];self.assertTrue(Path(a['pipeline']['cache_dir']).exists())
        again=self.client.post('/api/queue-cache/'+replay['id']+'/reprocess');self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(replay['status'],'queued') # planner uses copies to ensure rollback
        latest=next(j for j in self.queue if j['id']==replay['id']);self.assertEqual(latest['status'],'replaced')
        self.assertEqual(len([j for j in self.queue if j['status']=='queued']),1)

    def test_failed_new_queue_acceptance_preserves_previous_files_and_metadata(self):
        a=self.job('A');self.scope['save_processing_queue_unlocked']()
        self.scope['save_processing_queue_unlocked']=Mock(side_effect=OSError('disk full'))
        response=self.client.post('/api/process',files={'audio_file':('new.mp4',b'new','video/mp4')})
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual(self.queue,[a]);self.assertTrue(Path(a['pipeline']['cache_dir']).exists())
        self.assertEqual(json.loads((self.root/'queue.json').read_text())[0]['id'],'A')

    def test_invalid_drafts_cannot_modify_saved_review(self):
        a=self.job('A');segments=self.client.get('/api/queue-cache/A').json()['segments'];segments[0]['end']=9
        self.assertEqual(self.client.patch('/api/queue-cache/A/segments',json={'segments':segments}).status_code,400)
        self.assertFalse((Path(a['pipeline']['cache_dir'])/'review_draft.json').exists())
        self.assertEqual(self.client.get('/api/queue-cache/missing').status_code,404)

    def test_removed_cancelled_items_remain_editable_after_restart(self):
        a=self.job('A','queued');b=self.job('B','processing');b['cancel_requested']=True
        self.assertEqual(self.client.delete('/api/queue/A').status_code,200)
        self.scope['save_processing_queue_unlocked']();self.scope['load_processing_queue']()
        self.assertEqual([j['status'] for j in self.scope['processing_queue']],['removed','cancelled'])
        self.assertTrue(Path(a['pipeline']['cache_dir']).exists());self.assertTrue(Path(b['pipeline']['cache_dir']).exists())

    def test_new_revision_drops_render_srt_and_translation_checkpoints(self):
        a=self.job('A',subtitle=True);cache=Path(a['pipeline']['cache_dir'])
        (cache/'stage_checkpoints.json').write_text(json.dumps({'active_processing_seconds':500,'completed_stages':{'subtitle_transcription_ready':{},'subtitle_original_ready':{'filename':'old.srt'},'subtitle_translation_finished':{},'video_rendered':{}}}))
        result=self.client.post('/api/process',data={'cache_job_id':'A','subtitle_only':'true','subtitle_settings_json':'{"font_size":44}'})
        self.assertEqual(result.status_code,200,result.text)
        replay=self.queue[-1];self.assertEqual(replay['pipeline']['subtitle_settings']['font_size'],44)
        checkpoints=json.loads((Path(replay['pipeline']['cache_dir'])/'stage_checkpoints.json').read_text())
        self.assertEqual(set(checkpoints['completed_stages']),{'subtitle_transcription_ready'})
        self.assertEqual(checkpoints['active_processing_seconds'],0)

    def test_live_worker_keeps_both_success_and_failed_cache(self):
        a=self.job('A','queued');b=self.job('B','queued')
        state={};self.scope.update(state=state,state_lock=threading.Lock(),update_state=Mock(),StagePauseRequested=type('StagePauseRequested',(Exception,),{}))
        def pipeline(**options):
            id=Path(options['cache_dir']).parent.name
            state.update(status='done' if id=='A' else 'error',error_message='Falha' if id=='B' else '',history_filename='A.mp4',subtitle_filename=None)
        self.scope['run_pipeline']=pipeline
        self.scope['processing_queue_event']=SimpleNamespace(wait=Mock(side_effect=[True,StopIteration()]),clear=Mock(),set=Mock())
        with self.assertRaises(StopIteration):self.scope['processing_queue_worker']()
        self.assertEqual([j['status'] for j in self.queue],['done','error'])
        self.assertTrue(Path(a['pipeline']['cache_dir']).exists());self.assertTrue(Path(b['pipeline']['cache_dir']).exists())

    def test_worker_finishes_current_record_when_another_item_is_enqueued_during_processing(self):
        a=self.job('A','queued');self.job('B','queued');c=self.job('C','queued');self.queue.remove(c)
        state={};self.scope.update(state=state,state_lock=threading.Lock(),update_state=Mock(),StagePauseRequested=type('StagePauseRequested',(Exception,),{}))
        def pipeline(**options):
            id=Path(options['cache_dir']).parent.name
            if id=='A': self.scope['enqueue_processing_job'](c)
            state.update(status='done',error_message='',history_filename=id+'.mp4',subtitle_filename=None)
        self.scope['run_pipeline']=pipeline
        self.scope['processing_queue_event']=SimpleNamespace(wait=Mock(side_effect=[True,StopIteration()]),clear=Mock(),set=Mock())
        with self.assertRaises(StopIteration):self.scope['processing_queue_worker']()
        self.assertEqual([j['status'] for j in self.queue],['done','done','done'])
        self.assertEqual([j['history_filename'] for j in self.queue],['A.mp4','B.mp4','C.mp4'])
        self.assertEqual(self.queue[-1]['batch_id'],a['batch_id'])

    def test_manual_review_survives_a_revision_with_new_model_settings(self):
        a=self.job('A');cache=Path(a['pipeline']['cache_dir'])
        segments=[{'start':1,'end':2,'text':'Correção manual','words':[]}]
        (cache/'reviewed_segments.json').write_text(json.dumps(segments))
        (cache/'stage_checkpoints.json').write_text(json.dumps({'completed_stages':{'transcription_reviewed':{}}}))
        result=self.client.post('/api/process',data={'cache_job_id':'A','whisper_model':'small'})
        self.assertEqual(result.status_code,200,result.text)
        replay=self.queue[-1];self.assertEqual(replay['pipeline']['whisper_model'],'small')
        self.assertEqual(queue_cache.read_draft(replay['pipeline']['cache_dir']),segments)

    def test_editor_reads_the_verified_guide_result_before_raw_recognition(self):
        a=self.job('A');cache=Path(a['pipeline']['cache_dir'])
        verified=[{'start':1,'end':2,'text':'Texto conferido','words':[]}]
        (cache/'lyrics_guide_cache.json').write_text(json.dumps({'segments':verified,'report':{}}))
        self.assertEqual(self.client.get('/api/queue-cache/A').json()['segments'],verified)

    def test_existing_queue_list_can_include_finished_items_and_actions_without_exposing_other_profiles(self):
        self.job('A');self.job('B','queued');self.job('C','cancelled');self.job('BOB',owner='bob')
        self.assertEqual([j['id'] for j in self.client.get('/api/queue').json()['jobs']],['B'])
        visible=self.client.get('/api/queue?include_completed=true').json()['jobs']
        self.assertEqual([j['id'] for j in visible],['B','A','C'])
        self.assertEqual(visible[0]['position'],1)
        self.assertTrue(visible[0]['has_segments']);self.assertTrue(visible[0]['can_reprocess'])
        self.user={'username':'administrator','role':'admin'}
        self.assertEqual(len(self.client.get('/api/queue?include_completed=true').json()['jobs']),4)

    def test_finished_queue_list_does_not_drop_earlier_items_at_a_display_limit(self):
        for index in range(105): self.job(str(index))
        self.assertEqual(len(self.client.get('/api/queue?include_completed=true').json()['jobs']),105)
        self.assertEqual(self.client.get('/api/queue').json()['jobs'],[])

    def test_snapshot_freezes_guide_but_does_not_expose_paths(self):
        a=self.job('A');options=self.client.get('/api/queue-cache/A').json()['options']
        self.assertEqual(options['lyrics_mode'],'manual');self.assertEqual(options['lyrics_text'],'Guia A')
        self.assertFalse(any(key.endswith('_dir') or key in {'owner_user','input_audio_path'} for key in options))


if __name__=='__main__':unittest.main()
