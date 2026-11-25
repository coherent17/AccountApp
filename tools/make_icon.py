"""由 desktop/ui/logo.svg（24 像素以下用 logo-small.svg）產生程式圖示 packaging/app.ico、desktop/ui/logo-256.png 與 README 的圖示。

用 Windows 的 venv3 執行（以 Edge 繪製 SVG、Pillow 縮圖；只在開發時使用，不會包進程式）：
    ..\\venv3\\Scripts\\python.exe tools\\make_icon.py
"""

import io
import os
import pathlib
import struct
import subprocess
import tempfile

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "desktop" / "ui"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SMALL = 24          # 這個尺寸（含）以下用簡化版
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def render(svg: pathlib.Path, px: int = 1024) -> Image.Image:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        page, shot = pathlib.Path(tmp, "p.html"), pathlib.Path(tmp, "p.png")
        page.write_text(f'<body style="margin:0;background:transparent"><img src="{svg.as_uri()}" width="{px}" height="{px}" style="display:block">',
                        encoding="utf-8")
        subprocess.run([EDGE, "--headless", "--disable-gpu", f"--user-data-dir={tmp}\\profile", "--default-background-color=00000000",
                        "--allow-file-access-from-files", "--hide-scrollbars", f"--window-size={px},{px}", f"--screenshot={shot}",
                        page.as_uri()], check=True, capture_output=True, timeout=60)
        return Image.open(io.BytesIO(shot.read_bytes())).convert("RGBA")


def png(img: Image.Image, size: int) -> bytes:
    buf = io.BytesIO()
    img.resize((size, size), Image.LANCZOS).save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main() -> None:
    big, small = render(UI / "logo.svg"), render(UI / "logo-small.svg")
    images = [png(small if s <= SMALL else big, s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries, data = b"", b""
    for s, img in zip(SIZES, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset + len(data))
        data += img
    out = ROOT / "packaging" / "app.ico"
    out.write_bytes(header + entries + data)
    (UI / "logo-256.png").write_bytes(images[-1])
    print("wrote", out, out.stat().st_size, "bytes; corner alpha", big.getpixel((2, 2))[3])


if __name__ == "__main__":
    main()
