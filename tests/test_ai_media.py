import base64
import io
import json
import unittest
from unittest.mock import patch, Mock, MagicMock
from PIL import Image
from ai_media import MediaReply, get_sticker
from ai_web import response_text, web_payload, generate_with_search
from native_images import image_bytes, send_image
from native_backend import key, NativeConnection
from types import SimpleNamespace


def png():
    out=io.BytesIO();Image.new('RGBA',(8,8),(0,0,0,0)).save(out,'PNG');return out.getvalue()


class MediaTests(unittest.TestCase):
    def test_generated_image_is_preserved_not_dropped_when_text_is_empty(self):
        encoded=base64.b64encode(png()).decode()
        d={}
        reply=response_text({'status':'completed','output':[{'type':'image_generation_call','result':encoded}]},d,allow_media=True)
        self.assertIsInstance(reply,str)
        self.assertEqual(len(reply.images),1)
        self.assertEqual(d['image_count'],1)

    def test_transparent_sticker_has_white_background_after_upload_conversion(self):
        raw=image_bytes(base64.b64encode(png()).decode())
        self.assertEqual(Image.open(io.BytesIO(raw)).getpixel((0,0)),(255,255,255))

    def test_media_tools_are_not_enabled_without_permission(self):
        p=web_payload({'model':'test','mediaReplies':False},[{'role':'user','content':'hello'}])
        self.assertEqual([t['type'] for t in p['tools']],['web_search'])

    def test_enabled_media_tools_include_generation_and_online_stickers(self):
        p=web_payload({'model':'test','mediaReplies':True},[{'role':'user','content':'picture'}])
        self.assertIn('image_generation',[t['type'] for t in p['tools']])
        self.assertTrue(any(t.get('name')=='get_sticker' for t in p['tools']))

    def test_sticker_call_is_executed_and_attachment_retained(self):
        image=base64.b64encode(png()).decode()
        r={'status':'completed','output':[{'type':'function_call','name':'get_sticker','arguments':json.dumps({'mood':'laugh','caption':'哈哈'})}]}
        with patch('ai_web.get_sticker',return_value=MediaReply('哈哈',[image])) as sticker:
            reply=response_text(r,allow_media=True)
        sticker.assert_called_once_with('laugh','哈哈')
        self.assertEqual(len(reply.images),1)

    def test_invalid_sticker_cannot_become_arbitrary_url_or_file(self):
        with self.assertRaises(ValueError):get_sticker('../../private')

    def test_online_sticker_failure_falls_back_once_to_generation(self):
        from ai_media import StickerUnavailable
        function={'status':'completed','output':[{'type':'function_call','name':'get_sticker','arguments':'{"mood":"laugh","caption":"哈哈"}'}]}
        generated={'status':'completed','output':[{'type':'image_generation_call','result':base64.b64encode(png()).decode()}]}
        responses=[]
        for body in (function,generated):
            context=MagicMock();context.__enter__.return_value.read.return_value=json.dumps(body).encode();responses.append(context)
        with patch('ai_web.urllib.request.build_opener') as opener, patch('ai_web.get_sticker',side_effect=StickerUnavailable()):
            opener.return_value.open.side_effect=responses
            reply=generate_with_search({'endpoint':'https://example.test/v1/chat/completions','model':'test','mediaReplies':True},[{'role':'user','content':'表情'}])
            self.assertEqual(opener.return_value.open.call_count,2)
            fallback=json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertEqual([t['type'] for t in fallback['tools']],['image_generation'])
            self.assertEqual(len(reply.images),1)

    def test_automatic_image_send_uses_caller_idempotency_key(self):
        connection=SimpleNamespace(selected='friend',writable=NativeConnection.writable,info=lambda:{'id':'friend','kind':'direct'},request=Mock(return_value={'id':'job','state':'succeeded'}))
        with patch('native_images.image_bytes',return_value=b'png'),patch('native_images.binary',return_value=b'{"id":"upload"}'):
            result=send_image(connection,key('friend'),'encoded',request_id='stable-image-id')
        self.assertEqual(result['state'],'observed')
        self.assertEqual(connection.request.call_args.args[2],'stable-image-id')

    def test_pause_after_upload_prevents_send_submission(self):
        connection=SimpleNamespace(selected='friend',writable=NativeConnection.writable,info=lambda:{'id':'friend','kind':'direct'},request=Mock())
        with patch('native_images.image_bytes',return_value=b'png'),patch('native_images.binary',return_value=b'{"id":"upload"}'):
            result=send_image(connection,key('friend'),'encoded',should_stop=Mock(side_effect=[False,True]))
        self.assertEqual(result['state'],'not_sent')
        connection.request.assert_not_called()

    def test_pause_before_image_upload_sends_nothing(self):
        connection=SimpleNamespace(selected='friend')
        result=send_image(connection,'unused','unused',should_stop=lambda:True)
        self.assertEqual(result['state'],'not_sent')


if __name__ == '__main__':unittest.main()
