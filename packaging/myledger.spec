# -*- mode: python ; coding: utf-8 -*-
# 我的理財帳本 打包：單一執行檔（發行時上傳為 MyLedger.exe）。畫面（v3/ui）打包在 exe 內；
# 不含 Qt（介面由 Windows 內建的 Edge WebView2 顯示）。在 packaging 資料夾執行（或用 build.bat）：
#   pyinstaller --noconfirm --clean myledger.spec   → packaging\dist\我的理財帳本.exe

excluded = ["PySide6", "shiboken6", "tkinter", "unittest", "pydoc", "numpy", "PIL",
            "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.android",
            "webview.platforms.cef"]

hidden = ["openpyxl.cell._writer", "clr", "webview.platforms.edgechromium", "webview.platforms.winforms",
          "v3", "v3.api", "v3.rpc", "v3.paths", "v3.webview2", "v3.screenshot", "v3.devshots",
          "v3.api_accounts", "v3.api_dashboard", "v3.api_data", "v3.api_invest", "v3.api_journal", "v3.api_more",
          "v3.api_reports", "v3.api_settings", "v3.api_txn", "v3.api_update",
          "app.analytics", "app.backup", "app.database", "app.exporter", "app.fmt", "app.importer", "app.investments",
          "app.journal_templates", "app.online", "app.performance", "app.printing", "app.sample_data", "app.search",
          "app.statements", "app.undo", "app.updater", "app.version"]

a = Analysis(
    ["../v3/run.py"],
    pathex=[".."],
    binaries=[],
    datas=[("../v3/ui", "v3/ui"), ("../v3/whatsnew.md", "v3")],          # 含 logo.svg（啟動畫面、側邊欄）
    hiddenimports=hidden,
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
    name="我的理財帳本",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon="app.ico",
    version="version_info.txt",
)
