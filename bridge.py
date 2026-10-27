"""Local UI Automation adapter. No injection, database access, or foreground typing."""
import ctypes
from ctypes import wintypes
import hashlib
import os
import re
import time


class BridgeError(Exception):
    pass


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def contact_name(value):
    return ' '.join(value.split())


def session_details(label, name):
    """Parse the session's accessible summary; never infer counts from preview changes."""
    lines = [part.strip() for part in label.splitlines() if part.strip()]
    result = {'preview': '', 'unreadCount': None, 'unreadLabel': '', 'time': '', 'muted': False, 'draft': False}
    if not lines or contact_name(lines.pop(0)) != name:
        return result
    if lines and lines[0] in ('已置顶', '置顶', 'Pinned'):
        lines.pop(0)
    if lines and lines[-1] in ('消息免打扰', '已静音', 'Muted'):
        result['muted'] = True
        lines.pop()
    if lines and re.fullmatch(r'(?:\d{1,2}:\d{2}|(?:昨天|前天|星期[一二三四五六日天]|周[一二三四五六日天])(?:\s+\d{1,2}:\d{2})?|\d{2,4}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}月\d{1,2}日)', lines[-1]):
        result['time'] = lines.pop()
    preview = '\n'.join(lines)
    count = re.match(r'^\[(\d+)(\+?)条\]\s*', preview)
    if count:
        result['unreadCount'] = int(count[1])
        result['unreadLabel'] = count[1] + count[2]
        preview = preview[count.end():]
    result['preview'] = preview[:500]
    result['draft'] = preview.startswith(('[草稿]', '草稿：', '[Draft]'))
    return result


def windows():
    user = ctypes.WinDLL('user32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _):
        if not user.IsWindowVisible(hwnd) or user.GetWindow(hwnd, 4):
            return True
        size = user.GetWindowTextLengthW(hwnd)
        if not size:
            return True
        title = ctypes.create_unicode_buffer(size + 1)
        user.GetWindowTextW(hwnd, title, size + 1)
        if title.value not in ('微信', 'Weixin', 'WeChat'):
            return True
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                buf = ctypes.create_unicode_buffer(32768)
                count = wintypes.DWORD(len(buf))
                if kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(count)):
                    if os.path.basename(buf.value).lower() in ('weixin.exe', 'wechat.exe'):
                        result.append(int(hwnd))
            finally:
                kernel.CloseHandle(handle)
        return True

    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows(callback, 0)
    return result


def walk(root, depth=24, maximum=1800, skip_lists=False):
    stack = [(root, 0)]
    count = 0
    deadline = time.monotonic() + 5
    while stack:
        item, level = stack.pop()
        count += 1
        if count > maximum or time.monotonic() > deadline:
            raise BridgeError('界面读取超时；请关闭微信弹窗后重试。')
        yield item
        if level < depth and not (skip_lists and item.ControlTypeName == 'ListControl'):
            stack.extend((c, level + 1) for c in reversed(item.GetChildren()))


class Bridge:
    def __init__(self):
        import uiautomation as auto
        self.auto = auto
        auto.Logger.SetLogFile(os.devnull)
        auto.SetGlobalSearchTimeout(0.6)
        self.search_results = {}
        self.search_query = ''
        self.capture = None
        self.media_not_before = 0

    def _layout(self):
        candidates = windows()
        if not candidates:
            raise BridgeError('未找到已登录的微信主窗口。请打开微信并进入普通聊天。')
        if len(candidates) != 1:
            raise BridgeError('检测到多个微信窗口。请只保留一个已登录的主窗口。')
        hwnd = candidates[0]
        root = self.auto.ControlFromHandle(hwnd)
        nodes = list(walk(root, skip_lists=True))
        editors = [x for x in nodes if x.ClassName == 'mmui::ChatInputField' and x.ControlTypeName == 'EditControl']
        names = [x.Name for x in nodes if x.AutomationId.endswith('current_chat_name_label') and x.Name.strip()]
        message_lists = []
        session_lists = []
        for node in nodes:
            if node.ClassName == 'mmui::MessageView':
                message_lists.extend(x for x in walk(node, depth=3, maximum=300, skip_lists=True) if x.ControlTypeName == 'ListControl')
            if node.ClassName == 'mmui::ChatSessionList':
                session_lists.extend(x for x in walk(node, depth=3, maximum=150, skip_lists=True) if x.ControlTypeName == 'ListControl')
        blocked = any(n.ControlTypeName == 'WindowControl' and n != root
                      and n.Name not in ('微信', 'Weixin', 'WeChat') for n in nodes)
        if len(editors) != 1 or len(message_lists) != 1:
            if len(session_lists) == 1:
                # The subscription feed is an authenticated navigation page, not a lost UIA connection.
                name = contact_name(names[0]) if len(names) == 1 else '微信功能页面'
                return dict(hwnd=hwnd, root=root, nodes=nodes, blocked=blocked, name=name,
                            binding=digest(str(hwnd)+':navigation:'+name+':'+repr(root.GetRuntimeId())),
                            editor=None, messages=None, sessions=session_lists[0], send=None, chatAvailable=False)
            raise BridgeError('当前页面没有可用的聊天控件。请在微信选择普通聊天，再点重新连接。')
        editor = editors[0]
        name = names[0] if len(names) == 1 else editor.Name.strip()
        if not name or name in ('输入', '输入消息', '编辑', '微信', 'Input', 'Message'):
            raise BridgeError('无法可靠识别当前聊天对象，已停止连接。请在微信中选择一个普通聊天。')
        editor_name = editor.Name.strip().removesuffix('长按鼠标 语音输入').strip()
        if len(names) == 1 and editor_name and editor_name not in (name, '输入', '输入消息', '编辑', 'Input', 'Message'):
            raise BridgeError('聊天标题与输入框标识不一致，请回到微信确认对象后重试。')
        name = contact_name(name)
        buttons = [x for x in nodes if x.ControlTypeName == 'ButtonControl' and x.Name in ('发送(S)', '发送', 'Send', 'Send(S)')]
        binding = digest(str(hwnd) + ':' + name + ':' + repr(editor.GetRuntimeId()))
        blocked = any(n.ControlTypeName == 'WindowControl' and n != root
                      and n.Name not in ('微信', 'Weixin', 'WeChat') for n in nodes)
        return dict(hwnd=hwnd, root=root, nodes=nodes, blocked=blocked, name=name, binding=binding, editor=editor,
                    messages=message_lists[0], sessions=session_lists[0] if len(session_lists) == 1 else None,
                    send=buttons[0] if len(buttons) == 1 else None)

    def _pattern(self, control, name):
        return control.GetPattern(getattr(self.auto.PatternId, name)) if control else None

    def _records(self, layout):
        rows = []
        if layout['messages'] is None:
            return rows
        for item in layout['messages'].GetChildren()[-160:]:
            content = item.Name.strip()
            if not content:
                # Some versions expose text only in children. Preserve order, do not infer senders.
                parts = [c.Name for c in walk(item, depth=5, maximum=100) if c.ControlTypeName == 'TextControl' and c.Name]
                content = '\n'.join(dict.fromkeys(parts))
            if content:
                rows.append({'id': digest(repr(item.GetRuntimeId())), 'text': content[:20000]})
        return rows

    def _sessions(self, layout):
        result = []
        if layout['sessions']:
            for item in layout['sessions'].GetChildren()[:100]:
                identifier = item.AutomationId
                name = contact_name(identifier[len('session_item_'):]) if identifier.startswith('session_item_') else ''
                if not name.strip():
                    continue
                result.append({'id': digest(repr(item.GetRuntimeId())), 'name': name,
                               'key': digest(name), 'control': item, **session_details(item.Name, name)})
        return result

    def snapshot(self):
        try:
            return self._snapshot_from_layout(self._layout())
        except BridgeError as error:
            return {'connected': False, 'detail': str(error), 'sessions': [], 'records': [], 'canSend': False}
        except Exception:
            return {'connected': False, 'detail': '读取失败：微信可能最小化、退出或改变了界面。打开原窗口后重新连接。', 'sessions': [], 'records': [], 'canSend': False}

    def _snapshot_from_layout(self, layout, *, include_images=True, records=None):
        sessions = self._sessions(layout)
        if not layout.get('chatAvailable', True):
            detail = '当前是公众号或其他功能页面。可在左侧选择好友或群聊继续使用，无需重启服务。'
            can_search = any(n.ControlTypeName == 'EditControl' and n.Name in ('搜索', 'Search') for n in layout['nodes'])
            return {'connected': True, 'mode': 'uia', 'view': 'navigation',
                    'canSearch': can_search and not layout['blocked'], 'canHistory': False,
                    'detail': detail, 'sendNote': '此页面没有聊天输入框，请从左侧选择好友或群聊。',
                    'current': {'name': layout['name'], 'key': digest(layout['name']), 'binding': layout['binding']},
                    'records': [], 'sessions': [{k:v for k,v in item.items() if k != 'control'} for item in sessions],
                    'canSend': False, 'canSendImage': False, 'hasNativeDraft': False}
        value = self._pattern(layout['editor'], 'ValuePattern')
        duplicates = sum(s['name'] == layout['name'] for s in sessions) > 1
        can_send = bool(value and not value.IsReadOnly and layout['send'] and not duplicates and not layout['blocked'])
        return {'connected': True, 'mode': 'uia', 'canSearch': True, 'canHistory': not layout['blocked'],
                'detail': '当前窗口记录已读取；可搜索联系人并切换会话。',
                'current': {'name': layout['name'], 'key': digest(layout['name']), 'binding': layout['binding']},
                'records': self._media_records(layout) if include_images else self._history_records(layout, records),
                'sessions': [{k: v for k, v in s.items() if k != 'control'} for s in sessions],
                'canSend': can_send,
                'canSendImage': can_send,
                'sendNote': '' if can_send else '当前控件不支持可靠的后台发送，或会话名称重复。请使用“打开原窗口”。',
                'hasNativeDraft': bool(value and value.Value)}

    def select(self, session_id):
        layout = self._navigation_layout()
        if layout['blocked']:
            raise BridgeError('原窗口有未处理的对话框，请先关闭。')
        searched = session_id in self.search_results
        sessions = self._search_items(layout) if searched else self._sessions(layout)
        matches = [s for s in sessions if s['id'] == session_id]
        if len(matches) != 1:
            raise BridgeError('项目目录已变化，请刷新后重新选择。')
        selected = matches[0]
        if sum(s['name'] == selected['name'] for s in sessions) != 1:
            raise BridgeError('存在同名会话，请在原窗口确认目标。')
        if selected['name'] == layout['name'] and not searched:
            return self.snapshot()
        self._click_item(layout, selected['control'])
        self.media_not_before = time.monotonic()
        updated = None
        for _ in range(12):
            time.sleep(.15)
            try:
                candidate = self._layout()
                if contact_name(candidate['name']) == selected['name']:
                    updated = candidate
                    break
            except BridgeError:
                # Qt can briefly expose neither page while replacing the feed with a chat.
                continue
        if updated is None:
            raise BridgeError('尚未确认切换成功。请在原窗口确认，不会向旧会话发送。')
        if searched:
            self._search_editor(updated).SetValue('', waitTime=0)
            self.search_query = ''
            self.search_results = {}
        return self.snapshot()

    def _navigation_layout(self):
        handles = windows()
        if len(handles) != 1 or not self._restore_minimized(handles[0]):
            return self._layout()
        for _ in range(15):
            try:
                return self._layout()
            except BridgeError:
                time.sleep(.12)
        raise BridgeError('微信正在恢复界面，请稍候重新选择会话。')

    def _restore_minimized(self, hwnd):
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.IsIconic.argtypes = [wintypes.HWND]
        if not user.IsIconic(hwnd):
            return False
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetForegroundWindow.restype = wintypes.HWND
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        previous = user.GetForegroundWindow()
        # SW_RESTORE is required for an iconic Qt window; merely showing it can retain icon geometry.
        user.ShowWindow(hwnd, 9)
        for _ in range(15):
            time.sleep(.05)
            if not user.IsIconic(hwnd):
                if previous and previous != hwnd and user.GetForegroundWindow() == hwnd:
                    user.SetForegroundWindow(previous)
                return True
        raise BridgeError('微信窗口仍处于最小化状态，请从任务栏打开微信后再切换会话。')

    def _click_item(self, layout, control):
        self._pointer_item(layout, control)

    def scroll_history(self, binding, direction):
        if direction not in ('older', 'newer', 'latest'):
            raise BridgeError('无效的翻页方向。')
        layout = self._layout()
        if layout['binding'] != binding or layout['blocked'] or layout['messages'] is None:
            raise BridgeError('当前页面不是可翻页的聊天，请选择好友或群聊后再查看历史。')
        before = self._records(layout)
        self._pointer_item(layout, layout['messages'], {'older': 240, 'newer': -240, 'latest': -12000}[direction])
        self.media_not_before = time.monotonic()
        current, records = layout, before
        for attempt in range(8):
            time.sleep(.05 if attempt == 0 else .10)
            current = self._layout()
            if current['binding'] != binding or current['blocked'] or current['messages'] is None:
                raise BridgeError('查看历史时会话或窗口状态已改变，请重新同步。')
            records = self._records(current)
            if records != before:
                break
        # Return text immediately; regular polling fills in image previews afterwards.
        result = self._snapshot_from_layout(current, include_images=False, records=records)
        confirmed = self._layout()
        if confirmed['binding'] != binding or confirmed['blocked']:
            raise BridgeError('查看历史时连接或会话已变化，请重新同步。')
        result['historyChanged'] = records != before
        return result

    def _pointer_item(self, layout, control, wheel_delta=None):
        # Qt exposes SelectionItemPattern but its Select() can return EVENT_E_ALL_SUBSCRIBERS_FAILED.
        # Route a single click to the item's own HWND, without moving the user's cursor.
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.IsIconic.argtypes = [wintypes.HWND]
        if user.IsIconic(layout['hwnd']):
            raise BridgeError('微信窗口已最小化，请先打开微信或重新选择会话。')
        user.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        old = user.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))
        try:
            parent = control
            for _ in range(32):
                hwnd = parent.NativeWindowHandle
                if hwnd:
                    break
                parent = parent.GetParentControl()
                if not parent:
                    raise BridgeError('无法绑定目标控件窗口。')
            else:
                raise BridgeError('目标控件层级无效。')
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            actual, expected = wintypes.DWORD(), wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(actual))
            user.GetWindowThreadProcessId(layout['hwnd'], ctypes.byref(expected))
            if not actual.value or actual.value != expected.value or control.IsOffscreen:
                raise BridgeError('目标不在当前微信窗口中。')
            rect = control.BoundingRectangle
            if rect.right <= rect.left or rect.bottom <= rect.top:
                raise BridgeError('目标控件不可见。')
            point = wintypes.POINT((rect.left+rect.right)//2, (rect.top+rect.bottom)//2)
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            if wheel_delta is not None:
                # WM_MOUSEWHEEL uses screen coordinates, unlike mouse button messages.
                position = (point.y & 0xffff) << 16 | (point.x & 0xffff)
                if not user.PostMessageW(hwnd, 0x20A, (wheel_delta & 0xffff) << 16, position):
                    raise BridgeError('无法滚动微信记录，请重新同步。')
                return
            user.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            user.ScreenToClient(hwnd, ctypes.byref(point))
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            position = (point.y & 0xffff) << 16 | (point.x & 0xffff)
            if not user.PostMessageW(hwnd, 0x201, 1, position) or not user.PostMessageW(hwnd, 0x202, 0, position):
                raise BridgeError('未完成会话选择，请重新同步。')
        finally:
            if old:
                user.SetThreadDpiAwarenessContext(old)

    def _search_editor(self, layout):
        controls = [n for n in layout['nodes'] if n.ControlTypeName == 'EditControl'
                    and n.Name in ('搜索', 'Search') and n.AutomationId != 'chat_input_field']
        if len(controls) != 1:
            raise BridgeError('未找到唯一的联系人搜索框。')
        value = self._pattern(controls[0], 'ValuePattern')
        if not value or value.IsReadOnly:
            raise BridgeError('当前微信未提供联系人搜索接口。')
        return value

    def _search_items(self, layout):
        if self._search_editor(layout).Value != self.search_query:
            raise BridgeError('微信搜索内容已变化，请重新搜索。')
        lists = [n for n in layout['nodes'] if n.AutomationId == 'search_list']
        result = []
        prefixes = {'search_item_contact_': '联系人', 'search_item_group_': '群聊',
                    'search_item_chatroom_': '群聊', 'search_item_function_': '功能'}
        for listing in lists:
            category = ''
            for item in listing.GetChildren():
                identifier = item.AutomationId
                if not identifier:
                    if item.Name in ('最常使用', '联系人', '群聊', '功能'):
                        category = item.Name
                    elif not item.Name.startswith('查看全部'):
                        category = ''
                    continue
                prefix = next((p for p in prefixes if identifier.startswith(p)), None)
                if not prefix and identifier.startswith('search_item_') and category in ('最常使用', '联系人', '群聊'):
                    prefix = 'search_item_'
                if not prefix:
                    continue
                name = contact_name(identifier[len(prefix):])
                if not name or (prefix == 'search_item_function_' and name != '文件传输助手'):
                    continue
                result.append({'id': 'search:' + digest(repr(item.GetRuntimeId()) + identifier + self.search_query),
                               'name': name, 'key': digest(name), 'category': prefixes.get(prefix, category),
                               'control': item})
        return result

    def search(self, query):
        layout = self._navigation_layout()
        if layout['blocked']:
            raise BridgeError('原窗口有未处理的对话框，请先关闭。')
        value = self._search_editor(layout)
        if value.Value and value.Value != self.search_query:
            raise BridgeError('原窗口正在搜索，请先清空原窗口搜索内容。')
        if query:
            control = next(n for n in layout['nodes'] if n.ControlTypeName == 'EditControl'
                           and n.Name in ('搜索', 'Search') and n.AutomationId != 'chat_input_field')
            self._click_item(layout, control)
            # Re-entering the same query after the popup closed must trigger a fresh search.
            value.SetValue('', waitTime=0)
        value.SetValue(query, waitTime=0)
        self.search_query = query
        self.search_results = {}
        if not query:
            return {'results': [], 'query': query}
        results = []
        for _ in range(8):
            time.sleep(.15)
            results = self._search_items(self._layout())
            if results:
                break
        self.search_results = {r['id']: r['name'] for r in results}
        return {'query': query, 'results': [{k: v for k, v in r.items() if k != 'control'} for r in results]}

    def close(self):
        if self.capture:
            self.capture.close()
            self.capture = None

    def _history_records(self, layout, records):
        image_ids = {digest(repr(n.GetRuntimeId())) for n in layout['messages'].GetChildren()
                     if n.ClassName == 'mmui::ChatImageItemView'}
        # Keep the same identity/text as a completed preview so the browser can merge it.
        return [dict(row, text='图片 · 当前窗口预览', imagePending=True) if row['id'] in image_ids
                else row for row in records]

    def _media_records(self, layout):
        records = self._records(layout)
        image_items = {digest(repr(n.GetRuntimeId())): n for n in layout['messages'].GetChildren()
                       if n.ClassName == 'mmui::ChatImageItemView'}
        if not image_items or layout['blocked']:
            return records
        for record in records:
            if record['id'] in image_items:
                record['text'] = '图片 · 当前窗口预览'
                record['imagePending'] = False
                record['imageUnavailable'] = True
        try:
            from media import picture_previews
            pictures = picture_previews(self, layout, image_items)
            for record in records:
                if record['id'] in pictures:
                    record['image'] = pictures[record['id']]
                    record['imagePending'] = False
                    record['imageUnavailable'] = False
                    record['text'] = '图片 · 当前窗口预览'
        except Exception:
            for record in records:
                if record['id'] in image_items:
                    record['imageUnavailable'] = True
        return records

    def send_image(self, binding, encoded):
        from media import ImageSender
        return ImageSender(self).send(binding, encoded)

    def click_send(self, binding, expected_draft):
        # Qt's InvokePattern can return successfully without activating this button.
        # Use the same window-bound click route as session selection and file picking.
        layout = self._layout()
        value = self._pattern(layout['editor'], 'ValuePattern')
        if layout['binding'] != binding or layout.get('blocked'):
            raise BridgeError('发送前对象或窗口状态已变化，没有点击发送。')
        if not value or value.Value.replace('\r\n', '\n') != expected_draft.replace('\r\n', '\n'):
            raise BridgeError('发送前草稿已变化，没有点击发送。')
        if not layout['send'] or not layout['send'].IsEnabled:
            raise BridgeError('微信发送按钮尚不可用，没有点击发送。')
        self._click_item(layout, layout['send'])

    def _wait_draft(self, binding, expected, *, require_send=False):
        # SetValue returns before Qt necessarily publishes the new accessible value.
        # Reacquire the pattern each time; never rewrite or retry a send here.
        deadline = time.monotonic() + 1.2
        for attempt in range(9):
            layout = self._layout()
            if layout['binding'] != binding or layout.get('blocked'):
                raise BridgeError('校验时会话或窗口状态已变化，未点击发送。请重新选择会话。')
            value = self._pattern(layout['editor'], 'ValuePattern')
            if not value or value.IsReadOnly:
                raise BridgeError('输入框暂时不可用，未点击发送。草稿已保留。')
            matches = value.Value.replace('\r\n', '\n') == expected.replace('\r\n', '\n')
            if matches and (not require_send or (layout['send'] and layout['send'].IsEnabled)):
                return layout, value
            if attempt == 8 or time.monotonic() >= deadline:
                break
            time.sleep(.1)
        if not matches:
            raise BridgeError('微信输入框未及时显示完整文字，未点击发送。草稿已保留，可稍后重试。')
        raise BridgeError('微信发送按钮尚未就绪，未点击发送。草稿已保留，可稍后重试。')

    def clear_draft(self, binding):
        # User preference: replace this conversation's native draft on an explicit send.
        layout = self._layout()
        if layout['binding'] != binding or layout.get('blocked'):
            raise BridgeError('清空草稿前会话或窗口状态已变化，已停止。')
        if sum(s['name'] == layout['name'] for s in self._sessions(layout)) > 1:
            raise BridgeError('存在同名会话，没有清空草稿。')
        value = self._pattern(layout['editor'], 'ValuePattern')
        if not value or value.IsReadOnly:
            raise BridgeError('无法操作当前输入框，没有清空草稿。')
        if value.Value:
            value.SetValue('', waitTime=0)
            layout, value = self._wait_draft(binding, '')
        return layout, value

    def send(self, binding, text):
        layout = self._layout()
        if layout.get('blocked'):
            raise BridgeError('原窗口有未处理的对话框，已停止发送。')
        if layout['binding'] != binding:
            raise BridgeError('当前聊天对象已改变。请刷新并核对收件人后再发送。')
        if sum(s['name'] == layout['name'] for s in self._sessions(layout)) > 1:
            raise BridgeError('存在同名会话，已停止发送。')
        value = self._pattern(layout['editor'], 'ValuePattern')
        if not value or value.IsReadOnly or not layout['send']:
            raise BridgeError('当前版本未提供可靠的后台输入或发送接口。请使用原窗口。')
        if value.Value:
            layout, value = self.clear_draft(binding)
        before = {r['id'] for r in self._records(layout)}
        # Before the click, failure is known not to have sent anything. Keep the draft.
        try:
            value.SetValue(text, waitTime=0)
            refreshed, value = self._wait_draft(binding, text, require_send=True)
        except BridgeError as error:
            return {'state': 'not_sent', 'detail': str(error)}
        except Exception:
            return {'state': 'not_sent', 'detail': '输入框读取中断，未点击发送。草稿已保留，请重新同步后重试。'}
        # A click may have been dispatched even if its call raises. Never retry it.
        try:
            self.click_send(binding, text)
            for _ in range(5):
                time.sleep(0.2)
                refreshed = self._layout()
                if refreshed['binding'] != binding:
                    break
                value = self._pattern(refreshed['editor'], 'ValuePattern')
                if value and not value.Value and any(r['id'] not in before and text in r['text'] for r in self._records(refreshed)):
                    return {'state': 'observed', 'detail': '已在本机消息列表中看到新增文字；这不代表对方已收到或已读。'}
            if refreshed['binding'] == binding and value and value.Value.replace('\r\n', '\n') == text.replace('\r\n', '\n'):
                return {'state': 'unknown', 'detail': '发送请求未确认，文字仍留在微信输入框。请在原窗口处理这条草稿，工作台不会自动补发。'}
            return {'state': 'unknown', 'detail': '已请求点击一次发送，但未观察到新增消息。请核对原窗口，勿重复发送。'}
        except Exception:
            return {'state': 'unknown', 'detail': '操作中断，文字可能已写入或发送。请到原窗口核对，未自动重试。'}

    def open_native(self):
        handles = windows()
        if len(handles) != 1:
            raise BridgeError('请自行打开要使用的微信主窗口。')
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user.SetForegroundWindow.argtypes = [wintypes.HWND]
        user.ShowWindow(handles[0], 9)
        user.SetForegroundWindow(handles[0])
        return {'ok': True}
