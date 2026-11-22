# -*- mode: python ; coding: utf-8 -*-
# v3 試作版打包：單一執行檔。畫面（v3/ui）打包在 exe 內；不含 Qt（介面由 Windows 內建的 Edge WebView2 顯示）。
# 在專案根目錄執行：pyinstaller --noconfirm --clean v3/v3.spec（spec 內的路徑相對於 v3/）

excluded = ["PySide6", "shiboken6", "tkinter", "unittest", "pydoc", "numpy", "PIL",
            "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.android",
            "webview.platforms.cef"]

a = Analysis(
    ["run.py"],
    pathex=[".."],
    binaries=[],
    datas=[("ui", "v3/ui")],
    hiddenimports=["openpyxl.cell._writer", "v3", "v3.api", "v3.paths", "webview.platforms.edgechromium",
                   "webview.platforms.winforms", "clr"],
    hookspath=[],
    runtime_hooks=[],
    excludes=excluded,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MyLedger_v3_trial",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon="../app.ico",
    version="../version_info.txt",
)
