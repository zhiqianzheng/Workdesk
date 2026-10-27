"""Bound foreground input for the OCR adapter; no clipboard or process memory access."""
import ctypes
import time
from ctypes import wintypes

from bridge import BridgeError

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', wintypes.DWORD), ('data', INPUTUNION)]


class BoundInput:
    def __init__(self, hwnd, size):
        self.hwnd, self.size = hwnd, size
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.user.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        self.user.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        self.old_dpi = self.user.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetAncestor.restype = wintypes.HWND
        self.user.WindowFromPoint.argtypes = [wintypes.POINT]
        self.user.WindowFromPoint.restype = wintypes.HWND
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT
        self.previous = self.user.GetForegroundWindow()
        self.cursor = wintypes.POINT()
        self.user.GetCursorPos(ctypes.byref(self.cursor))
        self.last_click = None

    def activate(self):
        if any(self.user.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12, 0x01, 0x02)):
            raise BridgeError('检测到按键或鼠标正在使用，请松开后再提交。')
        self.user.SetForegroundWindow(self.hwnd)
        time.sleep(.15)
        if self.user.GetForegroundWindow() != self.hwnd:
            # Windows foreground restrictions can block a loopback server. Temporarily
            # attach input queues, never send shortcut keys or alter user settings.
            self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
            current = ctypes.windll.kernel32.GetCurrentThreadId()
            foreground = self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), None)
            attached = bool(self.user.AttachThreadInput(current, foreground, True)) if foreground else False
            try:
                self.user.SetForegroundWindow(self.hwnd)
                time.sleep(.15)
            finally:
                if attached:
                    self.user.AttachThreadInput(current, foreground, False)
        self.verify()

    def verify(self):
        if self.user.GetForegroundWindow() != self.hwnd:
            raise BridgeError('原窗口未获得焦点，已停止操作。')
        rect = wintypes.RECT()
        dwm = ctypes.WinDLL('dwmapi')
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        if dwm.DwmGetWindowAttribute(self.hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)):
            raise BridgeError('无法核对窗口边界。')
        if (rect.right-rect.left, rect.bottom-rect.top) != self.size:
            raise BridgeError('窗口尺寸已改变，请同步后重新提交。')
        return rect

    def click(self, x, y):
        rect = self.verify()
        point = wintypes.POINT(rect.left+int(x), rect.top+int(y))
        target = self.user.WindowFromPoint(point)
        if self.user.GetAncestor(target, 2) != self.hwnd:
            raise BridgeError('操作位置被其他窗口遮挡，已停止。')
        self.user.SetCursorPos(point.x, point.y)
        self.last_click = (point.x, point.y)
        events = (INPUT*2)(INPUT(type=0, mi=MOUSEINPUT(dwFlags=2)), INPUT(type=0, mi=MOUSEINPUT(dwFlags=4)))
        if self.user.SendInput(2, events, ctypes.sizeof(INPUT)) != 2:
            raise BridgeError('点击未完整执行，请在原窗口核对。')

    def type_text(self, text):
        self.verify()
        data = text.encode('utf-16-le')
        events = []
        for i in range(0, len(data), 2):
            unit = int.from_bytes(data[i:i+2], 'little')
            events.extend((INPUT(type=1, ki=KEYBDINPUT(wScan=unit, dwFlags=4)),
                           INPUT(type=1, ki=KEYBDINPUT(wScan=unit, dwFlags=6))))
        array = (INPUT*len(events))(*events)
        if self.user.SendInput(len(events), array, ctypes.sizeof(INPUT)) != len(events):
            raise BridgeError('文字输入未完整执行，请在原窗口核对草稿。')

    def paste(self):
        self.verify()
        if any(self.user.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12)):
            raise BridgeError('检测到按键正在使用，没有粘贴图片。')
        keys = [(0x11, 0), (0x56, 0), (0x56, 2), (0x11, 2)]
        events = (INPUT*4)(*(INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=flags)) for key, flags in keys))
        if self.user.SendInput(4, events, ctypes.sizeof(INPUT)) != 4:
            releases = (INPUT*2)(*(INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=2)) for key in (0x56, 0x11)))
            self.user.SendInput(2, releases, ctypes.sizeof(INPUT))
            raise BridgeError('图片粘贴未完整执行，没有点击发送。')

    def clear_text(self):
        self.verify()
        if any(self.user.GetAsyncKeyState(k) & 0x8000 for k in (0x10, 0x11, 0x12)):
            raise BridgeError('检测到按键正在使用，未清空草稿。')
        keys = [(0x11, 0), (0x41, 0), (0x41, 2), (0x11, 2), (0x08, 0), (0x08, 2)]
        events = (INPUT*len(keys))(*(INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=flags)) for key, flags in keys))
        if self.user.SendInput(len(events), events, ctypes.sizeof(INPUT)) != len(events):
            releases = (INPUT*3)(*(INPUT(type=1, ki=KEYBDINPUT(wVk=key, dwFlags=2)) for key in (0x41, 0x11, 0x08)))
            self.user.SendInput(3, releases, ctypes.sizeof(INPUT))
            raise BridgeError('清空输入未完整执行，没有发送。')

    def close(self):
        if self.previous and self.previous != self.hwnd and self.user.GetForegroundWindow() == self.hwnd:
            self.user.SetForegroundWindow(self.previous)
            time.sleep(.15)
            if self.user.GetForegroundWindow() == self.hwnd:
                self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
                current = ctypes.windll.kernel32.GetCurrentThreadId()
                foreground = self.user.GetWindowThreadProcessId(self.hwnd, None)
                attached = bool(self.user.AttachThreadInput(current, foreground, True))
                try:
                    self.user.SetForegroundWindow(self.previous)
                    time.sleep(.15)
                finally:
                    if attached:
                        self.user.AttachThreadInput(current, foreground, False)
        point = wintypes.POINT()
        if self.last_click and self.user.GetCursorPos(ctypes.byref(point)) and (point.x,point.y) == self.last_click:
            self.user.SetCursorPos(self.cursor.x, self.cursor.y)
        if self.old_dpi:
            self.user.SetThreadDpiAwarenessContext(self.old_dpi)
