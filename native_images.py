"""Bounded native image transfer; no clipboard, file dialogs, or desktop input."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
import uuid

from PIL import Image, ImageOps


def image_bytes(encoded):
    if not isinstance(encoded, str) or len(encoded) > 11184820:
        raise ValueError('请选择 8 MB 以内的 PNG、JPEG 或 WebP 图片。')
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise ValueError('图片超过 8 MB。')
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 24000000:
            raise ValueError('图片格式或尺寸不支持。')
        source.load()
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        picture = Image.new('RGB', rgba.size, 'white')
        picture.paste(rgba, mask=rgba.getchannel('A'))
    out = io.BytesIO()
    picture.save(out, 'PNG')
    if out.tell() > 32 * 1024 * 1024:
        raise ValueError('图片解码后过大。')
    return out.getvalue()


def binary(connection, path, body=None, content_type=None):
    headers = {'Authorization': 'Bearer ' + (connection.root / 'private-data/api-token').read_text().strip()}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(connection.base + path, data=body, headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=30) as response:
        raw = response.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('图片资源过大。')
    return raw


class Previews:
    def __init__(self, connection):
        self.connection = connection
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='native-image')
        self.tasks = {}
        self.cache = {}
        self.retry_after = {}

    def fetch(self, message):
        q = urllib.parse.quote(message, safe='')
        items = self.connection.request('messages/' + q + '/media')['items']
        available = [a for a in items if a.get('state') == 'available' and a.get('kind') == 'image']
        if not available:
            job = self.connection.request('messages/' + q + '/media-transfers',
                                          {'messageId': message, 'quality': 'best'})
            deadline = time.monotonic() + 20
            while job.get('state') in ('queued', 'running', 'preparing', 'downloading') and time.monotonic() < deadline:
                time.sleep(.5)
                job = self.connection.request('jobs/' + urllib.parse.quote(job['id'], safe=''))
            if not job.get('assetId'):
                raise ValueError('图片暂不可用。')
            available = [self.connection.request('media/' + urllib.parse.quote(job['assetId'], safe=''))]
        asset = min(available, key=lambda a: {'original': 0, 'standard': 1, 'thumbnail': 2}.get(a.get('actualVariant'), 3))
        raw = binary(self.connection, 'media/' + urllib.parse.quote(asset['id'], safe='') + '/content')
        if asset.get('sha256') and hashlib.sha256(raw).hexdigest() != asset['sha256']:
            raise ValueError('图片校验失败。')
        with Image.open(io.BytesIO(raw)) as picture:
            if picture.width * picture.height > 24000000:
                raise ValueError('图片尺寸过大。')
            picture = ImageOps.exif_transpose(picture).convert('RGB')
            picture.thumbnail((1600, 1200))
            out = io.BytesIO()
            picture.save(out, 'JPEG', quality=88)
        return 'data:image/jpeg;base64,' + base64.b64encode(out.getvalue()).decode('ascii')

    def enrich(self, rows):
        for ident, future in list(self.tasks.items()):
            if future.done():
                try:
                    self.cache[ident] = future.result()
                    while len(self.cache) > 32:
                        self.cache.pop(next(iter(self.cache)))
                except Exception:
                    self.retry_after[ident] = time.monotonic() + 30
                del self.tasks[ident]
        for row in [r for r in rows if r.get('kind') == 'image'][-24:]:
            ident = row['id']
            if ident in self.cache:
                row.update(image=self.cache[ident], imagePending=False, imageUnavailable=False)
            elif self.retry_after.get(ident, 0) > time.monotonic():
                row['imagePending'] = False
                row['imageUnavailable'] = True
            else:
                row['imagePending'] = True
                if ident not in self.tasks and len(self.tasks) < 4:
                    self.tasks[ident] = self.pool.submit(self.fetch, ident)
        return rows

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


def send_image(connection, binding, encoded, request_id=None, should_stop=None):
    from native_backend import key
    recipient = connection.selected
    if should_stop and should_stop():
        return {'state': 'not_sent', 'detail': '已暂停，未发送图片。'}
    if not connection.selected or key(connection.selected) != binding:
        return {'state': 'not_sent', 'detail': '会话已变化，未发送图片。'}
    if not connection.writable(connection.info()):
        return {'state': 'not_sent', 'detail': '当前对象不可发送图片。'}
    try:
        raw = image_bytes(encoded)
        boundary = 'workdesk-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="image.png"\r\n'
                'Content-Type: image/png\r\n\r\n').encode() + raw + f'\r\n--{boundary}--\r\n'.encode()
        upload = json.loads(binary(connection, 'uploads', body, 'multipart/form-data; boundary=' + boundary))
    except Exception:
        return {'state': 'not_sent', 'detail': '图片校验或上传失败，尚未提交发送，可重试。'}
    if (should_stop and should_stop()) or connection.selected != recipient or key(recipient) != binding:
        return {'state': 'not_sent', 'detail': '上传期间会话已变化，未发送图片。'}
    try:
        job = connection.request('sends', {'threadId': recipient, 'kind': 'image', 'sourceId': upload['id']},
                                 request_id or 'workdesk-image-' + str(uuid.uuid4()))
        deadline = time.monotonic() + 90
        while job.get('state') in ('queued', 'running', 'preparing', 'uploading', 'submitting') and time.monotonic() < deadline:
            time.sleep(.3)
            job = connection.request('jobs/' + urllib.parse.quote(job['id'], safe=''))
        if job.get('state') in ('succeeded', 'completed', 'accepted'):
            connection.history = False
            return {'state': 'observed', 'detail': '后台图片发送任务已完成；不代表对方已读。'}
    except Exception:
        pass
    return {'state': 'unknown', 'detail': '图片发送结果暂未确认，请查看会话，勿重复发送。'}
