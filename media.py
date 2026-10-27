"""Local image previews and an explicit, recipient-bound native image send flow."""
import base64
import ctypes
from ctypes import wintypes
import io
import time

from PIL import Image, ImageOps
from bridge import BridgeError, digest
from clipboard_image import ImageClipboard

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def decode_image(encoded):
    if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
        raise BridgeError('请选择 8 MB 以内的 PNG、JPEG 或 WebP 图片。')
    try:
        data = base64.b64decode(encoded, validate=True)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError()
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 24000000:
                raise ValueError()
            source.load()
            normalized = ImageOps.exif_transpose(source).convert('RGB')
        out = io.BytesIO()
        normalized.save(out, 'PNG')
        return out.getvalue()
    except Exception as error:
        raise BridgeError('图片无法解码，或格式、尺寸超出限制。') from error


def picture_previews(bridge, layout, items):
    from ocr_bridge import WindowCapture
    user = ctypes.WinDLL('user32')
    user.IsIconic.argtypes = [wintypes.HWND]
    if user.IsIconic(layout['hwnd']):
        return {}
    if not bridge.capture or bridge.capture.hwnd != layout['hwnd'] or bridge.capture.closed:
        bridge.close()
        bridge.capture = WindowCapture(layout['hwnd'])
    frame = bridge.capture.image(after=bridge.media_not_before)
    rect = wintypes.RECT()
    dwm = ctypes.WinDLL('dwmapi')
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    if dwm.DwmGetWindowAttribute(layout['hwnd'], 9, ctypes.byref(rect), ctypes.sizeof(rect)):
        return {}
    if (rect.right-rect.left, rect.bottom-rect.top) != frame.size:
        return {}
    viewport = layout['messages'].BoundingRectangle
    pictures = {}
    for key, item in list(items.items())[-12:]:
        bounds = item.BoundingRectangle
        box = (max(0, bounds.left-rect.left, viewport.left-rect.left),
               max(0, bounds.top-rect.top, viewport.top-rect.top),
               min(frame.width, bounds.right-rect.left, viewport.right-rect.left),
               min(frame.height, bounds.bottom-rect.top, viewport.bottom-rect.top))
        if box[2]-box[0] < 12 or box[3]-box[1] < 12 or item.IsOffscreen:
            continue
        picture = frame.crop(box)
        picture.thumbnail((1000, 600))
        out = io.BytesIO()
        picture.save(out, 'PNG')
        pictures[key] = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode('ascii')
    if bridge._layout()['binding'] != layout['binding']:
        raise BridgeError('图片采集期间对象已变化。')
    return pictures


class ImageSender:
    def __init__(self, bridge):
        self.bridge = bridge
        self.paste_attempted = False
        self.preview = None
        self.before = None
        self.previous_images = set()

    def stage(self, binding, encoded):
        data = decode_image(encoded)
        before = self.bridge._layout()
        self.before = before
        if before['messages'] is None or before['editor'] is None:
            raise BridgeError('当前页面没有聊天输入框，请先选择好友或群聊。')
        self.previous_images = {digest(repr(n.GetRuntimeId())) for n in before['messages'].GetChildren()
                                if n.ClassName == 'mmui::ChatImageItemView'}
        if before['binding'] != binding or before['blocked']:
            raise BridgeError('对象已变化或原窗口有弹窗，未准备图片。')
        value = self.bridge._pattern(before['editor'], 'ValuePattern')
        if not value or value.IsReadOnly:
            raise BridgeError('无法操作当前输入框，未准备图片。')
        if sum(s['name'] == before['name'] for s in self.bridge._sessions(before)) > 1:
            raise BridgeError('存在同名对象，未准备图片。')
        with ImageClipboard(data) as clipboard:
            if value.Value:
                self.before, value = self.bridge.clear_draft(binding)
            self._paste(binding, clipboard)
            result = self._wait_preview(binding)
            clipboard.verify()
            return result

    def _paste(self, binding, clipboard):
        from native_input import BoundInput
        layout = self.bridge._layout()
        if layout['binding'] != binding or layout['blocked']:
            raise BridgeError('粘贴前对象已改变，没有发送。')
        rect = wintypes.RECT()
        dwm = ctypes.WinDLL('dwmapi')
        dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        if dwm.DwmGetWindowAttribute(layout['hwnd'], 9, ctypes.byref(rect), ctypes.sizeof(rect)):
            raise BridgeError('无法核对图片粘贴窗口。')
        driver = BoundInput(layout['hwnd'], (rect.right-rect.left, rect.bottom-rect.top))
        try:
            driver.activate()
            layout = self.bridge._layout()
            if layout['binding'] != binding or layout['blocked']:
                raise BridgeError('粘贴前对象已改变，没有发送。')
            bounds = layout['editor'].BoundingRectangle
            driver.click((bounds.left+bounds.right)/2-rect.left, (bounds.top+bounds.bottom)/2-rect.top)
            time.sleep(.08)
            layout = self.bridge._layout()
            value = self.bridge._pattern(layout['editor'], 'ValuePattern')
            if (layout['binding'] != binding or layout['blocked'] or not value or value.Value
                    or not layout['editor'].HasKeyboardFocus):
                raise BridgeError('粘贴前输入框或对象已变化，没有发送。')
            clipboard.verify()
            self.paste_attempted = True
            driver.paste()
            time.sleep(.12)
        finally:
            driver.close()

    def _wait_preview(self, binding):
        # This WeChat version inserts one inline image object in the editor.
        for _ in range(25):
            layout = self.bridge._layout()
            value = self.bridge._pattern(layout['editor'], 'ValuePattern')
            if layout['binding'] != binding:
                raise BridgeError('图片准备期间对象已变化，没有点击发送。')
            if not layout['blocked'] and value and value.Value == '\ufffc' and layout['send'] and layout['send'].IsEnabled:
                self.preview = layout
                return layout
            time.sleep(.12)
        raise BridgeError('未确认输入框中的单张图片，没有点击发送。请检查原窗口。')

    def send(self, binding, encoded):
        invoked = False
        try:
            self.stage(binding, encoded)
            layout = self.bridge._layout()
            value = self.bridge._pattern(layout['editor'], 'ValuePattern')
            if layout['binding'] != binding or layout['blocked'] or not value or value.Value != '\ufffc' or not layout['send']:
                return {'state': 'unknown', 'detail': '图片已放入原窗口，但对象或草稿发生变化，没有点击发送。'}
            invoked = True
            self.bridge.click_send(binding, '\ufffc')
            for _ in range(12):
                time.sleep(.2)
                after = self.bridge._layout()
                if after['binding'] != binding:
                    break
                images = {digest(repr(n.GetRuntimeId())) for n in after['messages'].GetChildren()
                          if n.ClassName == 'mmui::ChatImageItemView'}
                current_value = self.bridge._pattern(after['editor'], 'ValuePattern')
                if current_value and not current_value.Value and images - self.previous_images:
                    return {'state': 'observed', 'detail': '已单次发送，并在当前会话中看到新增图片；不代表对方已读。'}
            return {'state': 'unknown', 'detail': '已请求点击一次发送，但未观察到新增图片。请核对原窗口及图片草稿；不会自动重发。'}
        except Exception as error:
            if self.paste_attempted:
                return {'state': 'unknown', 'detail': '图片操作中断，请检查原窗口；' + ('发送结果待核对。' if invoked else '没有点击发送。')}
            raise

    def cancel_staged(self):
        layout = self.bridge._layout()
        value = self.bridge._pattern(layout['editor'], 'ValuePattern')
        if self.preview and layout['binding'] == self.before['binding'] and value.Value == '\ufffc':
            value.SetValue('', waitTime=0)

