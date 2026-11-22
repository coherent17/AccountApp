# -*- mode: python ; coding: utf-8 -*-
# v2（PySide6 介面，已停用）的打包設定，只為了需要時重建舊版或執行 v2 的測試工具而保留。
# 在這個資料夾執行：pyinstaller --noconfirm --clean accountApp.spec

excluded = [
    "PySide6.QtNetwork",
    "tkinter", "unittest", "pydoc", "numpy", "PIL",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtSerialPort",
]

a = Analysis(
    ["run_v2.py"],
    pathex=["../.."],
    binaries=[],
    datas=[],
    hiddenimports=["openpyxl.cell._writer"],
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
    icon="../app.ico",
    version="../version_info.txt",
)
