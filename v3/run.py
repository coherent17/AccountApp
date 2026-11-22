"""v3 試作版進入點：pywebview（Windows 內建的 Edge WebView2）視窗 + HTML 畫面 + v2 的帳務程式。

試作版不會碰真正的帳本：沒有指定 MY_LEDGER_DATA_DIR 時，在暫存資料夾建立一本範例帳本。
"""

from __future__ import annotations

import os
import sys
import tempfile

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)

import webview  # noqa: E402

from app.database import Database  # noqa: E402
from app.sample_data import load_sample_data  # noqa: E402
from v3.api import Api, DbThread  # noqa: E402
from v3.paths import data_dir  # noqa: E402

UI = os.path.join(HERE, "v3", "ui", "index.html")


def open_ledger() -> tuple[Database, bool]:
    if os.environ.get("MY_LEDGER_DATA_DIR"):
        return Database(os.path.join(data_dir(), "理財帳本.db")), False
    folder = tempfile.mkdtemp(prefix="myledger_v3_demo_")
    db = Database(os.path.join(folder, "理財帳本.db"))
    db.set_setting("owner_name", "游媽媽")
    load_sample_data(db)
    return db, True


def main() -> None:
    dbt = DbThread()
    db, demo = dbt.run(open_ledger)
    api = Api(dbt, db, demo)
    win = webview.create_window("我的理財帳本（v3 試作）", UI, js_api=api, width=1440, height=900,
                                min_size=(1100, 700), background_color="#F4F6FA")
    shot = os.environ.get("MY_LEDGER_V3_SHOT")
    webview.start(_shots, (win, shot), http_server=True, debug=False) if shot else \
        webview.start(http_server=True, debug=False)
    dbt.run(db.close)
    dbt.close()


def _shots(win, out: str) -> None:
    """自動截圖（開發用，需要 Pillow）：淺色／深色 × 大／特大字型，各截一張後關閉。"""
    import time
    from PIL import ImageGrab
    os.makedirs(out, exist_ok=True)
    time.sleep(5)
    errs = win.evaluate_js("JSON.stringify(window.__errors)")
    if errs and errs != "[]":
        print("JS errors:", errs, flush=True)
    for theme in ("light", "dark"):
        for scale in ("large", "xlarge"):
            win.evaluate_js(f"window.__setPrefs('{theme}', '{scale}')")
            time.sleep(2.5)
            x, y, w, h = win.x, win.y, win.width, win.height
            ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(
                os.path.join(out, f"v3_dashboard_{theme}_{scale}.png"))
            if scale == "large":        # 下半頁：圖表、預算與最近的紀錄
                win.evaluate_js("document.querySelector('.main').scrollTop = 780")
                time.sleep(1.5)
                ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(
                    os.path.join(out, f"v3_dashboard_{theme}_{scale}_middle.png"))
                win.evaluate_js("document.querySelector('.main').scrollTop = 99999")
                time.sleep(1.5)
                ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(
                    os.path.join(out, f"v3_dashboard_{theme}_{scale}_lower.png"))
                win.evaluate_js("document.querySelector('.main').scrollTop = 0")
    win.destroy()


if __name__ == "__main__":
    main()
