"""檢查新版本與一鍵更新（與 v2 相同的流程：GitHub 最新版 → 下載並核對 SHA-256 → 備份帳本 → 換檔 → 重新開啟）。"""

from __future__ import annotations

import datetime as dt
import os
import threading

from app import online, updater
from app.version import APP_VERSION

from v3.rpc import exposed


class UpdateApi:
    _dl = None      # 下載進度：{"got", "total", "done", "path", "error"}

    @exposed
    def update_settings(self) -> dict:
        db = self._db
        return {"auto": db.get_setting("update_auto", "1") == "1",
                "due": db.get_setting("update_auto", "1") == "1"
                and db.get_setting("update_last_check", "") != dt.date.today().isoformat(),
                "skip": db.get_setting("update_skip", ""), "can_self_update": updater.can_self_update()}

    @exposed(db=False)
    def update_fetch(self) -> dict:
        try:
            rel = online.fetch_latest_release()
        except online.OfflineError as e:
            raise ValueError(str(e)) from None
        self._dbt.run(self._db.set_setting, "update_last_check", dt.date.today().isoformat())
        return {**rel, "current": APP_VERSION, "newer": online.is_newer(rel["version"], APP_VERSION)}

    @exposed
    def update_skip(self, version: str) -> None:
        self._db.set_setting("update_skip", version)

    @exposed(db=False)
    def update_start(self, rel: dict) -> None:
        """在背景下載；畫面用 update_progress 查詢進度。"""
        dest = os.path.join(updater._download_dir(), f"MyLedger_{rel['version']}.exe")
        state = {"got": 0, "total": rel.get("size", 0), "done": False, "path": "", "error": ""}
        type(self)._dl = state

        def work():
            try:
                online.download(rel["url"], dest, rel.get("size", 0), rel.get("sha256", ""),
                                lambda got, total: state.update(got=got, total=total))
                state["path"] = dest
            except online.OfflineError as e:
                state["error"] = str(e)
            except Exception as e:  # noqa: BLE001
                state["error"] = f"下載失敗：{e}"
            state["done"] = True
        threading.Thread(target=work, daemon=True).start()

    @exposed(db=False)
    def update_progress(self) -> dict:
        return dict(type(self)._dl or {})

    @exposed(db=False)
    def update_install(self, path: str) -> dict:
        """換成新版並重新開啟。程式放在無法寫入的資料夾時，傳回下載位置請她手動換檔。"""
        import sys
        exe = sys.executable
        if os.path.dirname(path) != os.path.dirname(exe):
            return {"manual": path}
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._dbt.run(self._db.backup_to, os.path.join(self._folder, "自動備份", f"更新前備份_v{APP_VERSION}_{stamp}.db"))
        try:
            updater.install(path, exe)
        except OSError as e:
            raise ValueError(f"無法替換程式檔（{e.strerror or e}），目前的程式與資料都沒有改變。") from None
        return {"installed": True}

    @exposed(db=False)
    def restart_app(self) -> None:
        """關閉帳本後開啟新版程式，再關閉這個視窗。"""
        import sys
        self._dbt.run(self._db.close)
        updater.restart(sys.executable)
        self._window.destroy()
