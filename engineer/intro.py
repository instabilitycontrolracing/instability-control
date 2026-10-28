"""The intro: a see-through layer (per-pixel alpha) where only the watch shows at first, then the
window forms around it. Drawn with Skia into a Windows layered window; at the end the real app
window is shown underneath at exactly the same spot and the layer fades away."""
import ctypes, time
from ctypes import wintypes
import numpy as np
import skia

from .watch_skia import Intro, INTRO_LEN

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x8, 0x80, 0x08000000
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
SW_SHOWNOACTIVATE = 4
PM_REMOVE = 1

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


_wndproc_ref = None

# 64-bit safe signatures (handles are pointer-sized)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p, ctypes.c_void_p, wintypes.HDC,
                                       ctypes.c_void_p, wintypes.COLORREF, ctypes.c_void_p, wintypes.DWORD]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]


def _wndproc(h, m, w, l):
    return user32.DefWindowProcW(h, m, w, l)


class LayeredWindow:
    def __init__(self, x, y, w, h):
        global _wndproc_ref
        self.x, self.y, self.w, self.h = x, y, w, h
        hinst = kernel32.GetModuleHandleW(None)
        _wndproc_ref = WNDPROC(_wndproc)
        wc = WNDCLASSEXW(); wc.cbSize = ctypes.sizeof(WNDCLASSEXW); wc.lpfnWndProc = _wndproc_ref
        wc.hInstance = hinst; wc.lpszClassName = "RaceEngineerIntro"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                                           "RaceEngineerIntro", "Race Engineer intro", WS_POPUP,
                                           x, y, w, h, None, None, hinst, None)
        # 32-bit top-down DIB we draw into directly with Skia (premultiplied BGRA = what Windows wants)
        bmi = BITMAPINFOHEADER(); bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight, bmi.biPlanes, bmi.biBitCount = w, -h, 1, 32
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        bits = ctypes.c_void_p()
        self.bmp = gdi32.CreateDIBSection(self.mem_dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        gdi32.SelectObject(self.mem_dc, self.bmp)
        buf = (ctypes.c_ubyte * (w * h * 4)).from_address(bits.value)
        self.pixels = np.ctypeslib.as_array(buf).reshape(h, w, 4)
        self.surface = skia.Surface(self.pixels, colorType=skia.kBGRA_8888_ColorType, alphaType=skia.kPremul_AlphaType)
        self.shown = False

    def present(self, alpha=255):
        self.surface.flushAndSubmit()
        size = wintypes.SIZE(self.w, self.h); src = wintypes.POINT(0, 0); pos = wintypes.POINT(self.x, self.y)
        bf = BLENDFUNCTION(AC_SRC_OVER, 0, int(max(0, min(255, alpha))), AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.hwnd, self.screen_dc, ctypes.byref(pos), ctypes.byref(size), self.mem_dc,
                                   ctypes.byref(src), 0, ctypes.byref(bf), ULW_ALPHA)
        if not self.shown:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE); self.shown = True
        self.pump()

    def pump(self):
        msg = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg)); user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        user32.DestroyWindow(self.hwnd)
        gdi32.DeleteObject(self.bmp); gdi32.DeleteDC(self.mem_dc); user32.ReleaseDC(None, self.screen_dc)


def play(rect, k, show_main, main_ready, log=print):
    """rect = (x, y, w, h) physical px where the app window will be. show_main() shows it;
    main_ready() -> True once the page has painted."""
    x, y, w, h = rect
    lw = LayeredWindow(x, y, w, h)
    lt = time.localtime()
    start_clock = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec + (time.time() % 1)
    intro = Intro(w, h, k, start_clock)
    canvas = lw.surface.getCanvas()
    t0 = time.perf_counter()
    frames = 0
    shown_at = None
    while True:
        t = time.perf_counter() - t0
        intro.frame(canvas, t)
        lw.present()
        frames += 1
        if t >= INTRO_LEN and shown_at is None:
            show_main(); shown_at = t
        if shown_at is not None and (main_ready() or t - shown_at > 3.0):
            break
        time.sleep(0.001)
    # hold one beat so the page is surely on screen, then fade the layer away
    fade = 0.28
    f0 = time.perf_counter()
    while True:
        p = (time.perf_counter() - f0) / fade
        if p >= 1:
            break
        intro.frame(canvas, time.perf_counter() - t0)
        lw.present(255 * (1 - p) ** 1.6)
    lw.close()
    log(f"[intro] {frames / max(.001, time.perf_counter() - t0):.0f} fps")
