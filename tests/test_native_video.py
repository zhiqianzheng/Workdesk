import base64
import unittest
from unittest.mock import Mock, patch
from native_video import is_channels,channels_context,frames_from_mp4,fetch_video
from native_ai_context import context_for,replyable
from ai_reply import generate


class NativeVideoTests(unittest.TestCase):
    def test_channels_placeholder_is_metadata_not_a_playable_video(self):
        row={'id':'card','type':49,'appMessageType':51,'direction':'incoming','createdAt':'2026-01-01',
             'link':{'description':'合成文案','sourceName':'合成作者','url':'https://support.weixin.qq.com/update/'}}
        self.assertTrue(is_channels(row));self.assertTrue(replyable(row))
        with patch('native_ai_context.Previews'),patch('native_ai_context.fetch_video') as fetch:
            result=context_for([row],[row],None,None,None,video_enabled=True)
        fetch.assert_not_called()
        self.assertIn('未取得视频或音频',result[0]['text'])
        self.assertIn('合成文案',result[0]['text'])
        self.assertNotIn('https://support.weixin',result[0]['text'])

    def test_invalid_or_non_mp4_data_is_not_executed(self):
        for raw in [b'',b'http://example.test/video',b'#EXTM3U\nhttp://private']:
            with patch('native_video.ffmpeg_executable') as executable:
                with self.assertRaises(ValueError):frames_from_mp4(raw)
            executable.assert_not_called()

    def test_disabled_video_analysis_does_not_download(self):
        row={'id':'v','type':43,'direction':'incoming','createdAt':'2026-01-01'}
        with patch('native_ai_context.Previews'),patch('native_ai_context.fetch_video') as fetch:
            result=context_for([row],[row],None,None,None)
        fetch.assert_not_called();self.assertIn('尚未开启',result[0]['text'])

    def test_wrong_thread_is_rejected_before_video_download(self):
        c=Mock();c.request.return_value={'type':43,'threadId':'other'}
        with patch('native_video.binary') as read:
            with self.assertRaises(ValueError):fetch_video(c,{'id':'v','threadId':'friend'})
        read.assert_not_called()

    def test_visual_frames_reach_responses_with_audio_limit_instruction(self):
        frame='data:image/jpeg;base64,'+base64.b64encode(b'synthetic').decode()
        record={'kind':'video','direction':'incoming','images':[frame]*4,'text':'抽帧分析，不含声音'}
        with patch('ai_web.generate_with_search',return_value='根据抽帧画面…') as model:
            generate({'style':'简短','webSearch':True},[record])
        content=model.call_args.args[1][-1]['content']
        self.assertEqual(sum(p['type']=='image_url' for p in content),4)
        self.assertIn('不含声音',content[0]['text'])
