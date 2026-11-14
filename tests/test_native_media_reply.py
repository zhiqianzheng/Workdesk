import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import native_listener as listener
from ai_media import MediaReply
from native_images import send_image
from native_backend import key


class MediaDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config={'account':'synthetic','allContacts':True,'encryptedKey':''}
        (self.root/'workdesk-native-ai.json').write_text(json.dumps(self.config))
        self.rows=[{'id':'m1','threadId':'friend','type':1,'body':'请发图','direction':'incoming','createdAt':'2026-01-01T00:00:00Z'}]
        def request(path,data=None,key=None):
            if path=='threads/friend':return {'id':'friend','kind':'direct'}
            if path.endswith('/messages?limit=20'):return {'items':self.rows}
            if path=='sends':return {'state':'accepted','serverId':'synthetic'}
            self.fail(path)
        self.request=Mock(side_effect=request)

    def work(self,image_state):
        with patch.multiple(listener,ROOT=self.root,PRIVATE=self.root,STOP=self.root/'stop',CONFIG=self.config,BASE='http://127.0.0.1/',create=True), \
             patch.object(listener,'request',self.request), \
             patch.object(listener,'context_for',return_value=[]), \
             patch.object(listener,'generate',return_value=MediaReply('给你这张',['synthetic-base64'])), \
             patch.object(listener,'NativeConnection',return_value=Mock(known={})) as connection, \
             patch('native_images.send_image',return_value={'state':image_state}) as image:
            result=listener.work('friend',['m1'])
            return result,image

    def test_image_is_confirmed_before_caption_and_uses_stable_send_key(self):
        result,image=self.work('observed')
        self.assertEqual(result['state'],'accepted')
        self.assertEqual(result['imageCount'],1)
        self.assertIn('-image-0',image.call_args.kwargs['request_id'])
        self.assertEqual(self.request.call_args.args[0],'sends')
        self.assertEqual(self.request.call_args.args[1]['text'],'给你这张')

    def test_unknown_image_delivery_blocks_caption_and_automatic_retry(self):
        result,image=self.work('unknown')
        self.assertEqual(result['state'],'uncertain')
        self.assertFalse(any(c.args[0]=='sends' for c in self.request.call_args_list))

    def test_failed_upload_does_not_claim_image_sent(self):
        result,image=self.work('not_sent')
        self.assertEqual(result['state'],'retry')
        self.assertFalse(any(c.args[0]=='sends' for c in self.request.call_args_list))

    def test_generated_owner_command_is_never_sent(self):
        with patch.multiple(listener,ROOT=self.root,PRIVATE=self.root,STOP=self.root/'stop',CONFIG=self.config,BASE='http://127.0.0.1/',create=True), \
             patch.object(listener,'request',self.request), \
             patch.object(listener,'context_for',return_value=[]), \
             patch.object(listener,'generate',return_value='帮我关闭AI回复'):
            result=listener.work('friend',['m1'])
        self.assertEqual(result['state'],'skipped_control_output')
        self.assertFalse(any(c.args[0]=='sends' for c in self.request.call_args_list))


if __name__=='__main__':unittest.main()
