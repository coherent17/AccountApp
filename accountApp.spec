# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包設定：產生單一執行檔「我的理財帳本.exe」

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
    ["run.py"],
    pathex=[],
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
    icon="app.ico",
    version="version_info.txt",
)
