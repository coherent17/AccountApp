"""資料夾位置（不需要 Qt）。

必須與 v2 的 context.data_dir() 找到同一個資料夾：Qt 的 DocumentsLocation 在 Windows 上取自
SHGetKnownFolderPath(FOLDERID_Documents)，所以這裡也用同一個 API（「文件」被移到 OneDrive 或 D 槽時也一樣）。
"""

from __future__ import annotations

import os
import sys

APP_NAME = "我的理財帳本"


def documents_dir() -> str:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD),
                        ("d4", ctypes.c_ubyte * 8)]
        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            if path:
                return path
    return os.path.join(os.path.expanduser("~"), "Documents")


def data_dir() -> str:
    override = os.environ.get("MY_LEDGER_DATA_DIR")
    path = override or os.path.join(documents_dir(), APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path
