@echo off
chcp 65001 >nul
REM 建置「我的理財帳本.exe」（在 Windows 上執行）。發行時把它上傳為 MyLedger.exe。
cd /d "%~dp0"
if not exist ..\venv3 (
    python -m venv ..\venv3
)
call ..\venv3\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r ..\requirements.txt pyinstaller
pyinstaller --noconfirm --clean myledger.spec
echo.
echo 完成！執行檔位於 packaging\dist\我的理財帳本.exe
pause
