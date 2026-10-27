"""Temporarily publish an image for a user-requested paste, preserving clipboard data."""
import ctypes
from ctypes import wintypes
import io
import time

from PIL import Image
from bridge import BridgeError


class ImageClipboard:
    def __init__(self, png):
        with Image.open(io.BytesIO(png)) as image:
            buffer = io.BytesIO()
            image.convert('RGB').save(buffer, 'BMP')
        self.dib = buffer.getvalue()[14:]
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                             wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
        self.user.CreateWindowExW.restype = wintypes.HWND
        self.user.DestroyWindow.argtypes = [wintypes.HWND]
        self.user.OpenClipboard.argtypes = [wintypes.HWND]
        self.user.GetClipboardData.argtypes = [wintypes.UINT]
        self.user.GetClipboardData.restype = wintypes.HANDLE
        self.user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        self.user.SetClipboardData.restype = wintypes.HANDLE
        self.user.EnumClipboardFormats.argtypes = [wintypes.UINT]
        self.user.EnumClipboardFormats.restype = wintypes.UINT
        self.user.GetClipboardSequenceNumber.restype = wintypes.DWORD
        self.user.GetClipboardOwner.restype = wintypes.HWND
        for name in ('GlobalLock', 'GlobalFree'):
            getattr(self.kernel, name).argtypes = [wintypes.HGLOBAL]
            getattr(self.kernel, name).restype = ctypes.c_void_p
        self.kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self.kernel.GlobalSize.argtypes = [wintypes.HGLOBAL]
        self.kernel.GlobalSize.restype = ctypes.c_size_t
        self.kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self.kernel.GlobalAlloc.restype = wintypes.HGLOBAL
        self.saved = []
        self.window = None
        self.sequence = None

    def _open(self):
        for _ in range(15):
            if self.user.OpenClipboard(self.window):
                return
            time.sleep(.02)
        raise BridgeError('剪贴板正在使用，请稍后重新发送图片。')

    def _allocate(self, data):
        handle = self.kernel.GlobalAlloc(2, len(data))
        if not handle:
            raise BridgeError('无法分配图片剪贴板内存。')
        pointer = self.kernel.GlobalLock(handle)
        if not pointer:
            self.kernel.GlobalFree(handle)
            raise BridgeError('无法写入图片剪贴板。')
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            self.kernel.GlobalUnlock(handle)
        return handle

    def _snapshot(self):
        formats, current = [], 0
        while True:
            ctypes.set_last_error(0)
            current = self.user.EnumClipboardFormats(current)
            if not current:
                if ctypes.get_last_error():
                    raise BridgeError('无法保存当前剪贴板，未粘贴图片。')
                break
            formats.append(current)
        total = 0
        for kind in formats:
            # Windows synthesizes CF_BITMAP from DIB. Preserve the lossless DIB instead.
            if kind == 2 and (8 in formats or 17 in formats):
                continue
            # These are object/owner-managed handles, not copyable HGLOBAL blocks.
            if kind in (2, 3, 9, 14, 128, 130, 131, 142) or 0x200 <= kind <= 0x3ff:
                raise BridgeError('当前剪贴板格式无法临时保存。请先复制一段普通文字，再发送图片。')
            handle = self.user.GetClipboardData(kind)
            size = self.kernel.GlobalSize(handle) if handle else 0
            total += size
            if not size or total > 64 * 1024 * 1024:
                raise BridgeError('当前剪贴板内容无法临时保存，未粘贴图片。')
            pointer = self.kernel.GlobalLock(handle)
            if not pointer:
                raise BridgeError('无法保存当前剪贴板，未粘贴图片。')
            try:
                data = ctypes.string_at(pointer, size)
            finally:
                self.kernel.GlobalUnlock(handle)
            self.saved.append([kind, self._allocate(data)])

    def _restore_open(self):
        if not self.user.EmptyClipboard():
            raise BridgeError('无法恢复剪贴板，请检查当前复制内容。')
        failed = False
        for entry in self.saved:
            if self.user.SetClipboardData(entry[0], entry[1]):
                entry[1] = None  # Ownership transferred to Windows.
            else:
                failed = True
        if failed:
            raise BridgeError('部分剪贴板格式恢复失败，请检查当前复制内容。')

    def _dispose(self):
        for _, handle in self.saved:
            if handle:
                self.kernel.GlobalFree(handle)
        self.saved.clear()
        if self.window:
            self.user.DestroyWindow(self.window)
            self.window = None

    def __enter__(self):
        self.window = self.user.CreateWindowExW(0, 'STATIC', 'Workdesk clipboard', 0, 0, 0, 0, 0, wintypes.HWND(-3), None, None, None)
        if not self.window:
            raise BridgeError('无法准备图片剪贴板。')
        image_handle = None
        try:
            self._open()
            try:
                self._snapshot()
                image_handle = self._allocate(self.dib)
                if not self.user.EmptyClipboard():
                    raise BridgeError('无法临时写入剪贴板。')
                if not self.user.SetClipboardData(8, image_handle):
                    self._restore_open()
                    raise BridgeError('无法将图片放入剪贴板。')
                image_handle = None
                self.sequence = self.user.GetClipboardSequenceNumber()
            finally:
                self.user.CloseClipboard()
            return self
        except Exception:
            if image_handle:
                self.kernel.GlobalFree(image_handle)
            self._dispose()
            raise

    def verify(self):
        self._open()
        try:
            if not self._owns_image():
                raise BridgeError('粘贴期间剪贴板已变化，没有发送图片。')
        finally:
            self.user.CloseClipboard()

    def _owns_image(self):
        # CloseClipboard and synthesized formats can advance the sequence number.
        # Check the owner and actual DIB instead of mistaking those for a user copy.
        if self.user.GetClipboardOwner() != self.window:
            return False
        handle = self.user.GetClipboardData(8)
        if not handle or self.kernel.GlobalSize(handle) < len(self.dib):
            return False
        pointer = self.kernel.GlobalLock(handle)
        if not pointer:
            return False
        try:
            return ctypes.string_at(pointer, len(self.dib)) == self.dib
        finally:
            self.kernel.GlobalUnlock(handle)

    def __exit__(self, *_):
        try:
            self._open()
            try:
                # A concurrent user copy wins; never overwrite their newer clipboard.
                if self._owns_image():
                    self._restore_open()
            finally:
                self.user.CloseClipboard()
        finally:
            self._dispose()
