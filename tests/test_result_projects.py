"""Finished videos keep their original project across queue rotation and restart."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
import result_projects
import test_queue_cache as queue_routes


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.queue=self.root/'queue';self.library=self.root/'alice/library'
        self.video=self.library/'history'/'Música - Karaokê.mp4';self.video.parent.mkdir(parents=True);self.video.write_bytes(b'result')
        self.identifier=uuid.uuid4().hex;self.cache=self.queue/self.identifier/'cache';self.cache.mkdir(parents=True)
        (self.cache/'original_input.mp4').write_bytes(b'original media')
        (self.cache/'reviewed_segments.json').write_text('[{"start":1,"end":2,"text":"Guia"}]')
        self.job={'id':self.identifier,'owner_username':'alice','history_filename':self.video.name,
            'process_summary':{'mode':'Modo Rápido'},'pipeline':{'cache_dir':str(self.cache),'library_dir':str(self.library),
            'owner_user':{'username':'alice','role':'user'},'font_size':48,'lyrics_text':'Guia completa'}}

    def test_snapshot_and_media_remain_editable_for_the_owner(self):
        self.assertTrue(result_projects.capture(self.job,self.queue))
        loaded=result_projects.lookup_video(self.video,self.queue,{'username':'alice'})
        self.assertEqual(loaded['pipeline']['font_size'],48)
        self.assertEqual(loaded['pipeline']['lyrics_text'],'Guia completa')
        self.assertTrue(result_projects.protected(self.cache,self.queue))
        self.assertIsNone(result_projects.lookup_job(self.identifier,self.queue,{'username':'bob'}))
        self.assertIsNotNone(result_projects.lookup_job(self.identifier,self.queue,{'username':'root'},True))
        self.assertEqual((self.cache/'original_input.mp4').read_bytes(),b'original media')

    def test_renaming_keeps_project_and_only_video_deletion_removes_its_cache(self):
        result_projects.capture(self.job,self.queue)
        renamed=self.video.with_name('Nome corrigido.mp4');self.video.rename(renamed)
        result_projects.rename_video(self.video,renamed,self.queue)
        self.assertEqual(result_projects.lookup_video(renamed,self.queue)['history_filename'],renamed.name)
        unrelated=self.queue/uuid.uuid4().hex/'cache';unrelated.mkdir(parents=True)
        renamed.unlink();result_projects.remove_video(renamed,self.queue)
        self.assertFalse(self.cache.exists());self.assertTrue(unrelated.is_dir())

    def test_setting_applies_to_future_jobs_without_deleting_existing_projects(self):
        output=self.root/'alice/output'
        self.assertTrue(result_projects.enabled(output))
        result_projects.capture(self.job,self.queue)
        result_projects.save_settings(output,False)
        self.assertFalse(result_projects.enabled(output))
        self.assertTrue(result_projects.protected(self.cache,self.queue))
        with self.assertRaises(ValueError):result_projects.save_settings(output,'false')


class ResultEditingRoutesTests(unittest.TestCase):
    setUp = queue_routes.QueueCacheTests.setUp
    paths = queue_routes.QueueCacheTests.paths
    job = queue_routes.QueueCacheTests.job
    def test_result_survives_new_batch_and_can_restore_every_setting(self):
        old=self.job(uuid.uuid4().hex)
        history=Path(old['pipeline']['library_dir'])/'history'/'Primeiro - Karaokê.mp4';history.write_bytes(b'finished video')
        old.update(history_filename=history.name,retain_result_cache=True)
        old['pipeline'].update(font_size=51,text_color='#123456',lyrics_text='Guia salva',telegram_mode='quick')
        first_cache=Path(old['pipeline']['cache_dir'])
        response=self.client.post('/api/process',data={'youtube_url':'https://youtu.be/abcdefghijk'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn(old['id'],[job['id'] for job in self.queue])
        self.assertTrue(first_cache.is_dir())
        project=self.client.get('/api/library/history/'+history.name+'/project')
        self.assertEqual(project.status_code,200,project.text)
        self.assertEqual(project.json()['job_id'],old['id'])
        restored=self.client.get('/api/queue-cache/'+old['id']).json()['options']
        self.assertEqual(restored['font_size'],51);self.assertEqual(restored['text_color'],'#123456')
        self.assertEqual(restored['telegram_mode'],'quick')
        revision=self.client.post('/api/process',data={'cache_job_id':old['id'],'font_size':46})
        self.assertEqual(revision.status_code,200,revision.text)
        self.assertEqual(self.queue[-1]['revision_of'],old['id'])
        self.assertEqual(self.queue[-1]['pipeline']['font_size'],46)
        self.assertEqual((Path(self.queue[-1]['pipeline']['cache_dir'])/'original_input.mp4').read_bytes(),old['id'].encode())

    def test_old_result_without_original_cache_is_not_falsely_treated_as_editable(self):
        result=Path(self.paths(self.user)['library'])/'history'/'Antigo.mp4';result.write_bytes(b'burned subtitles')
        response=self.client.get('/api/library/history/Antigo.mp4/project')
        self.assertEqual(response.status_code,409,response.text)
        self.assertIn('não foram preservados',response.json()['detail'])

    def test_deleting_result_disables_its_old_queue_editor_even_with_a_youtube_url(self):
        job=self.job(uuid.uuid4().hex)
        job['pipeline']['youtube_url']='https://youtu.be/abcdefghijk'
        video=Path(job['pipeline']['library_dir'])/'history'/'Deleted.mp4';video.write_bytes(b'video')
        job['history_filename']=video.name
        result_projects.capture(job,self.scope['PROCESSING_QUEUE_ROOT'])
        video.unlink();result_projects.remove_video(video,self.scope['PROCESSING_QUEUE_ROOT'])
        self.assertFalse(self.scope['public_cached_queue_job'](job)['can_reprocess'])
