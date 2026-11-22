@echo off
chcp 65001 >nul
REM 重建 v2（PySide6 介面，已停用）：只在需要舊版時使用。目前發行的版本請用 packaging\build.bat。
cd /d "%~dp0"
python -m pip install -r ..\..\requirements-v2.txt pyinstaller
pyinstaller --noconfirm --clean accountApp.spec
echo 完成！執行檔位於 packaging\legacy_v2\dist\我的理財帳本.exe
pause
