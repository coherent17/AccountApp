"""開發用：自動操作 v3 畫面並截圖（需要 Pillow，不打包進 exe）。

MY_LEDGER_V3_SHOT=<資料夾> 啟動時執行；MY_LEDGER_V3_SCENES=名稱前綴,… 只跑部分場景。
每個場景先執行一段 JS（透過 window.__t 的測試掛鉤操作畫面），再截下視窗；JS 錯誤會印出來並寫進 errors.txt。
"""

from __future__ import annotations

import json
import os
import time

ESC = "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))"

# (名稱, 截圖前執行的 JS, 等待秒數)
SCENES = [
    ("dashboard", "__t.go('dashboard')", 3),
    ("dashboard_lower", "document.querySelector('.main').scrollTop = 99999", 1.5),
    ("transactions", "document.querySelector('.main').scrollTop = 0; __t.go('transactions')", 2.5),
    ("transactions_year", "__t.filter({period: '今年'})", 2),
    ("txn_new_expense", "__t.openTxn({type: 'expense'})", 1.5),
    ("txn_new_transfer", ESC + "; __t.openTxn({type: 'transfer'})", 1.5),
    ("txn_edit", ESC + "; __t.editFirst()", 2),
    ("txn_menu", ESC + "; __t.menuFirst()", 1.2),
    ("voucher_journal", ESC + "; __t.openFirstOf('journal')", 2),
    ("void_dialog", ESC + "; __t.askVoid()", 1.2),
    ("audit", ESC + "; __t.openAudit()", 2),
    ("txn_dark", ESC + "; __t.prefs('dark', 'large'); __t.go('transactions')", 2),
    ("txn_dialog_dark", "__t.openTxn({type: 'income'})", 1.5),
    ("txn_xlarge", ESC + "; __t.prefs('light', 'xlarge')", 2),
    ("txn_dialog_xlarge", "__t.openTxn({type: 'expense'})", 1.5),
    ("accounts", ESC + "; __t.prefs('light', 'large'); __t.go('accounts')", 2.5),
    ("accounts_lower", "document.querySelector('.main').scrollTop = 99999", 1.2),
    ("account_dialog", "document.querySelector('.main').scrollTop = 0; __t.openAccount(1)", 1.5),
    ("adjust_dialog", ESC + "; __t.openAdjust(9)", 1.5),
    ("invest", ESC + "; __t.go('investments')", 3),
    ("invest_events", "__t.tab('交易紀錄')", 2),
    ("invest_realized", "__t.tab('已實現損益')", 2),
    ("invest_perf", "__t.tab('報酬分析')", 2.5),
    ("trade_sell", "__t.openTrade('sell', 1)", 2),
    ("trade_div", ESC + "; __t.openTrade('cash_div', 3)", 2),
    ("price_dialog", ESC + "; __t.openPrices()", 2),
    ("security_list", ESC + "; __t.openSecurityList()", 2),
    ("security_dialog", "__t.openSecurity(1)", 1.5),
    ("rates", ESC + "; " + ESC + "; __t.openRates()", 1.5),
    ("invest_dark", ESC + "; __t.prefs('dark', 'large'); __t.tab('持股明細')", 2.5),
    ("accounts_xlarge", "__t.prefs('light', 'xlarge'); __t.go('accounts')", 2.5),
    ("dashboard_dark", ESC + "; __t.prefs('dark', 'large'); __t.go('dashboard')", 3),
    ("min_window", ESC + "; __t.prefs('light', 'xlarge'); __t.go('transactions')", 1),
]


def run(win, out: str) -> None:
    from PIL import ImageGrab
    os.makedirs(out, exist_ok=True)
    only = [s for s in os.environ.get("MY_LEDGER_V3_SCENES", "").split(",") if s]
    time.sleep(5)
    errors = []
    for name, js, wait in SCENES:
        if only and not any(name.startswith(o) for o in only):
            continue
        if name == "min_window":
            win.resize(1100, 700)
        try:
            win.evaluate_js(js)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
        time.sleep(wait)
        errs = json.loads(win.evaluate_js("JSON.stringify(window.__errors.splice(0))") or "[]")
        errors += [f"{name}: {e}" for e in errs]
        x, y, w, h = win.x, win.y, win.width, win.height
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(os.path.join(out, f"v3_{name}.png"))
    with open(os.path.join(out, "errors.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(errors))
    print("JS errors:" if errors else "no JS errors", *errors, sep="\n", flush=True)
    win.destroy()
