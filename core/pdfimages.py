"""把幾張 JPEG 圖片做成 PDF（每張一頁，A4 直式、等比例縮放置中）。只用標準函式庫。

意見回饋用：每一頁由畫面先畫成圖片（含中文說明與螢幕截圖），所以 PDF 不需要內嵌中文字型。
"""

from __future__ import annotations

import datetime as _dt

A4 = (595.28, 841.89)
MARGIN = 24.0


def jpeg_size(data: bytes) -> tuple[int, int]:
    """讀取 JPEG 的寬高（SOF 標記）。"""
    if data[:2] != b"\xff\xd8":
        raise ValueError("不是 JPEG 圖片")
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h
        i += 2 + length
    raise ValueError("無法讀取 JPEG 尺寸")


def _text(s: str) -> bytes:
    """PDF 文字字串（UTF-16BE，可放中文標題）。"""
    return b"<FEFF" + s.encode("utf-16-be").hex().upper().encode() + b">"


def write(path: str, jpegs: list[bytes], title: str = "") -> None:
    if not jpegs:
        raise ValueError("沒有可以放進 PDF 的頁面")
    objs: list[bytes] = []          # objs[n-1] 是第 n 個物件的內容

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    catalog = add(b"")              # 稍後填入
    pages = add(b"")
    kids = []
    W, H = A4
    for n, img in enumerate(jpegs):
        w, h = jpeg_size(img)
        im = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
                 b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n" % (w, h, len(img)) + img + b"\nendstream")
        s = min((W - 2 * MARGIN) / w, (H - 2 * MARGIN) / h)
        dw, dh = w * s, h * s
        x, y = (W - dw) / 2, H - MARGIN - dh
        draw = b"q %.2f 0 0 %.2f %.2f %.2f cm /Im%d Do Q" % (dw, dh, x, y, n)
        content = add(b"<< /Length %d >>\nstream\n" % len(draw) + draw + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /XObject << /Im%d %d 0 R >> >> "
                        b"/Contents %d 0 R >>" % (pages, W, H, n, im, content)))
    objs[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages
    objs[pages - 1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    info = add(b"<< /Title " + _text(title) + b" /Producer " + _text("我的理財帳本")
               + b" /CreationDate (D:" + _dt.datetime.now().strftime("%Y%m%d%H%M%S").encode() + b") >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, info, xref)
    with open(path, "wb") as f:
        f.write(out)
