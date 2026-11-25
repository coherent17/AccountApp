"""檢查新版本與一鍵更新（與 v2 相同的流程：GitHub 最新版 → 下載並核對 SHA-256 → 備份帳本 → 換檔 → 重新開啟）。"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading

from core import online, updater
from core.version import APP_VERSION

from desktop.rpc import exposed


CHECK_EVERY = dt.timedelta(hours=4)     # 程式開著時，每 4 小時再檢查一次新版本


class UpdateApi:
    _dl = None      # 下載進度：{"got", "total", "done", "path", "error"}

    @exposed
    def update_settings(self) -> dict:
        """自動檢查：開啟程式時，以及開著的期間每 4 小時（上次成功檢查超過 4 小時才會再查）。"""
        db = self._db
        auto = db.get_setting("update_auto", "1") == "1"
        last = db.get_setting("update_last_check_at", "")
        try:
            due = not last or dt.datetime.now() - dt.datetime.fromisoformat(last) >= CHECK_EVERY
        except ValueError:
            due = True
        return {"auto": auto, "due": auto and due, "skip": db.get_setting("update_skip", ""),
                "can_self_update": updater.can_self_update()}

    @exposed(db=False)
    def update_fetch(self) -> dict:
        try:
            rel = online.fetch_latest_release()
        except online.OfflineError as e:
            raise ValueError(str(e)) from None
        def mark():
            self._db.set_setting("update_last_check", dt.date.today().isoformat())      # v2 使用的鍵（一天一次）
            self._db.set_setting("update_last_check_at", dt.datetime.now().isoformat(timespec="seconds"))
        self._dbt.run(mark)
        return {**rel, "current": APP_VERSION, "newer": online.is_newer(rel["version"], APP_VERSION)}

    @exposed
    def update_skip(self, version: str) -> None:
        self._db.set_setting("update_skip", version)

    @exposed(db=False)
    def update_start(self, rel: dict) -> None:
        """在背景下載；畫面用 update_progress 查詢進度。"""
        dest = os.path.join(updater._download_dir(), f"MyLedger_{rel['version']}.exe")
        type(self)._rel = rel
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
        rel = getattr(type(self), "_rel", None) or {}
        if rel.get("version"):      # 更新後第一次開啟時，用這份說明顯示「已更新到…」
            self._dbt.run(self._db.set_setting, "update_notes",
                          json.dumps({"version": rel["version"], "notes": rel.get("notes", "")}, ensure_ascii=False))
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
        type(self)._skip_farewell = True      # 更新時直接關閉，不顯示結束畫面
        self._window.destroy()

    @exposed
    def whats_new(self) -> dict | None:
        """這個版本第一次開啟：傳回「已更新到…」要顯示的說明（每個版本只顯示一次）。
        說明優先用更新時從 GitHub 存下的內容，否則用程式內附的 desktop/whatsnew.md。
        全新安裝不顯示（歡迎畫面會記下目前版本）。"""
        db = self._db
        seen = db.get_setting("last_seen_version", "")
        db.set_setting("last_seen_version", APP_VERSION)
        raw = db.get_setting("update_notes", "")
        db.set_setting("update_notes", "")
        if seen == APP_VERSION:
            return None
        notes = ""
        try:
            saved = json.loads(raw) if raw else {}
            if saved.get("version") == APP_VERSION:
                notes = saved.get("notes", "")
        except ValueError:
            pass
        if not notes:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whatsnew.md")
            try:
                with open(path, encoding="utf-8") as f:
                    notes = f.read()
            except OSError:
                return None
        return {"version": APP_VERSION, "notes": notes}

    @exposed
    def tour_status(self) -> bool:
        """新介面導覽是否還沒看過（第一次開啟、已經看過的都不顯示）。"""
        return self._db.get_setting("v3_tour_done", "") != "1"

    @exposed
    def tour_done(self) -> None:
        self._db.set_setting("v3_tour_done", "1")

    # ------------------------------------------------------------------ 操作導覽：看過哪些（設定 guides，只影響提示，不是帳務資料）
    def _guides(self) -> dict:
        g = self._db.get_json("guides", {})
        g = g if isinstance(g, dict) else {}
        seen, offered = g.get("seen"), g.get("offered")
        return {"seen": seen if isinstance(seen, dict) else {}, "offered": offered if isinstance(offered, list) else [], "off": bool(g.get("off"))}

    @exposed
    def guide_state(self) -> dict:
        return self._guides()

    @exposed
    def guide_mark(self, gid: str, what: str) -> dict:
        """what：seen（看完）、offered（提示過或中途結束，不再主動提示）。"""
        g = self._guides()
        gid = str(gid)[:40]
        if what == "seen":
            g["seen"][gid] = dt.date.today().isoformat()
        if gid not in g["offered"]:
            g["offered"].append(gid)
        self._db.set_json("guides", g)
        return g

    @exposed
    def guide_off(self, off: bool) -> dict:
        g = self._guides()
        g["off"] = bool(off)
        self._db.set_json("guides", g)
        return g

    @exposed
    def guide_reset(self) -> dict:
        self._db.set_json("guides", {"seen": {}, "offered": [], "off": False})
        return self._guides()
