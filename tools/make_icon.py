"""由 desktop/ui/logo.svg 產生程式圖示 packaging/app.ico（16～256 像素，PNG 格式的 ICO）。

用 Windows 的 v2 venv 執行（需要 PySide6 的 QtSvg 來繪製 SVG）：
    ..\\venv\\Scripts\\python.exe tools\\make_icon.py
"""

import os
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    buf = QByteArray()
    io = QBuffer(buf)
    io.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(io, "PNG")
    return bytes(buf.data())


def main() -> None:
    QGuiApplication(sys.argv)
    r = QSvgRenderer(os.path.join(ROOT, "desktop", "ui", "logo.svg"))
    images = [png(r, s) for s in SIZES]
    out = os.path.join(ROOT, "packaging", "app.ico")
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, data = b"", b""
    for s, img in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset + len(data))
        data += img
    with open(out, "wb") as f:
        f.write(header + entries + data)
    with open(os.path.join(ROOT, "desktop", "ui", "logo-256.png"), "wb") as f:
        f.write(images[-1])
    print("wrote", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
