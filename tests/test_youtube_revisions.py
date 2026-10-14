"""Verify replacement ordering, playlist retry checkpoints and Telegram link bindings."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
from youtube_publisher import PublicationError
from result_publication import record_result_kind
import test_youtube_publisher as baseline


class YouTubeRevisionsTests(unittest.TestCase):
    def setUp(self):
        baseline.PublisherTests.setUp(self)
        self.old={**self.job,'status':'done','video_id':'oldVideo001','actual_privacy':'public',
                  'telegram_link_enabled':True,'telegram_results':[{'video':str(self.video),'automatic':True}]}
        self.publisher.save('jobs.json',[self.old]);self.publisher.start=Mock()
        self.new=Path(self.folder.name)/'new.mp4';self.new.write_bytes(b'new-render');record_result_kind(self.new,'karaoke')
        self.playlists=[{'id':id,'title':id} for id in ('playlist-one','playlist-two','playlist-three')]
        self.publisher.playlists=Mock(return_value=self.playlists)

    def enqueue(self):
        result=self.publisher.enqueue(self.new,'Corrigido','public','playlist-one',thumbnail=b'\xff\xd8\xffcover',
            additional_playlists=['playlist-two','playlist-three'],replaces_video_id='oldVideo001',automatic=True)
        return next(j for j in self.publisher.read('jobs.json',[]) if j['id']==result['id'])

    def backend(self,job,fail_playlist=None,privacy='public',channel='channel-one',delete_timeout=False,old_exists=True):
        calls=[];state={'old_exists':old_exists,'fail_playlist':fail_playlist,'delete_timeout':delete_timeout}
        def upload(j):self.publisher.checkpoint(j,video_id='newVideo001');return 'newVideo001'
        def api(method,path,**options):
            calls.append((method,path,options))
            if path=='/playlistItems':
                playlist=options.get('params',{}).get('playlistId') or options.get('json',{}).get('snippet',{}).get('playlistId')
                if method=='POST' and playlist==state['fail_playlist']:
                    state['fail_playlist']=None;raise PublicationError('Playlist indisponível')
                return {'items':[]} if method=='GET' else {'id':'added'}
            if method=='PUT':return {'status':{'privacyStatus':privacy}}
            if method=='GET':return {'items':[{'id':'oldVideo001','snippet':{'channelId':channel}}] if state['old_exists'] else []}
            if method=='DELETE':
                self.assertEqual(options['params']['id'],'oldVideo001');self.assertEqual(job['thumbnail_done'],True)
                self.assertEqual(set(job['completed_playlists']),{p['id'] for p in self.playlists})
                state['old_exists']=False
                if state['delete_timeout']:state['delete_timeout']=False;raise PublicationError('Timeout')
                return {}
            raise AssertionError((method,path))
        return calls,state,upload,api

    def test_all_playlists_and_confirmed_privacy_precede_removal_and_update_original_telegram(self):
        job=self.enqueue();calls,_,upload,api=self.backend(job);notify=Mock(return_value=True);self.publisher.on_published=notify
        with patch.object(self.publisher,'upload_video',side_effect=upload),patch.object(self.publisher,'upload_request',return_value=baseline.response()),patch.object(self.publisher,'api',side_effect=api):
            self.publisher.publish(job)
        delete=next(i for i,c in enumerate(calls) if c[0]=='DELETE');privacy=next(i for i,c in enumerate(calls) if c[0]=='PUT')
        self.assertLess(privacy,delete)
        self.assertEqual(job['status'],'done');self.assertTrue(job['replacement_done'])
        self.assertEqual({c.args[0]['video'] for c in notify.call_args_list},{str(self.video),str(self.new)})
        self.assertEqual(self.publisher.replacement_for(self.video)['video_id'],'newVideo001')
        self.assertFalse(self.publisher.read('jobs.json',[])[0]['telegram_link_enabled'])

    def test_playlist_failure_preserves_previous_video_and_retry_skips_confirmed_playlist(self):
        job=self.enqueue();calls,_,upload,api=self.backend(job,fail_playlist='playlist-two')
        with patch.object(self.publisher,'upload_video',side_effect=upload),patch.object(self.publisher,'upload_request',return_value=baseline.response()),patch.object(self.publisher,'api',side_effect=api):
            with self.assertRaises(PublicationError):self.publisher.publish(job)
            self.assertFalse(any(c[0]=='DELETE' for c in calls));self.assertEqual(job['completed_playlists'],['playlist-one'])
            self.publisher.publish(job)
        inserts=[c[2]['json']['snippet']['playlistId'] for c in calls if c[0]=='POST']
        self.assertEqual(inserts.count('playlist-one'),1);self.assertTrue(job['replacement_done'])

    def test_unconfirmed_privacy_and_foreign_channel_preserve_previous_video(self):
        for privacy,channel in [('private','channel-one'),('public','foreign')]:
            with self.subTest(privacy=privacy,channel=channel):
                job=self.enqueue();calls,_,upload,api=self.backend(job,privacy=privacy,channel=channel)
                with patch.object(self.publisher,'upload_video',side_effect=upload),patch.object(self.publisher,'upload_request',return_value=baseline.response()),patch.object(self.publisher,'api',side_effect=api):
                    with self.assertRaises(PublicationError):self.publisher.publish(job)
                self.assertFalse(any(c[0]=='DELETE' for c in calls))

    def test_retry_after_uncertain_delete_checks_absence_without_another_delete(self):
        job=self.enqueue();calls,_,upload,api=self.backend(job,delete_timeout=True)
        with patch.object(self.publisher,'upload_video',side_effect=upload),patch.object(self.publisher,'upload_request',return_value=baseline.response()),patch.object(self.publisher,'api',side_effect=api):
            with self.assertRaises(PublicationError):self.publisher.publish(job)
            self.publisher.publish(job)
        self.assertEqual(sum(c[0]=='DELETE' for c in calls),1);self.assertEqual(job['status'],'done')

    def test_extra_playlist_validation_and_default_are_independent_of_primary(self):
        self.assertEqual(self.publisher.validate_additional_playlists(None,'playlist-one'),[])
        self.assertEqual(self.publisher.validate_additional_playlists(['playlist-two','playlist-one','playlist-two'],'playlist-one'),['playlist-two'])
        for values in ('playlist-two',['foreign'],[None],['bad id'],['playlist-two']*21):
            with self.subTest(values=values),self.assertRaises(PublicationError):self.publisher.validate_additional_playlists(values,'playlist-one')
        self.publisher.save('settings.json',{'defaults':{'playlist_id':'playlist-one'},'user_assignments':{'alice':{'playlist_id':'playlist-one'}}})
        options=self.publisher.publication_options({'username':'alice','role':'user'},True,additional_playlists=['playlist-two'])
        self.assertEqual(options['playlist_id'],'playlist-one');self.assertEqual(options['additional_playlists'],['playlist-two'])
        self.assertEqual(self.publisher.publication_options({'role':'admin'},True)['additional_playlists'],[])

    def test_http_204_delete_is_success_without_json_body(self):
        response=SimpleNamespace(status_code=204,json=Mock(side_effect=ValueError('empty')))
        with patch.object(self.publisher,'authenticated_request',return_value=response):self.assertEqual(self.publisher.api('DELETE','/videos'),{})
        response.json.assert_not_called()

    def test_unknown_replacement_cannot_delete_a_video(self):
        with self.assertRaises(PublicationError):self.publisher.enqueue(self.new,'Song',playlist_id='playlist-one',thumbnail=b'\xff\xd8\xffcover',replaces_video_id='unknown0001')


if __name__=='__main__':unittest.main()
