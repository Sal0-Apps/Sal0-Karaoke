"""Exercise actual policy dispatch and text-only completion without Telegram network access."""
import ast
import html
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).parents[1]/'app'))
import telegram_preferences as prefs
from test_automatic_lyrics_and_search import load_function


class PreferenceTests(unittest.TestCase):
    def target(self,mode='quick'):
        return {'telegram_token':'bot','telegram_chat_id':'chat','_mode':mode,'_title':'A <song>',
                'notification_policy':prefs.normalize()}

    def test_filters_and_safe_text_are_independent_for_each_mode(self):
        target=self.target(); policy=target['notification_policy']
        policy['modes']['quick']['transcription']=False
        self.assertIsNone(prefs.message(target,'transcription','Original'))
        self.assertEqual(prefs.message({**target,'_mode':'subtitle'},'transcription','Original'),'Original')
        policy['templates']['quick']['completed']='Meu <texto> · {titulo} · {tempo}\n{links}'
        text=prefs.message(target,'completed','Native',elapsed=3661,links='<a href="https://local/file">Baixar</a>')
        self.assertIn('Meu &lt;texto&gt;',text);self.assertIn('A &lt;song&gt;',text)
        self.assertIn('1h 01min 01s',text);self.assertIn('<a href=',text)
        policy['enabled']=False
        self.assertIsNone(prefs.message(target,'completed','Original'))

    def test_dispatch_reloads_settings_and_never_queues_a_disabled_event(self):
        target=self.target();send=Mock()
        target['notification_policy']['modes']['quick']['download']=False
        notify=load_function('notify_targets',resolve_notification_target=lambda old:target,
            send_telegram_notification=send,state={'progress':20})
        notify([{'stale':'configuration'}],'Original',event='download');send.assert_not_called()
        target['notification_policy']['templates']['quick']['started']='Iniciando {titulo}: {progresso}'
        notify([target],'Original',event='started')
        self.assertEqual(send.call_args.args,('bot','chat','Iniciando A &lt;song&gt;: 20%'))

    def test_text_only_completion_never_opens_compresses_or_uploads_media(self):
        sender=Mock(return_value=True);encode=Mock();upload=Mock()
        flow=load_function('send_telegram_video_flow',
            format_processing_duration=lambda seconds:'1 min',telegram_escape=lambda text:html.escape(str(text)),
            telegram_notice=lambda icon,title,*parts:title+'\n'+'\n'.join(parts),
            _send_telegram_notification_worker=sender,compress_video_for_telegram=encode,TELEGRAM_DELIVERY=upload)
        target=self.target();target['notification_policy']['templates']['quick']['completed']='Pronto: {titulo}\n{links}'
        self.assertTrue(flow('bot','chat','/file-that-does-not-exist.mp4','Song','Song.mp4','token',
            'http://local',notification_target=target,allow_attachment=False))
        encode.assert_not_called();upload.send_video.assert_not_called()
        self.assertIn('Pronto: A &lt;song&gt;',sender.call_args.args[2])
        self.assertIn('http://local/api/public/download/token',sender.call_args.args[2])
        sender.reset_mock();target['notification_policy']['modes']['quick']['links']=False
        flow('bot','chat','/missing.mp4','Song','Song.mp4','token','http://local',notification_target=target,allow_attachment=False)
        self.assertNotIn('http://local',sender.call_args.args[2])

    def test_no_selected_destinations_never_encodes_or_uploads(self):
        target=self.target();target['notification_policy']['enabled']=False
        send=Mock();encode=Mock()
        dispatch=load_function('send_video_to_targets',resolve_notification_target=lambda target:target,
            compress_video_for_telegram=encode,send_telegram_video_flow=send)
        dispatch([target],'/missing.mp4','Song','Song.mp4','','','',subtitle_downloads=[])
        send.assert_not_called();encode.assert_not_called()
