"""Prefer UIA; use local OCR only when native text controls are unavailable."""
from bridge import Bridge, BridgeError, windows, walk
import time


def ai_interaction_ready():
    """Automatic UI changes only when WeChat is already foreground and input idle."""
    import ctypes
    from ctypes import wintypes
    class LastInput(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]
    user = ctypes.WinDLL('user32')
    user.GetForegroundWindow.restype = wintypes.HWND
    handles = windows()
    if len(handles) != 1 or user.GetForegroundWindow() != handles[0]:
        return False
    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not user.GetLastInputInfo(ctypes.byref(info)):
        return False
    elapsed = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xffffffff
    return elapsed >= 2000


def require_ai_interaction():
    if not ai_interaction_ready():
        raise BridgeError('正在让出前台供你办公；仅检测消息，等待微信在前台且键鼠空闲后回复。')


def service_page(layout):
    return any(n.ClassName == 'mmui::BizMenuButton' or n.AutomationId.endswith('brand_profile_button')
               for n in layout.get('nodes', []))


class Connection:
    def __init__(self):
        self.uia = Bridge()
        self.ocr = None
        self.active = self.uia
        self.next_uia_probe = 0
        self.ai_drafts = {}

    def _clear_ai_draft(self, layout):
        owned = getattr(self, 'ai_drafts', {}).get(layout['name'])
        if not owned or layout.get('blocked') or not layout.get('editor'):
            return
        binding, text = owned
        if layout['binding'] != binding:
            return
        value = self.uia._pattern(layout['editor'], 'ValuePattern')
        if not value:
            return
        if value.Value == text:
            # Recheck the exact value inside clear_draft immediately before mutation.
            self.uia.clear_draft(binding, expected=text)
        # An empty or edited draft is no longer ours; never erase user edits.
        self.ai_drafts.pop(layout['name'], None)

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

    def navigate_back(self):
        result = self.uia.navigate_back()
        self.active = self.uia
        return result

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

    def ai_scan(self):
        try:
            layout = self.uia._layout()
        except BridgeError:
            return {'available': False, 'detail': '等待普通聊天页面；后台检测不会自动切页或恢复窗口。'}
        if layout.get('blocked') or not layout.get('sessions'):
            return {'available': False}
        back = [n for n in layout.get('nodes', []) if n.ClassName == 'mmui::ChatBackwardView' and n.Name == '返回']
        if len(back) == 1:
            return {'available': False, 'detail': '当前在子目录，请手动返回；后台不会反复点击返回。'}
        current = layout['name'] if layout.get('editor') and layout.get('messages') and not service_page(layout) else None
        return {'available': True, 'current': current,
                'sessions': [{k:v for k,v in s.items() if k != 'control'}
                             for s in self.uia._sessions(layout)]}

    def ai_observe(self, name, permit):
        # Never use OCR-only text to drive unattended sends.
        with permit():
            layout = self.uia._layout()
            if self.uia.search_query:
                self.uia._search_editor(layout).SetValue('', waitTime=0)
                self.uia.search_query = ''
                self.uia.search_results = {}
                layout = self.uia._layout()
            sessions = [s for s in self.uia._sessions(layout) if s['name'] == name]
            if len(sessions) != 1:
                return {'available': False, 'detail': '联系人不在最近会话中或名称重复；请手动打开会话后重新启用。'}
            if layout['name'] != name:
                self.uia.select(sessions[0]['id'])
                selected = self.uia._layout()
                if selected['name'] == name and selected.get('messages'):
                    self.uia.scroll_history(selected['binding'], 'latest')
        with permit():
            layout = self.uia._layout()
            if service_page(layout) or (layout['name'] == name and not layout.get('editor')):
                return {'available': False, 'unsupported': True}
            if layout['name'] != name or layout.get('blocked') or not layout.get('messages'):
                raise BridgeError('未确认接管会话，已暂停。')
            self._clear_ai_draft(layout)
        from ai_observation import records
        rows = records(self.uia, layout)
        value = self.uia._pattern(layout['editor'], 'ValuePattern')
        return {'available': True, 'name': name, 'binding': layout['binding'],
                'records': rows, 'hasDraft': bool(value and value.Value)}

    def ai_deliver(self, name, binding, expected, text, permit):
        from ai_observation import records
        from ai_reply import signature, text_tail
        with permit():
            layout = self.uia._layout()
            if layout.get('blocked') or service_page(layout):
                return {'state': 'stale'}
            if layout['name'] != name:
                matches = [s for s in self.uia._sessions(layout) if s['name'] == name]
                if len(matches) != 1:
                    return {'state': 'stale'}
                self.uia.select(matches[0]['id'])
                layout = self.uia._layout()
                if layout['name'] != name or layout.get('blocked') or not layout.get('messages'):
                    return {'state': 'stale'}
                self.uia.scroll_history(layout['binding'], 'latest')
                layout = self.uia._layout()
            if layout['name'] != name or not layout.get('messages') or service_page(layout):
                return {'state': 'stale'}
            binding = layout['binding']
        rows = records(self.uia, layout)
        if signature(rows) != expected or text_tail(rows).get('direction') != 'incoming':
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
        def own_draft(written_binding, written_text):
            if not hasattr(self, 'ai_drafts'):
                self.ai_drafts = {}
            self.ai_drafts[name] = (written_binding, written_text)
        try:
            return self.uia.send(binding, text, guard=unchanged, preserve_draft=True,
                                 on_draft_written=own_draft)
        finally:
            # Cleanup must not replace the send outcome (especially an unknown click).
            # If temporarily unreadable or paused, retry cleanup on the next observation.
            try:
                with permit():
                    self._clear_ai_draft(self.uia._layout())
            except Exception:
                pass

    def close(self):
        self.uia.close()
        if self.ocr:
            self.ocr.close()
