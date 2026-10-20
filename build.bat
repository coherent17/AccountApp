@echo off
chcp 65001 >nul
REM 建置「我的理財帳本.exe」（在 Windows 上執行）
cd /d "%~dp0"
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller pillow
python tools\make_icon.py app.ico
pyinstaller --noconfirm --clean accountApp.spec
echo.
echo 完成！執行檔位於 dist\我的理財帳本.exe
pause
