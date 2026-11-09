"""Conservative direction recognition for fully visible, standard light-theme text bubbles."""
import ctypes
from ctypes import wintypes

from bridge import BridgeError, digest


def bubble_direction(rgb):
    import cv2
    import numpy as np
    a = np.asarray(rgb)
    h, w = a.shape[:2]
    if h < 24 or w < 180:
        return 'unknown'
    r, g, b = (a[:, :, i].astype('int16') for i in range(3))
    green = ((g > 160) & (g-r > 25) & (g-b > 45) & (r > 50)).astype('uint8')
    white = ((r > 245) & (g > 245) & (b > 245)).astype('uint8')
    grey = ((a.min(axis=2) >= 215) & (a.max(axis=2) <= 242)
            & (a.max(axis=2).astype('int16')-a.min(axis=2) < 10)).astype('uint8')
    def regions(mask):
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        return [s for s in stats[1:] if s[4] >= 180 and s[2] >= 18 and s[3] >= 16
                and s[4] / (s[2]*s[3]) > .55]
    # Any substantial green area prevents interpreting this row as incoming.
    if regions(green):
        return 'outgoing'
    candidates = [s for s in regions(white) + regions(grey) if .055*w <= s[0] <= .27*w
                  and s[0]+s[2] < .91*w and s[3] < h-2]
    if len(candidates) != 1:
        return 'unknown'
    x, y, width, height, _ = candidates[0]
    # A textured avatar to the left must accompany the white bubble. Text-only notices fail closed.
    avatar = a[max(0,y-14):min(h,y+height), max(0,x-int(w*.12)):max(0,x-6)]
    if avatar.size and float(avatar.std(axis=(0,1)).mean()) > 20:
        return 'incoming'
    return 'unknown'


def records(bridge, layout):
    from window_frame import capture
    user = ctypes.WinDLL('user32')
    user.IsIconic.argtypes = [wintypes.HWND]
    if user.IsIconic(layout['hwnd']):
        raise BridgeError('自动回复需要微信未最小化，已暂停。')
    original = bridge._records(layout)
    frame, bounds = capture(layout['hwnd'])
    items = {digest(repr(n.GetRuntimeId())): n for n in layout['messages'].GetChildren()}
    viewport = layout['messages'].BoundingRectangle
    result = []
    for row in original[-24:]:
        item = items.get(row['id'])
        kind = 'text' if item and item.ClassName == 'mmui::ChatTextItemView' else 'other'
        direction = 'unknown'
        if kind == 'text' and not item.IsOffscreen:
            rect = item.BoundingRectangle
            if (rect.top >= viewport.top and rect.bottom <= viewport.bottom
                    and rect.left >= bounds.left and rect.right <= bounds.right
                    and rect.top >= bounds.top and rect.bottom <= bounds.bottom):
                crop = frame.crop((rect.left-bounds.left, rect.top-bounds.top,
                                   rect.right-bounds.left, rect.bottom-bounds.top))
                direction = bubble_direction(crop)
        result.append({**row, 'kind': kind, 'direction': direction})
    confirmed = bridge._layout()
    actual = wintypes.RECT()
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowRect(layout['hwnd'], ctypes.byref(actual))
    if (actual.left, actual.top, actual.right, actual.bottom) != (bounds.left, bounds.top, bounds.right, bounds.bottom):
        raise BridgeError('读取期间窗口移动，自动回复已暂停。')
    if confirmed['binding'] != layout['binding'] or bridge._records(confirmed) != original:
        raise BridgeError('读取期间会话或消息已变化，请稍后重新启用。')
    return result
