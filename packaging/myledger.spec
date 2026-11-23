# -*- mode: python ; coding: utf-8 -*-
# 我的理財帳本 打包：單一執行檔（發行時上傳為 MyLedger.exe）。畫面（desktop/ui）打包在 exe 內；
# 不含 Qt（介面由 Windows 內建的 Edge WebView2 顯示）。在 packaging 資料夾執行（或用 build.bat）：
#   pyinstaller --noconfirm --clean myledger.spec   → packaging\dist\我的理財帳本.exe

excluded = ["PySide6", "shiboken6", "tkinter", "unittest", "pydoc", "numpy", "PIL",
            "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa", "webview.platforms.android",
            "webview.platforms.cef"]

hidden = ["openpyxl.cell._writer", "clr", "webview.platforms.edgechromium", "webview.platforms.winforms",
          "desktop", "desktop.api", "desktop.rpc", "desktop.paths", "desktop.webview2", "desktop.screenshot", "desktop.devshots",
          "desktop.api_accounts", "desktop.api_dashboard", "desktop.api_data", "desktop.api_invest", "desktop.api_journal", "desktop.api_more",
          "desktop.api_reports", "desktop.api_settings", "desktop.api_txn", "desktop.api_update", "desktop.api_tools",
          "core.analytics", "core.backup", "core.bankmatch", "core.health", "core.monthclose", "core.quick", "core.reminders", "core.database", "core.exporter", "core.fmt", "core.importer", "core.investments",
          "core.journal_templates", "core.online", "core.performance", "core.printing", "core.sample_data", "core.search",
          "core.statements", "core.undo", "core.updater", "core.version"]

a = Analysis(
    ["../desktop/run.py"],
    pathex=[".."],
    binaries=[],
    datas=[("../desktop/ui", "desktop/ui"), ("../desktop/whatsnew.md", "desktop")],          # 含 logo.svg（啟動畫面、側邊欄）
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
