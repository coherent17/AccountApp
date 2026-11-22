"""擷取本程式自己的視窗存成 PNG（只用 Windows GDI 與標準函式庫，打包進 exe 也能用；煙霧測試用）。

用 PrintWindow 只畫出這個視窗本身的內容：不會拍到螢幕上的其他程式，視窗被遮住或放在螢幕外也可以擷取。
"""

from __future__ import annotations

import ctypes
import struct
import zlib
from ctypes import wintypes


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def grab_window(hwnd: int, path: str) -> None:
    user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    H = wintypes.HANDLE
    for fn, res, args in ((user32.GetDC, H, [H]), (user32.ReleaseDC, ctypes.c_int, [H, H]),
                          (gdi32.CreateCompatibleDC, H, [H]), (gdi32.CreateCompatibleBitmap, H, [H, ctypes.c_int, ctypes.c_int]),
                          (gdi32.SelectObject, H, [H, H]), (gdi32.DeleteObject, wintypes.BOOL, [H]),
                          (gdi32.DeleteDC, wintypes.BOOL, [H]),
                          (gdi32.BitBlt, wintypes.BOOL, [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H,
                                                         ctypes.c_int, ctypes.c_int, wintypes.DWORD]),
                          (gdi32.GetDIBits, ctypes.c_int, [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                                           ctypes.c_void_p, wintypes.UINT]),
                          (user32.PrintWindow, wintypes.BOOL, [H, H, wintypes.UINT]),
                          (user32.GetWindowRect, wintypes.BOOL, [H, ctypes.POINTER(wintypes.RECT)])):
        fn.restype, fn.argtypes = res, args
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        user32.PrintWindow(hwnd, mem, 2)       # PW_RENDERFULLCONTENT：含 WebView2 的畫面
        info = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
    raw = bytearray()
    data = buf.raw
    for row in range(h):
        line = data[row * w * 4:(row + 1) * w * 4]
        rgb = bytearray(w * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]     # BGRA → RGB
        raw += b"\x00" + rgb

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
