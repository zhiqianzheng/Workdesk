"""Read a window's rendered surface with a bounded wait, independent of desktop opacity."""
from concurrent.futures import Future, TimeoutError
import ctypes
from ctypes import wintypes as w
import threading

from bridge import BridgeError

_lock = threading.Lock()
_pending = None


def _capture(hwnd):
    from PIL import Image
    user, gdi = ctypes.WinDLL('user32'), ctypes.WinDLL('gdi32')
    user.SetThreadDpiAwarenessContext.argtypes = [w.HANDLE]
    user.SetThreadDpiAwarenessContext.restype = w.HANDLE
    old_dpi = user.SetThreadDpiAwarenessContext(w.HANDLE(-4))
    user.GetWindowDC.argtypes = [w.HWND]; user.GetWindowDC.restype = w.HDC
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.PrintWindow.argtypes = [w.HWND, w.HDC, w.UINT]
    user.ReleaseDC.argtypes = [w.HWND, w.HDC]
    gdi.CreateCompatibleDC.argtypes = [w.HDC]; gdi.CreateCompatibleDC.restype = w.HDC
    gdi.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = w.HBITMAP
    gdi.SelectObject.argtypes = [w.HDC, w.HANDLE]; gdi.SelectObject.restype = w.HANDLE
    gdi.DeleteDC.argtypes = [w.HDC]; gdi.DeleteObject.argtypes = [w.HANDLE]
    gdi.GetDIBits.argtypes = [w.HDC, w.HBITMAP, w.UINT, w.UINT, ctypes.c_void_p, ctypes.c_void_p, w.UINT]
    class Header(ctypes.Structure):
        _fields_ = [('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),
                    ('compression',w.DWORD),('imagesize',w.DWORD),('xp',w.LONG),('yp',w.LONG),
                    ('used',w.DWORD),('important',w.DWORD)]
    dc = memory = bitmap = previous = None
    try:
        rect = w.RECT()
        if not user.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise BridgeError('无法读取微信窗口尺寸。')
        width, height = rect.right-rect.left, rect.bottom-rect.top
        if width < 200 or height < 200 or width*height > 40000000:
            raise BridgeError('微信窗口尺寸不适合自动识别。')
        dc = user.GetWindowDC(hwnd)
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        if not dc or not memory or not bitmap:
            raise BridgeError('无法建立窗口读取资源。')
        previous = gdi.SelectObject(memory, bitmap)
        if not user.PrintWindow(hwnd, memory, 2):
            raise BridgeError('当前微信版本未提供窗口画面，自动回复已暂停。')
        gdi.SelectObject(memory, previous); previous = None
        info = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width*height*4)
        if gdi.GetDIBits(memory, bitmap, 0, height, buffer, ctypes.byref(info), 0) != height:
            raise BridgeError('微信画面读取不完整。')
        return Image.frombytes('RGB', (width,height), buffer.raw, 'raw', 'BGRX'), rect
    finally:
        if previous: gdi.SelectObject(memory, previous)
        if bitmap: gdi.DeleteObject(bitmap)
        if memory: gdi.DeleteDC(memory)
        if dc: user.ReleaseDC(hwnd, dc)
        if old_dpi: user.SetThreadDpiAwarenessContext(old_dpi)


def capture(hwnd):
    global _pending
    with _lock:
        if _pending is not None and not _pending.done():
            raise BridgeError('窗口读取仍未结束，自动回复已暂停。')
        _pending = Future()
        future = _pending
        def run():
            try:
                future.set_result(_capture(hwnd))
            except Exception as error:
                future.set_exception(error)
        threading.Thread(target=run, daemon=True, name='workdesk-frame').start()
    try:
        return future.result(timeout=2)
    except TimeoutError:
        raise BridgeError('窗口读取超时，自动回复已暂停。') from None
