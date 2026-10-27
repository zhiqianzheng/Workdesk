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

    def close(self):
        self.uia.close()
        if self.ocr:
            self.ocr.close()
