"""Bounded image replies and online OpenMoji assets; no arbitrary file access."""
import base64
import urllib.request
from native_images import image_bytes


class MediaReply(str):
    def __new__(cls, text, images=()):
        result = super().__new__(cls, text)
        result.images = tuple(images)[:1]
        return result


class StickerUnavailable(ValueError):
    pass


STICKERS = {'laugh':'1F602', 'happy':'1F600', 'sad':'1F622', 'love':'2764',
            'thumbs_up':'1F44D', 'think':'1F914', 'cat':'1F63A', 'angry':'1F621',
            'celebrate':'1F389', 'sleep':'1F634', 'ok':'1F44C', 'cry_laugh':'1F923'}


def image_result(encoded):
    # Decode and validate pixels before any upload or send can occur.
    return base64.b64encode(image_bytes(encoded)).decode('ascii')


def sticker_tool():
    return {'type':'function', 'name':'get_sticker',
        'description':'从网上获取一张适合聊天的现成表情图片（OpenMoji）。对方要简单表情图片时使用；定制梗图、熊猫头等使用 image_generation。',
        'strict':True, 'parameters':{'type':'object', 'properties':{
            'mood':{'type':'string','enum':list(STICKERS)},
            'caption':{'type':'string','description':'不超过60字的自然配文，不声称已发送。'}},
            'required':['mood','caption'], 'additionalProperties':False}}


def get_sticker(mood, caption=''):
    if mood not in STICKERS:
        raise ValueError('Unsupported sticker')
    url='https://raw.githubusercontent.com/hfg-gmuend/openmoji/master/color/618x618/'+STICKERS[mood]+'.png'
    try:
        with urllib.request.urlopen(url,timeout=20) as response:
            raw=response.read(2*1024*1024+1)
    except OSError:
        raise StickerUnavailable('在线表情暂不可用') from None
    if len(raw)>2*1024*1024:
        raise ValueError('Sticker too large')
    encoded=image_result(base64.b64encode(raw).decode('ascii'))
    text=(caption.strip()[:120] or '给你这个表情。')+'\n素材：OpenMoji · CC BY-SA 4.0 https://openmoji.org/'
    return MediaReply(text,[encoded])
