"""Bounded native attachment transfer and inert document text extraction."""
import base64
import hashlib
import io
import json
from pathlib import PurePosixPath
import time
import urllib.parse
import uuid
import zipfile
from xml.etree import ElementTree as ET

from native_images import binary

MAX_FILE = 8 * 1024 * 1024


def is_file(row):
    return row.get('type') == 49 and row.get('appMessageType') == 6 and not row.get('recall')


def safe_name(name):
    name = PurePosixPath(str(name or 'attachment.bin').replace('\\', '/')).name
    return ''.join(c for c in name if c.isalnum() or c in ' ._-')[:160].strip(' .') or 'attachment.bin'


def fetch_file(connection, message, thread):
    q = urllib.parse.quote(message, safe='')
    row = connection.request('messages/' + q)
    if row.get('threadId') != thread or not is_file(row):
        raise ValueError('附件不属于当前会话或已撤回。')
    items = connection.request('messages/' + q + '/media')['items']
    files = [a for a in items if a.get('kind') == 'file']
    if not files:
        raise ValueError('没有可下载文件。')
    asset = files[0]
    size = asset.get('byteLength') or asset.get('advertisedByteLength')
    if not isinstance(size, int) or not 0 <= size <= MAX_FILE:
        raise ValueError('文件大小未知或超过 8 MB。')
    if asset.get('state') != 'available':
        job = connection.request('messages/' + q + '/media-transfers', {'messageId': message, 'quality': 'best'})
        deadline = time.monotonic() + 45
        while job.get('state') in ('queued', 'running', 'preparing', 'downloading') and time.monotonic() < deadline:
            time.sleep(.3)
            job = connection.request('jobs/' + urllib.parse.quote(job['id'], safe=''))
        if not job.get('assetId'):
            raise ValueError('文件尚未下载完成。')
        asset = connection.request('media/' + urllib.parse.quote(job['assetId'], safe=''))
    if asset.get('kind') != 'file' or asset.get('byteLength', MAX_FILE + 1) > MAX_FILE:
        raise ValueError('文件资源不符合限制。')
    raw = binary(connection, 'media/' + urllib.parse.quote(asset['id'], safe='') + '/content')
    if len(raw) > MAX_FILE or len(raw) != asset.get('byteLength') or not asset.get('sha256') or hashlib.sha256(raw).hexdigest() != asset['sha256']:
        raise ValueError('文件完整性校验失败。')
    return safe_name(asset.get('filename')), raw


def document_text(name, raw):
    extension = PurePosixPath(name).suffix.lower()
    if len(raw) > MAX_FILE:
        raise ValueError('文件超过 8 MB。')
    if extension in ('.pdf', '.xlsx', '.pptx'):
        from native_documents import office_text, pdf_text
        text = pdf_text(raw) if extension == '.pdf' else office_text(extension, raw)
    elif extension == '.docx':
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            part = z.getinfo('word/document.xml')
            if part.file_size > 4 * 1024 * 1024:
                raise ValueError('文档解压后正文过大。')
            xml = z.read(part)
            if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
                raise ValueError('不支持文档中的实体声明。')
            root = ET.fromstring(xml)
            ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            text = '\n'.join(''.join(p.itertext()) for p in root.iter(ns + 'p'))
    elif extension in {'.txt', '.md', '.csv', '.json', '.log', '.py', '.c', '.h', '.cpp', '.js', '.ts', '.yaml', '.yml', '.xml', '.ini', '.conf'}:
        text = None
        for encoding in ('utf-8-sig', 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8', 'gb18030'):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeError:
                pass
        if text is None or '\x00' in text:
            raise ValueError('文件不是可读取的文本。')
    else:
        return '此文件格式暂不支持解析。请如实告知对方，不能声称已阅读附件内容。'
    if not text.strip():
        return '未提取到正文。文档可能只有图片；不能声称已读懂。'
    return text[:12000] + ('\n[内容已截断，仅提供前 12000 字符]' if len(text) > 12000 else '')


def send_file(connection, binding, payload, request_id=None, should_stop=None):
    from native_backend import key
    recipient = connection.selected
    if should_stop and should_stop():
        return {'state': 'not_sent', 'detail': '已暂停，未发送文件。'}
    try:
        writable = recipient and key(recipient) == binding and connection.writable(connection.info())
    except Exception:
        return {'state': 'not_sent', 'detail': '会话查询失败，尚未提交文件发送。'}
    if not writable:
        return {'state': 'not_sent', 'detail': '当前会话不可发送文件。'}
    try:
        data = json.loads(payload)
        name = safe_name(data['name'])
        raw = base64.b64decode(data['data'], validate=True)
        if not 0 < len(raw) <= MAX_FILE:
            raise ValueError('文件大小无效。')
        boundary = 'workdesk-' + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + raw + f'\r\n--{boundary}--\r\n'.encode()
        upload = json.loads(binary(connection, 'uploads', body, 'multipart/form-data; boundary=' + boundary))
    except Exception:
        return {'state': 'not_sent', 'detail': '文件校验或上传失败，未提交发送。'}
    if connection.selected != recipient or (should_stop and should_stop()):
        return {'state': 'not_sent', 'detail': '会话已变化，未发送文件。'}
    try:
        job = connection.request('sends', {'threadId': recipient, 'kind': 'file', 'sourceId': upload['id']}, request_id or 'workdesk-file-' + str(uuid.uuid4()))
        deadline = time.monotonic() + 90
        while job.get('state') in ('queued', 'running', 'preparing', 'uploading', 'submitting') and time.monotonic() < deadline:
            time.sleep(.3)
            job = connection.request('jobs/' + urllib.parse.quote(job['id'], safe=''))
        if job.get('state') in ('succeeded', 'completed', 'accepted'):
            return {'state': 'observed', 'detail': '文件发送任务已完成，不代表对方已打开。'}
        return {'state': 'unknown', 'detail': '发送尚未确认，请勿重复发送。', 'jobId': job.get('id')}
    except Exception:
        return {'state': 'unknown', 'detail': '发送结果未知，请勿重复发送。'}
