"""Optional dedicated image endpoint, independent of the chat model and key."""
import json
import re
import urllib.request
import urllib.error
import urllib.parse
from host_runtime import data_home


def settings():
    path = data_home() / 'agent/private-data/image-provider.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('独立生图配置格式无效。')
    url = urllib.parse.urlsplit(value.get('endpoint', ''))
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('独立生图接口地址无效。')
    if not isinstance(value.get('model'), str) or not value['model'] or not value.get('encryptedKey'):
        raise ValueError('独立生图配置不完整。')
    return value


def explicit_request(text):
    if re.search(r'(不要|不用|别).{0,10}(画|生图|图片|配图)', text):
        return False
    # Requests bypass the chat endpoint; ordinary image-related discussion does not.
    return bool(re.search(r'(?:^|[，。！!\n])\s*(?:请|帮我|给我|麻烦)?\s*(?:画(?:一[张幅个])?|生成(?:一[张幅个])?|制作一张|做一张).{0,60}(?:图|插画|海报|照片|示意|猫|狗|机器人)', text)
                or re.search(r'^(?:please\s+)?(?:draw|generate|create)\s+(?:an?\s+)?(?:image|picture|illustration|poster)\b', text, re.I))


def tool():
    return {'type': 'function', 'name': 'generate_image',
            'description': '生成一张定制图片并由工作台发送。提供完整画面描述，不要仅给文字方案。',
            'strict': True, 'parameters': {'type': 'object', 'properties': {
                'prompt': {'type': 'string', 'description': '需要生成的画面、风格和构图。'}},
                'required': ['prompt'], 'additionalProperties': False}}


def generate_image(prompt, config=None):
    from ai_reply import protect
    from ai_web import NoRedirect
    from ai_media import MediaReply, image_result
    config = config or settings()
    if not config or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
        raise ValueError('生图配置或画面描述无效。')
    body = {'model': config['model'], 'prompt': prompt, 'n': 1, 'size': '1024x1024'}
    headers = {'Authorization': 'Bearer ' + protect(config['encryptedKey'], decrypt=True),
               'Content-Type': 'application/json', 'User-Agent': 'Workdesk/1.1',
               'x-openai-actor-authorization': 'local-image-extension'}
    request = urllib.request.Request(config['endpoint'], data=json.dumps(body, ensure_ascii=False).encode(), headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=240) as response:
            raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError('生图接口返回内容过大。')
        value = json.loads(raw)
        encoded = value['data'][0]['b64_json']
        return MediaReply('按你的要求生成了一张图。', [image_result(encoded)])
    except urllib.error.HTTPError as error:
        raise ValueError('生图接口暂时失败（HTTP %s），未取得图片。' % error.code) from None
    except (OSError, KeyError, IndexError, TypeError) as error:
        raise ValueError('本次生图未完成或未返回可验证图片。') from None
