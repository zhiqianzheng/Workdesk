"""Bounded image replies and online OpenMoji assets; no arbitrary file access."""
import base64
import io
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
        'description':'从网上获取一张适合聊天的现成表情图片（OpenMoji）。这是主动聊天反应工具：报喜庆祝、接梗、轻松附和时可直接调用，不需要对方提出发图请求。按语境选择，不按次数或概率发图；定制梗图、熊猫头等使用 image_generation。',
        'strict':True, 'parameters':{'type':'object', 'properties':{
            'mood':{'type':'string','enum':list(STICKERS)},
            'caption':{'type':'string','description':'兼容字段，表情只发图片，此处填空字符串。'}},
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
    # Keep the asset attribution in the image, without posting a second chat message.
    from PIL import Image, ImageDraw
    verified=image_bytes(base64.b64encode(raw).decode('ascii'))
    with Image.open(io.BytesIO(verified)) as original:
        picture=original.convert('RGB')
        canvas=Image.new('RGB',(max(picture.width,420),picture.height+32),'white')
        canvas.paste(picture,((canvas.width-picture.width)//2,0))
        draw=ImageDraw.Draw(canvas)
        draw.text((5,picture.height+2),'OpenMoji (credit footer added) | CC BY-SA 4.0',fill='#555555')
        draw.text((5,picture.height+16),'openmoji.org | creativecommons.org/licenses/by-sa/4.0',fill='#555555')
        out=io.BytesIO();canvas.save(out,format='PNG')
    encoded=image_result(base64.b64encode(out.getvalue()).decode('ascii'))
    return MediaReply('',[encoded])
