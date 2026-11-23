"""自動更新的檔案操作：判斷能否自動更新、下載位置、換檔、重新開啟、清除舊檔。"""

from __future__ import annotations

import os
import subprocess
import sys


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def cleanup_old_exe() -> None:
    """刪除上次更新留下的舊版程式（MyLedger.exe.old）。"""
    if not can_self_update():
        return
    try:
        os.remove(sys.executable + ".old")
    except OSError:
        pass


def _download_dir() -> str:
    """exe 所在資料夾可寫入就下載到那裡（同一磁碟才能直接換檔），否則放到「下載」資料夾。"""
    here = os.path.dirname(sys.executable)
    test = os.path.join(here, ".myledger_write_test")
    try:
        with open(test, "w"):
            pass
        os.remove(test)
        return here
    except OSError:
        d = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(d, exist_ok=True)
        return d


def install(new_path: str, exe: str | None = None) -> None:
    """以 new_path 取代正在執行的 exe（Windows 允許將執行中的程式改名）。失敗時還原並拋出 OSError。"""
    exe = exe or sys.executable
    old = exe + ".old"
    if os.path.exists(old):
        os.remove(old)
    os.replace(exe, old)
    try:
        os.replace(new_path, exe)
    except OSError:
        os.replace(old, exe)
        raise


def restart(exe: str | None = None) -> None:
    """開啟新版程式。清除 PyInstaller 的環境變數，避免新程式誤用舊程式的暫存資料夾。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe or sys.executable], env=env, close_fds=True, creationflags=flags,
                     cwd=os.path.dirname(exe or sys.executable))
