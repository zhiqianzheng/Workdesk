"""Window-bound capture and Windows OCR. All frames and chat text stay in memory."""
import asyncio
import ctypes
from ctypes import wintypes
import io
import re
import threading
import time

import numpy as np
import cv2
from PIL import Image, ImageOps
from windows_capture import WindowsCapture
from winsdk.windows.globalization import Language
from winsdk.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, BitmapAlphaMode
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter

from bridge import BridgeError, digest, windows


def compact(text):
    return re.sub(r'\s+', '', text)


def readable(text):
    # Windows OCR inserts spaces between CJK glyphs. Keep genuine Latin word gaps.
    text = re.sub(r'(?<=[\u3400-\u9fff])\s+|\s+(?=[\u3400-\u9fff])', '', text)
    return re.sub(r'\s*([，。！？：；、（）])\s*', r'\1', text)


class WindowCapture:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.frame = None
        self.frame_at = 0
        self.closed = False
        self.capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False,
                                      draw_border=False, minimum_update_interval=100)

        @self.capture.event
        def on_frame_arrived(frame, capture_control):
            with self.lock:
                self.frame = frame.frame_buffer[:, :, :3][:, :, ::-1].copy()
                self.frame_at = time.monotonic()
                self.ready.set()

        @self.capture.event
        def on_closed():
            self.closed = True
            self.ready.set()

        self.control = self.capture.start_free_threaded()

    def image(self, after=None):
        if not self.ready.wait(4) or self.closed:
            raise BridgeError('无法采集原窗口。请保持微信打开且未最小化。')
        if after is not None:
            deadline = time.monotonic() + 1
            while self.frame_at < after and time.monotonic() < deadline and not self.closed:
                time.sleep(.02)
            if self.frame_at < after:
                raise BridgeError('尚未取得切换后的新画面。')
        with self.lock:
            if self.frame is None:
                raise BridgeError('尚未收到原窗口画面。')
            return Image.fromarray(self.frame)

    def close(self):
        if not self.closed:
            self.control.stop()
            self.closed = True


class OCRBridge:
    def __init__(self):
        self.capture = None
        self.engine = OcrEngine.try_create_from_language(Language('zh-Hans-CN'))
        if self.engine is None:
            self.engine = OcrEngine.try_create_from_user_profile_languages()
        if self.engine is None:
            raise BridgeError('Windows 未安装可用的文字识别语言。请安装中文 OCR 语言包。')

    def close(self):
        if self.capture:
            self.capture.close()
            self.capture = None

    def frame(self):
        handles = windows()
        if len(handles) != 1:
            raise BridgeError('请只保留一个已登录的微信主窗口。')
        user = ctypes.windll.user32
        user.IsIconic.argtypes = [wintypes.HWND]
        if user.IsIconic(handles[0]):
            raise BridgeError('原窗口已最小化。请恢复窗口，之后可以让工作台覆盖在它上方。')
        if not self.capture or self.capture.hwnd != handles[0] or self.capture.closed:
            self.close()
            self.capture = WindowCapture(handles[0])
        return handles[0], self.capture.image()

    async def _recognize(self, image):
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        blob = io.BytesIO()
        image.save(blob, format='PNG')
        writer.write_bytes(blob.getvalue())
        await writer.store_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
        result = await self.engine.recognize_async(bitmap)
        rows = []
        for line in result.lines:
            words = list(line.words)
            if not words:
                continue
            rects = [w.bounding_rect for w in words]
            rows.append({'text': line.text, 'box': (min(r.x for r in rects), min(r.y for r in rects),
                         max(r.x+r.width for r in rects), max(r.y+r.height for r in rects))})
        bitmap.close()
        stream.close()
        return rows

    def recognize(self, image):
        return asyncio.run(self._recognize(image))

    def layout(self):
        hwnd, image = self.frame()
        rgb = np.asarray(image)
        height, width = rgb.shape[:2]
        contours, _ = cv2.findContours(cv2.Canny(rgb, 15, 40), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [cv2.boundingRect(c) for c in contours]
        inputs = [b for b in boxes if b[0] > width*.25 and b[1] > height*.45
                  and b[2] > width*.35 and height*.12 < b[3] < height*.42]
        if not inputs:
            raise BridgeError('未识别到普通文字输入区域。请关闭弹窗并打开一个普通聊天。')
        ix, iy, iw, ih = max(inputs, key=lambda b: b[2]*b[3])
        scale = ih / 186
        contours, _ = cv2.findContours(cv2.Canny(rgb, 5, 15), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        buttons = {cv2.boundingRect(c) for c in contours}
        buttons = [b for b in buttons if ix+iw*.8 < b[0] < ix+iw and iy+ih*.65 < b[1]
                   and 40*scale < b[2] < 120*scale and 25*scale < b[3] < 65*scale]
        if len(buttons) != 1:
            raise BridgeError('无法确认唯一的发送按钮，已停止连接。')
        sx, sy, sw, sh = buttons[0]
        button_pixels = rgb[sy+4:sy+sh-4, sx+4:sx+sw-4].astype(float)
        enabled_pixels = (button_pixels[:,:,1]-button_pixels[:,:,0] > 45) & (button_pixels[:,:,1]-button_pixels[:,:,2] > 15)
        button_enabled = float(np.mean(enabled_pixels)) > .3
        inset = max(3, round(5*scale))
        button_image = image.crop((sx+inset, sy+inset, sx+sw-inset, sy+sh-inset)).convert('L')
        if np.median(np.asarray(button_image)) < 180:
            button_image = ImageOps.invert(button_image)
        button_ok = False
        for cutoff in (200, 190, 220, 20, 40, 60, 90, 120):
            processed = button_image.point(lambda p: 0 if p < cutoff else 255)
            processed = ImageOps.expand(processed, border=30, fill=255).convert('RGB')
            processed = processed.resize((processed.width*2, processed.height*2))
            if compact(''.join(r['text'] for r in self.recognize(processed))) in ('发送', '发送S', '发送(S)'):
                button_ok = True
                break
        magnification = 2 if max(image.size)*2 <= OcrEngine.max_image_dimension else 1
        enlarged = image.resize((image.width*magnification, image.height*magnification))
        rows = self.recognize(enlarged)
        for row in rows:
            row['box'] = tuple(v/magnification for v in row['box'])
        titles = [r for r in rows if ix < r['box'][0] < ix+iw*.5 and 30*scale < r['box'][1] < 110*scale]
        if len(titles) != 1 or len(compact(titles[0]['text'])) > 50:
            raise BridgeError('无法识别唯一的当前对象，请回原窗口确认。')
        title = titles[0]
        name = readable(title['text'])
        peers = [r for r in rows if r['box'][2] < ix and compact(r['text']) == compact(name)]
        identity = ''
        if len(peers) == 1:
            px, py, _, _ = peers[0]['box']
            avatar = image.crop((int(px-69*scale), int(py), int(px-16*scale), int(py+36*scale)))
            # Bind to the avatar, not row position: incoming chats reorder the sidebar.
            identity = digest(avatar.tobytes().hex())
        binding = digest(f'ocr:{hwnd}:{compact(name)}:{identity}:{image.size}:{ix}:{iy}')
        margin = max(8, round(12*scale))
        draft_box = (ix+margin, iy+margin, ix+iw-margin, sy-round(9*scale))
        draft_pixels = rgb[draft_box[1]:draft_box[3], draft_box[0]:draft_box[2]]
        background = np.median(draft_pixels.reshape(-1, 3), axis=0)
        # The empty editor can show a pale "长按鼠标 语音输入" placeholder.
        # Actual text and colored attachments have substantially stronger contrast.
        mask = (np.max(np.abs(draft_pixels.astype(float)-background), axis=2) > 70).astype('uint8')
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        marks = []
        for x, y, w, h, area in stats[1:]:
            caret = x < 12*scale and w <= 3*scale and h <= 30*scale
            if area > 4*scale*scale and not caret:
                marks.append((x, y, w, h))
        draft_rows = []
        if marks or button_enabled:
            draft_image = image.crop(draft_box)
            draft_rows = self.recognize(draft_image.resize((draft_image.width*2, draft_image.height*2)))
        # Header separator is a long horizontal line below the recognized title.
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        edge = np.mean(np.abs(np.diff(gray[:, ix+10:ix+iw-10].astype(float), axis=0)), axis=1)
        lower, upper = int(title['box'][3]+5*scale), int(title['box'][3]+50*scale)
        separator = lower + int(np.argmax(edge[lower:upper]))
        messages = [r for r in rows if r['box'][0] >= ix and r['box'][1] > separator+3*scale
                    and r['box'][3] < iy-4*scale]
        records = [{'id': digest(str(i)+':'+r['text']), 'text': readable(r['text'])}
                   for i, r in enumerate(messages)]
        return dict(hwnd=hwnd, image=image, name=name, binding=binding, records=records,
                    input=(ix, iy, iw, ih), button=(sx, sy, sw, sh), draft_box=draft_box,
                    draft=bool(marks) or button_enabled, draft_text=compact(''.join(r['text'] for r in draft_rows)),
                    can_send=len(peers) == 1 and button_ok, scale=scale)

    def snapshot(self):
        try:
            layout = self.layout()
            current = {'name': layout['name'], 'key': digest(layout['name']), 'binding': layout['binding']}
            return {'connected': True, 'mode': 'ocr', 'detail': '已读取当前可见文字（本机 OCR）。',
                    'current': current, 'records': layout['records'],
                    'sessions': [{'id': layout['binding'], **current}], 'canSend': layout['can_send'],
                    'hasNativeDraft': layout['draft'],
                    'sendNote': '本机 OCR：单条最多 200 字、暂不支持换行；发送会短暂显示原窗口。'
                    if layout['can_send'] else '无法在目录中唯一核对当前对象。请先在原窗口确认。'}
        except BridgeError as error:
            return {'connected': False, 'mode': 'ocr', 'detail': str(error), 'records': [], 'sessions': [], 'canSend': False}

    def select(self, session_id):
        state = self.snapshot()
        if not state.get('current') or state['current']['binding'] != session_id:
            raise BridgeError('OCR 模式请先在原窗口选择会话，再回到工作台同步。')
        return state

    def send(self, binding, text):
        if len(text) > 200 or any(ord(c) < 32 for c in text):
            raise BridgeError('OCR 模式目前支持 1–200 字的单行文字。长文或换行请用原窗口。')
        before = self.layout()
        self.check_target(before, binding)
        from native_input import BoundInput
        driver = BoundInput(before['hwnd'], before['image'].size)
        wrote = False
        clicked_send = False
        try:
            driver.activate()
            time.sleep(.2)
            layout = self.layout()
            self.check_target(layout, binding)
            x1, y1, x2, y2 = layout['draft_box']
            driver.click(x1+10, y1+10)
            time.sleep(.15)
            layout = self.layout()
            self.check_target(layout, binding)
            if layout['draft']:
                driver.clear_text()
                time.sleep(.25)
                layout = self.layout()
                self.check_target(layout, binding)
                if layout['draft']:
                    raise BridgeError('原窗口草稿未能清空，没有输入或发送。')
            wrote = True
            driver.type_text(text)
            time.sleep(.3)
            layout = self.layout()
            self.check_target(layout, binding)
            if layout['draft_text'] != compact(text):
                return {'state': 'unknown', 'detail': '文字已写入，但 OCR 校对未通过，未点击发送。请打开原窗口检查草稿。'}
            driver.verify()
            sx, sy, sw, sh = layout['button']
            clicked_send = True
            driver.click(sx+sw/2, sy+sh/2)
            for _ in range(5):
                time.sleep(.25)
                after = self.layout()
                # Sending can reorder the sidebar; compare the title as well as the same HWND.
                if after['hwnd'] != before['hwnd'] or compact(after['name']) != compact(before['name']):
                    break
                old_count = sum(compact(text) in compact(r['text']) for r in before['records'])
                new_count = sum(compact(text) in compact(r['text']) for r in after['records'])
                if not after['draft'] and new_count > old_count:
                    return {'state': 'observed', 'detail': '已单次发送，并在本机当前会话中读回新增文字；不代表对方已读。'}
            return {'state': 'unknown', 'detail': '已执行一次发送，尚未确认新增文字。请核对原窗口，不会自动重发。'}
        except Exception:
            if clicked_send:
                return {'state': 'unknown', 'detail': '发送操作中断，请检查原窗口记录。未自动重试。'}
            if wrote:
                return {'state': 'unknown', 'detail': '文字已写入，校验中断，未点击发送。请检查原窗口草稿。'}
            raise
        finally:
            driver.close()

    @staticmethod
    def check_target(layout, binding):
        if layout['binding'] != binding or not layout['can_send']:
            raise BridgeError('当前对象、目录或窗口布局已变化。请同步并核对对象后再提交。')
