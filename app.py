import ctypes
from ctypes import wintypes
import threading
import time

# === Load DLLs ===
user32   = ctypes.windll.user32
gdi32    = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# === Tipe untuk layered update ===
class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]
class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp",             ctypes.c_byte),
        ("BlendFlags",          ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat",         ctypes.c_byte),
    ]

# === Constants ===
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST     = 0x00000008
WS_POPUP          = 0x80000000
ULW_ALPHA         = 0x00000002
SW_SHOW           = 5
WM_DESTROY        = 0x0002
VK_LBUTTON        = 0x01

# === Callback signature & WNDCLASS ===
WNDPROCTYPE = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    wintypes.HWND, wintypes.UINT,
    ctypes.c_void_p, ctypes.c_void_p
)
class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style",         ctypes.c_uint),
        ("lpfnWndProc",   WNDPROCTYPE),
        ("cbClsExtra",    ctypes.c_int),
        ("cbWndExtra",    ctypes.c_int),
        ("hInstance",     wintypes.HINSTANCE),
        ("hIcon",         ctypes.c_void_p),
        ("hCursor",       ctypes.c_void_p),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName",  wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]

# DefWindowProcW
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT,
    ctypes.c_void_p, ctypes.c_void_p
]
user32.DefWindowProcW.restype = ctypes.c_long

def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_DESTROY:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

def bresenham_line(x0, y0, x1, y1):
    pts = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = err * 2
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return pts

def main():
    # --- Register window class ---
    hInst   = kernel32.GetModuleHandleW(None)
    clsName = "ClickTrailOverlay"
    wc      = WNDCLASS()
    wc.lpfnWndProc   = WNDPROCTYPE(wnd_proc)
    wc.hInstance     = hInst
    wc.lpszClassName = clsName
    wc.hbrBackground = gdi32.GetStockObject(0)   # NULL_BRUSH
    wc.hCursor       = user32.LoadCursorW(None, 32512)
    user32.RegisterClassW(ctypes.byref(wc))

    # --- Create layered window ---
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST,
        clsName, None,
        WS_POPUP,
        0, 0, sw, sh,
        None, None, hInst, None
    )
    user32.ShowWindow(hwnd, SW_SHOW)

    # --- Setup DIBSection ---
    hdc_screen = user32.GetDC(None)
    hdc_mem    = gdi32.CreateCompatibleDC(hdc_screen)
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize",        wintypes.DWORD),
            ("biWidth",       wintypes.LONG),
            ("biHeight",      wintypes.LONG),
            ("biPlanes",      wintypes.WORD),
            ("biBitCount",    wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage",   wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed",     wintypes.DWORD),
            ("biClrImportant",wintypes.DWORD),
        ]
    bmi = BITMAPINFOHEADER(
        biSize=ctypes.sizeof(BITMAPINFOHEADER),
        biWidth=sw,
        biHeight=-sh,   # top-down
        biPlanes=1,
        biBitCount=32,
        biCompression=0
    )
    ppvBits = ctypes.c_void_p()
    hbmp    = gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi),
                                     0, ctypes.byref(ppvBits), None, 0)
    oldbmp  = gdi32.SelectObject(hdc_mem, hbmp)

    # Prepare blend
    blend = BLENDFUNCTION(0, 0, 255, 1)

    running = True
    def updater():
        buf     = (ctypes.c_ubyte * (sw * sh * 4)).from_address(ppvBits.value)
        prev_pt = POINT()
        user32.GetCursorPos(ctypes.byref(prev_pt))

        while running:
            # check left button state
            pressed = (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0
            cur_pt = POINT()
            user32.GetCursorPos(ctypes.byref(cur_pt))

            if pressed:
                # draw only when pressed
                for x, y in bresenham_line(prev_pt.x, prev_pt.y, cur_pt.x, cur_pt.y):
                    if 0 <= x < sw and 0 <= y < sh:
                        idx = (y * sw + x) * 4
                        # 2px-thick
                        for dx in (-1,0,1):
                            for dy in (-1,0,1):
                                nx, ny = x+dx, y+dy
                                if 0 <= nx < sw and 0 <= ny < sh:
                                    nidx = (ny * sw + nx) * 4
                                    buf[nidx+0] = 0
                                    buf[nidx+1] = 255
                                    buf[nidx+2] = 0
                                    buf[nidx+3] = 255
                # update prev only when drawing
                prev_pt = cur_pt
            else:
                # reset prev on release so next click starts fresh
                prev_pt = cur_pt

            # composite
            user32.UpdateLayeredWindow(
                hwnd,
                hdc_screen,
                ctypes.byref(POINT(0,0)),
                ctypes.byref(SIZE(sw, sh)),
                hdc_mem,
                ctypes.byref(POINT(0,0)),
                0,
                ctypes.byref(blend),
                ULW_ALPHA
            )
            time.sleep(0.016)  # ~60 FPS

    # start updater thread
    t = threading.Thread(target=updater, daemon=True)
    t.start()

    # --- Message loop ---
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    # --- Cleanup ---
    nonlocal_running = False
    gdi32.SelectObject(hdc_mem, oldbmp)
    gdi32.DeleteObject(hbmp)
    user32.ReleaseDC(None, hdc_screen)
    gdi32.DeleteDC(hdc_mem)

if __name__ == "__main__":
    main()
