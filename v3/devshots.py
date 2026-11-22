"""自動操作 v3 畫面並截圖：開發用的場景截圖（run）與 exe 煙霧測試（smoke）。

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
    ("reports_bs", ESC + "; __t.prefs('light', 'large'); __t.go('reports')", 3),
    ("reports_is", "__t.tab('收支損益表')", 2),
    ("reports_cf", "__t.tab('現金流量表')", 2),
    ("reports_monthly", "__t.tab('月度收支')", 2.5),
    ("reports_cats", "__t.tab('分類與預算')", 2.5),
    ("reports_tags", "__t.tab('標籤／專案')", 2),
    ("reports_journal", "__t.tab('日記帳')", 2.5),
    ("reports_ledger", "__t.tab('分類帳')", 2),
    ("reports_tb", "__t.tab('試算表')", 2),
    ("reports_tax", "__t.tab('報稅彙總')", 2),
    ("print_preview", "__t.openPrint('2026-01-01', '2026-12-31')", 1.5),
    ("annual", ESC + "; __t.openAnnual([2026, 2025])", 1.5),
    ("export", ESC + "; __t.openExport('2026-01-01', '2026-12-31')", 1.5),
    ("reports_dark", ESC + "; __t.prefs('dark', 'large'); __t.tab('資產負債表')", 2.5),
    ("settings", ESC + "; __t.prefs('light', 'large'); __t.go('settings')", 2.5),
    ("settings_mid", "document.querySelector('.main').scrollTop = 900", 1.2),
    ("settings_lower", "document.querySelector('.main').scrollTop = 99999", 1.2),
    ("chart", "document.querySelector('.main').scrollTop = 0; __t.openChart()", 2),
    ("subject", ESC + "; __t.openSubject('asset')", 1.5),
    ("year_close", ESC + "; __t.openYearClose(2025)", 2),
    ("settings_dark", ESC + "; __t.prefs('dark', 'large')", 2),
    ("dashboard_dark", ESC + "; __t.prefs('dark', 'large'); __t.go('dashboard')", 3),
    ("min_window", ESC + "; __t.prefs('light', 'xlarge'); __t.go('transactions')", 1),
]


def _grab(win, path: str) -> None:
    from v3.screenshot import grab_window
    grab_window(int(win.native.Handle.ToInt64()), path)


SMOKE_PAGES = ["dashboard", "transactions", "accounts", "investments", "reports", "settings"]


def smoke(win, out: str) -> None:
    """煙霧測試（與 v2 相同的 MY_LEDGER_SMOKE_DIR）：每一頁截圖為 exe_*.png，JS 錯誤寫進 錯誤紀錄.log，然後關閉。"""
    os.makedirs(out, exist_ok=True)
    time.sleep(4)
    errors = []
    for page in SMOKE_PAGES:
        win.evaluate_js(f"__t.go('{page}')")
        time.sleep(2.5)
        errors += json.loads(win.evaluate_js("JSON.stringify(window.__errors.splice(0))") or "[]")
        _grab(win, os.path.join(out, f"exe_{page}.png"))
    if errors:
        folder = win.evaluate_js("window.__folder") or out
        with open(os.path.join(folder, "錯誤紀錄.log"), "a", encoding="utf-8") as f:
            f.write("\n".join(["v3 smoke JS errors:"] + errors) + "\n")
    win.destroy()


def run(win, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    only = [s for s in os.environ.get("MY_LEDGER_V3_SCENES", "").split(",") if s]
    time.sleep(5)
    errors = []
    for name, js, wait in SCENES:
        if only and not any(name.startswith(o) for o in only):
            continue
        if name == "min_window":
            win.resize(1100, 700)
            time.sleep(0.5)
        try:
            win.evaluate_js(js)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
        time.sleep(wait)
        errs = json.loads(win.evaluate_js("JSON.stringify(window.__errors.splice(0))") or "[]")
        errors += [f"{name}: {e}" for e in errs]
        _grab(win, os.path.join(out, f"v3_{name}.png"))
    with open(os.path.join(out, "errors.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(errors))
    print("JS errors:" if errors else "no JS errors", *errors, sep="\n", flush=True)
    win.destroy()
