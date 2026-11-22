"""v3 進入點：pywebview（Windows 內建的 Edge WebView2）視窗 + HTML 畫面 + v2 的帳務程式。

測試版不會碰真正的帳本：沒有指定 MY_LEDGER_DATA_DIR 時，在暫存資料夾建立一本範例帳本。
"""

from __future__ import annotations

import os
import sys
import tempfile

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)

from app.database import Database  # noqa: E402
from app.sample_data import load_sample_data  # noqa: E402
from v3.api import Api, DbThread  # noqa: E402
from v3.paths import data_dir  # noqa: E402

UI = os.path.join(HERE, "v3", "ui", "index.html")


def open_ledger() -> tuple[Database, str, bool]:
    if os.environ.get("MY_LEDGER_DATA_DIR"):
        folder = data_dir()
        return Database(os.path.join(folder, "理財帳本.db")), folder, False
    folder = tempfile.mkdtemp(prefix="myledger_v3_demo_")
    db = Database(os.path.join(folder, "理財帳本.db"))
    db.set_setting("owner_name", "游媽媽")
    load_sample_data(db)
    db.clear_undo()
    return db, folder, True


def main() -> int:
    from v3 import webview2
    if not webview2.ensure():
        return 1
    import webview
    dbt = DbThread()
    db, folder, demo = dbt.run(open_ledger)
    api = Api(dbt, db, folder, demo)
    win = webview.create_window("我的理財帳本（v3 測試版）", UI, js_api=api, width=1440, height=900,
                                min_size=(1100, 700), background_color="#F3F5F9")
    api._window = win
    shot = os.environ.get("MY_LEDGER_V3_SHOT")
    if shot:
        from v3 import devshots
        webview.start(devshots.run, (win, shot), http_server=True, gui="edgechromium", debug=False)
    else:
        webview.start(http_server=True, gui="edgechromium", debug=False)
    dbt.run(db.close)
    dbt.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
