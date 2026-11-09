"""Prefer UIA; use local OCR only when native text controls are unavailable."""
from bridge import Bridge, BridgeError
import time


class Connection:
    def __init__(self):
        self.uia = Bridge()
        self.ocr = None
        self.active = self.uia
        self.next_uia_probe = 0

    def snapshot(self):
        if self.active is self.uia or self.ocr is None or time.monotonic() >= self.next_uia_probe:
            self.next_uia_probe = time.monotonic() + 12
            state = self.uia.snapshot()
            if state.get('connected'):
                self.active = self.uia
                return state
            if self.ocr is None:
                from ocr_bridge import OCRBridge
                self.ocr = OCRBridge()
        self.active = self.ocr
        return self.ocr.snapshot()

    def send(self, binding, text):
        return self.active.send(binding, text)

    def select(self, session_id):
        return self.active.select(session_id)

    def search(self, query):
        if self.active is not self.uia:
            raise BridgeError('当前仅有 OCR 接口，联系人搜索暂不可用。请重新连接检查文字控件。')
        return self.uia.search(query)

    def send_image(self, binding, encoded):
        if self.active is not self.uia:
            raise BridgeError('当前只有 OCR 接口，图片发送不可用。')
        return self.uia.send_image(binding, encoded)

    def scroll_history(self, binding, direction):
        if self.active is not self.uia:
            raise BridgeError('当前仅有 OCR 接口，历史滚动暂不可用。')
        return self.uia.scroll_history(binding, direction)

    def open_native(self):
        return self.uia.open_native()

    def ai_observe(self, name, permit):
        # Never use OCR-only text to drive unattended sends.
        with permit():
            layout = self.uia._layout()
            sessions = [s for s in self.uia._sessions(layout) if s['name'] == name]
            if len(sessions) != 1:
                return {'available': False, 'detail': '联系人不在最近会话中或名称重复；请手动打开会话后重新启用。'}
            if layout['name'] != name:
                self.uia.select(sessions[0]['id'])
        with permit():
            layout = self.uia._layout()
            if layout['name'] != name or layout.get('blocked') or not layout.get('messages'):
                raise BridgeError('未确认接管会话，已暂停。')
        from ai_observation import records
        rows = records(self.uia, layout)
        value = self.uia._pattern(layout['editor'], 'ValuePattern')
        return {'available': True, 'name': name, 'binding': layout['binding'],
                'records': rows, 'hasDraft': bool(value and value.Value)}

    def ai_deliver(self, name, binding, expected, text, permit):
        from ai_observation import records
        from ai_reply import signature
        with permit():
            layout = self.uia._layout()
            if layout['binding'] != binding or layout['name'] != name or layout.get('blocked'):
                return {'state': 'stale'}
        rows = records(self.uia, layout)
        if signature(rows) != expected or not rows or rows[-1].get('direction') != 'incoming':
            return {'state': 'stale'}
        raw = self.uia._records(layout)
        from contextlib import contextmanager
        @contextmanager
        def unchanged():
            with permit():
                current = self.uia._layout()
                if current['binding'] != binding or self.uia._records(current) != raw:
                    raise BridgeError('回复前对象或消息已改变，已取消。')
                yield
        return self.uia.send(binding, text, guard=unchanged, preserve_draft=True)

    def close(self):
        self.uia.close()
        if self.ocr:
            self.ocr.close()
