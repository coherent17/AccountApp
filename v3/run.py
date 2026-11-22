"""v3 進入點：pywebview（Windows 內建的 Edge WebView2）視窗 + HTML 畫面 + v2 的帳務程式。

開啟與關閉時做的事與 v2 相同：刪除更新留下的舊程式、每天第一次開啟時自動備份（保留 30 份）、
第二份備份（每天第一次開啟，以及本次有記帳時於關閉時），錯誤寫入資料夾的「錯誤紀錄.log」。

環境變數：
* MY_LEDGER_DATA_DIR：資料夾（與 v2 相同）。
* MY_LEDGER_V3_DEMO=1：不碰真正的帳本，在暫存資料夾建立範例帳本（試用、截圖用）。
* MY_LEDGER_SMOKE_DIR：煙霧測試，開啟每一頁截圖後關閉（與 v2 相同）。
* MY_LEDGER_V3_SHOT：開發用自動截圖（v3/devshots.py）。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
import traceback

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)

from app.database import Database  # noqa: E402
from app.version import APP_VERSION  # noqa: E402
from v3.api import Api, DbThread  # noqa: E402
from v3.paths import data_dir  # noqa: E402

UI = os.path.join(HERE, "v3", "ui", "index.html")


def _log_crash(folder: str, e: BaseException) -> None:
    try:
        with open(os.path.join(folder, "錯誤紀錄.log"), "a", encoding="utf-8") as f:
            f.write(f"\n[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] v{APP_VERSION} v3 啟動\n")
            f.write("".join(traceback.format_exception(e)))
    except OSError:
        pass


def open_ledger() -> tuple[Database, str, bool]:
    if os.environ.get("MY_LEDGER_V3_DEMO") or (os.environ.get("MY_LEDGER_V3_SHOT") and not os.environ.get("MY_LEDGER_DATA_DIR")):
        from app.sample_data import load_sample_data
        folder = tempfile.mkdtemp(prefix="myledger_v3_demo_")
        db = Database(os.path.join(folder, "理財帳本.db"))
        db.set_setting("owner_name", "游媽媽")
        load_sample_data(db)
        db.set_setting("first_run_done", "1")
        db.clear_undo()
        return db, folder, True
    folder = data_dir()
    db = Database(os.path.join(folder, "理財帳本.db"))
    smoke = bool(os.environ.get("MY_LEDGER_SMOKE_DIR"))
    try:
        db.auto_backup(os.path.join(folder, "自動備份"))
    except Exception:  # noqa: BLE001 — 備份失敗不影響開啟
        pass
    from app import backup
    if backup.due_today(db) and not smoke:
        backup.try_run(db, folder)      # 每天第一次開啟：第二份備份（隨身碟／OneDrive）
    return db, folder, False


def main() -> int:
    from v3 import webview2
    if not webview2.ensure():
        return 1
    from app.updater import cleanup_old_exe
    cleanup_old_exe()
    shot = os.environ.get("MY_LEDGER_V3_SHOT")
    smoke = os.environ.get("MY_LEDGER_SMOKE_DIR")
    close_test = os.environ.get("MY_LEDGER_V3_CLOSE_TEST")      # 開發用：測試結束畫面
    if shot or smoke or close_test:
        # 自動截圖時視窗放在螢幕外、不搶焦點，不打擾正在使用電腦的人；關閉 Edge 的遮蔽偵測，螢幕外也照常繪製
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--disable-features=CalculateNativeWinOcclusion"
    import webview
    dbt = DbThread()
    try:
        db, folder, demo = dbt.run(open_ledger)
    except Exception as e:  # noqa: BLE001
        _log_crash(data_dir(), e)
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"無法開啟帳本：{e}\n\n詳細內容已記錄在資料夾的「錯誤紀錄.log」。",
                                         "我的理財帳本", 0x10)
        return 1
    start_changes = dbt.run(lambda: db.conn.total_changes)
    api = Api(dbt, db, folder, demo)
    title = "我的理財帳本" + ("（範例帳本）" if demo else "")
    place = {"x": -4000, "y": 40, "focus": False} if (shot or smoke or close_test) else {"maximized": True}
    win = webview.create_window(title, UI, js_api=api, width=1440, height=900, min_size=(1100, 700),
                                background_color="#F4F5FA", **place)
    api._window = win
    from v3 import devshots

    # 結束畫面：按關閉時先顯示「正在儲存帳本…」，完成第二份備份後顯示「帳本已安全儲存」，再關閉視窗
    state = {"closing": False, "backed_up": False}

    def on_closing():
        if state["closing"] or shot or smoke or getattr(api, "_skip_farewell", False):
            return True
        state["closing"] = True
        threading.Thread(target=farewell, daemon=True).start()
        return False

    def farewell():
        steps = ["今天的紀錄都已寫入帳本"]
        try:
            win.evaluate_js(f"window.__farewell({json.dumps(steps, ensure_ascii=False)}, false)")
            if not demo and dbt.run(lambda: db.conn is not None and db.conn.total_changes != start_changes):
                from app import backup
                if dbt.run(backup.try_run, db, folder):
                    steps.append("第二份備份（隨身碟／OneDrive）已完成")
                state["backed_up"] = True
            time.sleep(0.5)
            win.evaluate_js(f"window.__farewell({json.dumps(steps, ensure_ascii=False)}, true)")
            time.sleep(1.3)
        except Exception:  # noqa: BLE001 — 結束畫面失敗也要能關閉
            pass
        win.destroy()

    win.events.closing += on_closing
    if close_test:
        webview.start(devshots.closing, (win, close_test), http_server=True, gui="edgechromium", debug=False)
    elif shot:
        webview.start(devshots.run, (win, shot), http_server=True, gui="edgechromium", debug=False)
    elif smoke:
        webview.start(devshots.smoke, (win, smoke), http_server=True, gui="edgechromium", debug=False)
    else:
        webview.start(http_server=True, gui="edgechromium", debug=False)

    def shutdown():
        if db.conn is None:
            return
        if not demo and not smoke and not state["backed_up"] and db.conn.total_changes != start_changes:
            from app import backup
            backup.try_run(db, folder)  # 本次有記帳：關閉前把最新的帳本再複製到第二個備份位置
        db.close()
    try:
        dbt.run(shutdown)
    except Exception:  # noqa: BLE001 — 更新後重新開啟時帳本已經關閉
        pass
    dbt.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
