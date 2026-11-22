"""v3：畫面（HTML/JS）透過 pywebview 呼叫的 Python 介面。

帳務計算全部沿用 v2 的 app/ 模組（database、investments、statements…），這裡只把資料整理成畫面需要的格式。
傳回的金額都是數字，格式化（千分位、幣別符號、正負號）在畫面上做。

錯誤處理：帳務規則的錯誤（ValueError，例如「此期間已結帳」）以 {"__error__": 訊息} 傳回，畫面直接顯示給使用者；
其他未預期的錯誤記到資料夾的「錯誤紀錄.log」並傳回友善的訊息（帳本不會因此關閉）。
"""

from __future__ import annotations

import datetime as dt
import os
import sys
import traceback

from app.version import APP_VERSION
from app.database import CURRENCIES, TYPE_LABELS, ZERO_DECIMAL_CURRENCIES, Database
from v3.api_accounts import AccountsApi
from v3.api_dashboard import DashboardApi
from v3.api_data import DataApi
from v3.api_invest import InvestApi
from v3.api_journal import JournalApi
from v3.api_reports import ReportsApi
from v3.api_settings import SettingsApi
from v3.api_update import UpdateApi
from v3.api_txn import TxnApi
from v3.rpc import DbThread, exposed  # noqa: F401 — DbThread 由 run.py 匯入


class ApiBase:
    def __init__(self, dbt: DbThread, db: Database, folder: str, demo: bool):
        self._dbt = dbt
        self._db = db
        self._folder = folder
        self._demo = demo
        self._window = None

    def _log_error(self, where: str, e: Exception) -> None:
        try:
            with open(os.path.join(self._folder, "錯誤紀錄.log"), "a", encoding="utf-8") as f:
                f.write(f"\n[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] v{APP_VERSION} v3 {where}\n")
                f.write("".join(traceback.format_exception(e)))
        except OSError:
            pass
        traceback.print_exception(e, file=sys.stderr)

    @exposed
    def meta(self) -> dict:
        db = self._db
        return {
            "version": APP_VERSION,
            "base": db.base_currency,
            "currencies": {k: {"name": v[0], "symbol": v[1], "decimals": 0 if k in ZERO_DECIMAL_CURRENCIES else 2}
                           for k, v in CURRENCIES.items()},
            "type_labels": TYPE_LABELS,
            "owner": db.get_setting("owner_name"),
            "demo": self._demo,
            "sample": db.get_setting("sample_data") == "1",
            "theme": db.get_setting("theme_mode", "light"),
            "font_scale": db.get_setting("font_scale", "large"),
            "animations": db.get_setting("animations", "1") != "0",
            "folder": self._folder,
            "online": db.get_setting("online_updates", "0") == "1",
            "smoke": bool(os.environ.get("MY_LEDGER_SMOKE_DIR") or os.environ.get("MY_LEDGER_V3_SHOT")),
        }

    @exposed
    def set_pref(self, key: str, value: str) -> bool:
        """外觀偏好（深色模式、字型大小）：與 v2 共用同一個設定鍵，切換立即生效、不用重開。"""
        if key not in ("theme_mode", "font_scale", "animations"):
            return False
        self._db.set_setting(key, value)
        return True

    @exposed
    def date_range(self) -> list[str]:
        return list(self._db.date_range())

    # ------------------------------------------------------------------ 檔案
    @exposed(db=False)
    def pick_files(self, title: str = "選擇附件", kinds: str = "attach") -> list[str]:
        import webview
        types = {"attach": ("圖片或文件 (*.png;*.jpg;*.jpeg;*.pdf;*.heic;*.xlsx;*.docx)", "所有檔案 (*.*)"),
                 "import": ("Excel 或 CSV (*.xlsx;*.xlsm;*.csv)", "所有檔案 (*.*)"),
                 "db": ("帳本檔 (*.db)", "所有檔案 (*.*)")}[kinds]
        res = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=kinds == "attach",
                                              file_types=types)
        return list(res or [])

    @exposed(db=False)
    def open_url(self, url: str) -> bool:
        import webbrowser
        if not url.startswith("https://"):
            raise ValueError("不支援的網址")
        webbrowser.open(url)
        return True

    @exposed(db=False)
    def open_path(self, path: str) -> bool:
        if not path or not os.path.exists(path):
            raise ValueError("找不到這個檔案，可能已被移動或刪除。")
        os.startfile(path)  # noqa: S606 — 只開啟帳本資料夾內的檔案或使用者選的檔案
        return True


class Api(JournalApi, UpdateApi, SettingsApi, DataApi, ReportsApi, InvestApi, AccountsApi, TxnApi, DashboardApi, ApiBase):
    """pywebview 的 js_api：所有畫面可呼叫的方法（各頁的方法分在 api_*.py）。"""
