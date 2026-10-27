"""Loopback-only project workdesk; chat payloads are never written to disk."""
import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import webbrowser

ROOT = Path(__file__).resolve().parent
PORT = 18765


def runtime_dir(port=PORT):
    if getattr(sys, 'frozen', False):
        return Path(os.environ['LOCALAPPDATA']) / 'Workdesk' / 'runtime' / str(port)
    return ROOT / '.runtime'


class Service:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='workdesk-uia')
        self.bridge = None
        self.sends = {}
        self.read_future = None
        self.action_future = None

    def call(self, method, *args):
        try:
            if self.bridge is None:
                # Import and initialize COM exclusively on the same worker as all UIA calls.
                from connection import Connection
                self.bridge = Connection()
            return getattr(self.bridge, method)(*args)
        except Exception as error:
            from bridge import BridgeError
            if isinstance(error, BridgeError):
                return {'error': str(error), 'state': 'rejected'}
            return {'error': '连接操作失败，请在原窗口检查后重新连接。'}

    def read(self):
        with self.lock:
            if self.read_future is None or self.read_future.done():
                self.read_future = self.worker.submit(self.call, 'snapshot')
            return self.read_future

    def action(self, method, *args):
        with self.lock:
            if self.action_future is not None and not self.action_future.done():
                raise ValueError('上一项操作仍在进行，请稍后检查结果。')
            self.action_future = self.worker.submit(self.call, method, *args)
            return self.action_future

    def send(self, request_id, binding, text, kind='text'):
        fingerprint = hashlib.sha256((kind + '\0' + binding + '\0' + text).encode()).hexdigest()
        with self.lock:
            if request_id in self.sends:
                old_hash, future = self.sends[request_id]
                if old_hash != fingerprint:
                    raise ValueError('同一请求编号不能用于不同内容。')
                return future
            if len(self.sends) >= 2000:
                raise ValueError('本次运行的发送记录已满，请重启工作台。')
            if self.action_future is not None and not self.action_future.done():
                raise ValueError('上一项操作仍在进行，请先检查结果。')
            future = self.worker.submit(self.call, 'send_image' if kind == 'image' else 'send', binding, text)
            self.action_future = future
            self.sends[request_id] = fingerprint, future
            return future


class Handler(BaseHTTPRequestHandler):
    server_version = 'LocalDesk'

    def log_message(self, *_):
        pass

    def respond(self, code, value, content_type='application/json; charset=utf-8'):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
            self.wfile.flush()
            if code >= 400 and self.close_connection:
                # Deliver the rejection before closing a socket with an unread POST body.
                self.connection.shutdown(socket.SHUT_WR)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed(self, api=False):
        host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != host:
            self.respond(403, {'error': 'Host not allowed'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + host:
            self.respond(403, {'error': 'Origin not allowed'})
            return False
        supplied = self.headers.get('Authorization', '')
        if api and not secrets.compare_digest(supplied, 'Bearer ' + self.server.service.token):
            self.respond(401, {'error': '连接凭据已失效，请从“启动工作台”重新打开。'})
            return False
        return True

    def do_GET(self):
        if not self.allowed(api=self.path.startswith('/api/')):
            return
        if self.path == '/api/health':
            self.respond(200, {'app': 'project-workdesk', 'version': 1})
            return
        if self.path == '/api/state':
            try:
                self.respond(200, self.server.service.read().result(timeout=9))
            except TimeoutError:
                self.respond(503, {'error': '微信界面响应较慢，请稍后刷新。'})
            return
        if self.path == '/api/send-status':
            self.respond(405, {'error': 'Use POST'})
            return
        if self.path == '/health':
            self.respond(200, {'app': 'project-workdesk', 'version': 1})
            return
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8'), '/icon.svg': ('icon.svg', 'image/svg+xml')}
        if self.path not in files:
            self.respond(404, {'error': 'Not found'})
            return
        name, content_type = files[self.path]
        self.respond(200, (ROOT / 'web' / name).read_bytes(), content_type)

    def do_POST(self):
        if not self.allowed(api=True):
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.respond(415, {'error': 'JSON required'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            maximum = 12 * 1024 * 1024 if self.path == '/api/send-image' else 65536
            if length <= 0 or length > maximum:
                raise ValueError('请求长度无效。')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('请求格式无效。')
            service = self.server.service
            if self.path in ('/api/send', '/api/send-image'):
                request_id, binding, text = (data.get(k) for k in ('requestId', 'binding', 'text'))
                if not isinstance(request_id, str) or not 16 <= len(request_id) <= 80:
                    raise ValueError('请求编号无效。')
                if not isinstance(binding, str) or len(binding) != 24:
                    raise ValueError('请先连接并核对当前对象。')
                if self.path == '/api/send-image':
                    encoded = data.get('image')
                    if not isinstance(encoded, str) or not encoded or len(encoded) > 11184820:
                        raise ValueError('图片内容无效。')
                    future = service.send(request_id, binding, encoded, kind='image')
                else:
                    if not isinstance(text, str) or not text.strip() or len(text) > 4000 or '\0' in text:
                        raise ValueError('请输入 1–4000 个字符，不支持空消息。')
                    future = service.send(request_id, binding, text)
            elif self.path == '/api/send-status':
                with service.lock:
                    entry = service.sends.get(data.get('requestId'))
                if not entry:
                    self.respond(404, {'error': '本次进程未找到该请求。请核对原窗口后再决定是否重发。'})
                    return
                future = entry[1]
            elif self.path == '/api/history':
                binding, direction = data.get('binding'), data.get('direction')
                if not isinstance(binding, str) or len(binding) != 24 or direction not in ('older', 'newer', 'latest'):
                    raise ValueError('请先连接会话，再选择翻页方向。')
                future = service.action('scroll_history', binding, direction)
            elif self.path == '/api/select':
                if not isinstance(data.get('id'), str):
                    raise ValueError('请选择项目。')
                future = service.action('select', data['id'])
            elif self.path == '/api/search':
                query = data.get('query')
                if not isinstance(query, str) or len(query) > 80 or any(ord(c) < 32 for c in query):
                    raise ValueError('搜索内容无效。')
                future = service.action('search', query.strip())
            elif self.path == '/api/native':
                future = service.action('open_native')
            elif self.path == '/api/stop':
                self.respond(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                self.respond(404, {'error': 'Not found'})
                return
            try:
                result = future.result(timeout=9)
                self.respond(409 if 'error' in result else 200, result)
            except TimeoutError:
                self.respond(202, {'state': 'pending', 'detail': '操作仍在进行，不要重复发送。可点“检查上次发送”。'})
        except (ValueError, TypeError, json.JSONDecodeError):
            self.respond(400, {'error': '请求无效或上一项操作未完成，请检查内容后稍候重试。'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    runtime = runtime_dir(args.port)
    runtime.mkdir(parents=True, exist_ok=True)
    service = Service()
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError:
        # Do not trust a process that merely happens to own the port.
        service.worker.shutdown(wait=False)
        raise SystemExit('端口被占用。请关闭旧工作台，或用 --port 指定其他端口。')
    server.daemon_threads = True
    server.service = service
    url = f'http://127.0.0.1:{server.server_port}/#key={service.token}'
    # Credential is local to this OS account; no chats or message drafts in runtime files.
    (runtime / 'session.json').write_text(json.dumps({'url': url, 'pid': os.getpid()}), encoding='utf-8')
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if service.bridge and hasattr(service.bridge, 'close'):
            service.worker.submit(service.bridge.close).result(timeout=8)
        service.worker.shutdown(wait=False, cancel_futures=True)
        session = runtime / 'session.json'
        try:
            saved = json.loads(session.read_text(encoding='utf-8'))
            if saved['pid'] == os.getpid():
                session.unlink()
        except (OSError, ValueError, KeyError):
            pass


if __name__ == '__main__':
    main()
