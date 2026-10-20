"""以程式繪製的 App 圖示產生 Windows 的 .ico 檔。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.theme import app_icon  # noqa: E402

app = QApplication([])
pm = app_icon().pixmap(256, 256)
buf = QBuffer()
buf.open(QIODevice.OpenModeFlag.WriteOnly)
pm.save(buf, "PNG")
img = Image.open(io.BytesIO(bytes(buf.data())))
out = sys.argv[1] if len(sys.argv) > 1 else "app.ico"
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon:", out)
