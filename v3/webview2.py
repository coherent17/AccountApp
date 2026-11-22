"""啟動前檢查 Microsoft Edge WebView2 Runtime（v3 的畫面由它顯示）。

Windows 11 與一般有更新的 Windows 10 都已內建；少數沒有的電腦（長期未更新、精簡版 Windows），
啟動時顯示中文說明，按「是」就下載並執行微軟官方的安裝程式（約 2 MB，不需要系統管理員權限），裝好後繼續開啟。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
import urllib.request

RUNTIME_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
_KEYS = [("HKLM", rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"),
         ("HKLM", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}"),
         ("HKCU", rf"Software\Microsoft\EdgeUpdate\Clients\{RUNTIME_GUID}")]

MB_YESNO, MB_OK, MB_ICONWARNING, MB_ICONERROR, IDYES = 0x4, 0x0, 0x30, 0x10, 6
TITLE = "我的理財帳本"


def installed_version() -> str | None:
    """已安裝的 WebView2 版本；沒有安裝時傳回 None（微軟文件建議的檢查方式：登錄機碼的 pv 值）。"""
    if os.environ.get("MY_LEDGER_FAKE_NO_WEBVIEW2"):      # 測試用：模擬沒有安裝
        return None
    import winreg
    for hive, path in _KEYS:
        root = winreg.HKEY_LOCAL_MACHINE if hive == "HKLM" else winreg.HKEY_CURRENT_USER
        try:
            with winreg.OpenKey(root, path) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
        except OSError:
            continue
        if pv and pv != "0.0.0.0":
            return str(pv)
    return None


def _box(text: str, flags: int) -> int:
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags)


def ensure() -> bool:
    """有 WebView2 時傳回 True；沒有時詢問是否安裝，安裝成功傳回 True，否則顯示說明並傳回 False。"""
    if installed_version():
        return True
    if _box("這台電腦缺少「Microsoft Edge WebView2 Runtime」，新版畫面需要它才能顯示。\n\n"
            "它是微軟提供的免費元件（Windows 11 與大多數 Windows 10 已內建）。\n"
            "要現在從微軟網站下載並安裝嗎？（約 2 MB，需要網路，安裝約 1～2 分鐘）\n\n"
            "您的帳本資料不受影響。", MB_YESNO | MB_ICONWARNING) != IDYES:
        _box("沒有安裝 WebView2，程式無法開啟。\n\n"
             "也可以自行到微軟網站搜尋「WebView2 Runtime」下載安裝，裝好後再開啟本程式。", MB_OK | MB_ICONWARNING)
        return False
    try:
        dest = os.path.join(tempfile.gettempdir(), "MicrosoftEdgeWebview2Setup.exe")
        with urllib.request.urlopen(BOOTSTRAPPER_URL, timeout=60) as r, open(dest, "wb") as f:  # noqa: S310 — 微軟官方網址
            f.write(r.read())
        subprocess.run([dest, "/install"], check=False, timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        _box(f"下載或安裝 WebView2 時發生問題：{e}\n\n請確認網路連線後再開啟本程式重試。", MB_OK | MB_ICONERROR)
        return False
    if installed_version():
        return True
    _box("WebView2 似乎沒有安裝完成。請重新開機後再開啟本程式；如果仍然無法開啟，請改用 v2 版本並與我們聯絡。",
         MB_OK | MB_ICONERROR)
    return False
