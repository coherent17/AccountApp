"""第二份備份（電腦以外的地方）：隨身碟、外接硬碟或 OneDrive 等雲端同步資料夾。

* 「自動備份」資料夾跟帳本在同一顆硬碟上，硬碟壞掉就一起不見；這裡把帳本另外複製一份到她選的資料夾。
* 每天第一次開啟時備份一次，關閉程式時（本次有變更）再備份一次；同一天只保留一個檔，覆蓋成當天最新的內容，
  保留最近 KEEP 天。憑證附件只複製新的檔案，不會刪除那邊的任何檔案。
* 資料夾暫時不能用（隨身碟沒插、雲端資料夾不存在）時不會影響記帳，只記下失敗原因，
  在「設定」與「總覽」提醒。
不需要 Qt。
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil

from .database import Database

SUBFOLDER = "我的理財帳本備份"
PREFIX = "帳本備份_"
KEEP = 30
REMIND_DAYS = 7

# 設定鍵
DIR_KEY = "backup_extra_dir"
LAST_KEY = "backup_extra_last"      # 上次成功的時間（ISO）
ERROR_KEY = "backup_extra_error"    # 上次失敗的原因（成功後清空）


def target_dir(chosen: str) -> str:
    """她選的資料夾底下的「我的理財帳本備份」子資料夾（避免檔案散在隨身碟根目錄）。"""
    if os.path.basename(os.path.normpath(chosen)) == SUBFOLDER:
        return chosen
    return os.path.join(chosen, SUBFOLDER)


def onedrive_dir() -> str:
    """Windows 的 OneDrive 資料夾（沒有安裝時傳回空字串）。"""
    for key in ("OneDriveConsumer", "OneDrive", "OneDriveCommercial"):
        path = os.environ.get(key, "")
        if path and os.path.isdir(path):
            return path
    return ""


def same_drive(a: str, b: str) -> bool:
    """兩個路徑是否在同一顆磁碟（Windows 比較磁碟機代號）。"""
    da = os.path.splitdrive(os.path.abspath(a))[0].upper()
    db_ = os.path.splitdrive(os.path.abspath(b))[0].upper()
    return bool(da) and da == db_


def run(db: Database, data_folder: str, today: _dt.date | None = None) -> str:
    """立即備份到第二個位置，傳回備份檔路徑。失敗時記下原因並丟出 OSError。"""
    chosen = db.get_setting(DIR_KEY, "")
    if not chosen:
        raise OSError("尚未選擇第二份備份的位置")
    try:
        if not os.path.isdir(chosen):
            raise OSError(f"找不到資料夾「{chosen}」（隨身碟或外接硬碟是否已插上？）")
        dest_dir = target_dir(chosen)
        os.makedirs(dest_dir, exist_ok=True)
        day = today or _dt.date.today()
        dest = os.path.join(dest_dir, f"{PREFIX}{day:%Y%m%d}.db")
        tmp = dest + ".tmp"
        db.backup_to(tmp)
        os.replace(tmp, dest)
        _copy_attachments(os.path.join(data_folder, "憑證附件"), os.path.join(dest_dir, "憑證附件"))
        _prune(dest_dir)
    except Exception as e:  # noqa: BLE001  （sqlite3.Error 等也一併當作備份失敗）
        db.set_setting(ERROR_KEY, f"{_dt.datetime.now():%Y-%m-%d %H:%M}　{e}")
        raise OSError(str(e)) from None
    db.set_setting(LAST_KEY, _dt.datetime.now().isoformat(timespec="seconds"))
    db.set_setting(ERROR_KEY, "")
    return dest


def _copy_attachments(src: str, dest: str) -> None:
    if not os.path.isdir(src):
        return
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        out = os.path.join(dest, rel) if rel != "." else dest
        os.makedirs(out, exist_ok=True)
        for f in files:
            a, b = os.path.join(root, f), os.path.join(out, f)
            if not os.path.exists(b) or os.path.getsize(a) != os.path.getsize(b):
                shutil.copy2(a, b)


def _prune(dest_dir: str) -> None:
    files = sorted(f for f in os.listdir(dest_dir) if f.startswith(PREFIX) and f.endswith(".db"))
    for old in files[:-KEEP]:
        try:
            os.remove(os.path.join(dest_dir, old))
        except OSError:
            pass


def due_today(db: Database) -> bool:
    """今天還沒成功備份過（每天第一次開啟時使用）。"""
    if not db.get_setting(DIR_KEY, ""):
        return False
    return db.get_setting(LAST_KEY, "")[:10] != _dt.date.today().isoformat()


def try_run(db: Database, data_folder: str) -> bool:
    """背景用：失敗只記錄原因、不顯示錯誤。"""
    if not db.get_setting(DIR_KEY, ""):
        return False
    try:
        run(db, data_folder)
        return True
    except OSError:
        return False


def status(db: Database) -> dict:
    """設定頁與總覽提醒用：位置、上次成功時間、距今天數、失敗原因、是否需要提醒。"""
    chosen = db.get_setting(DIR_KEY, "")
    last = db.get_setting(LAST_KEY, "")
    days = None
    if last:
        try:
            days = (_dt.date.today() - _dt.date.fromisoformat(last[:10])).days
        except ValueError:
            days = None
    err = db.get_setting(ERROR_KEY, "")
    remind = bool(chosen) and (days is None or days >= REMIND_DAYS)
    return {"dir": chosen, "last": last, "days": days, "error": err, "remind": remind}
