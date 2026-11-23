"""自動操作 v3 畫面並截圖：開發用的場景截圖（run）與 exe 煙霧測試（smoke）。

MY_LEDGER_V3_SHOT=<資料夾> 啟動時執行；MY_LEDGER_V3_SCENES=名稱前綴,… 只跑部分場景。
每個場景先執行一段 JS（透過 window.__t 的測試掛鉤操作畫面），再截下視窗；JS 錯誤會印出來並寫進 errors.txt。
"""

from __future__ import annotations

import json
import os
import time

ESC = "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))"

# 她的螢幕（約 1280×720）：每一頁量測看得到的列數，再截圖（MY_LEDGER_V3_SCENES=mom）
MOM = []
for scale in ("normal", "large"):
    MOM += [
        (f"mom_{scale}_transactions", f"__t.prefs('light', '{scale}'); __t.go('transactions')", 2.5),
        (f"mom_{scale}_invest_hold", "__t.go('investments')", 2.5),
        (f"mom_{scale}_invest_events", "__t.tab('交易紀錄')", 2),
        (f"mom_{scale}_reports_bs", "__t.go('reports')", 2.5),
        (f"mom_{scale}_reports_is", "__t.tab('收支損益表')", 2),
        (f"mom_{scale}_reports_journal", "__t.tab('日記帳')", 2),
        (f"mom_{scale}_journal_combo", "__t.openJournal()", 1.5),
        (f"mom_{scale}_journal_combo_open", "document.querySelector('.combo input').focus()", 1),
        (f"mom_{scale}_close", ESC + "; " + ESC, 0.5),
    ]

# README 用的截圖（MY_LEDGER_V3_SCENES=readme）：淺色、大字，範例帳本
README = [
    ("readme_dashboard", "__t.prefs('light', 'large'); __t.go('dashboard')", 3.5),
    ("readme_insights", "document.querySelector('.main').scrollTop = 640", 2),
    ("readme_transactions", "document.querySelector('.main').scrollTop = 0; __t.go('transactions')", 2.5),
    ("readme_txn_dialog", "__t.openTxn({type: 'expense'})", 1.8),
    ("readme_journal", ESC + "; __t.openUserJournal()", 2.5),
    ("readme_investments", ESC + "; __t.go('investments')", 3),
    ("readme_reports", "__t.go('reports')", 3),
    ("readme_annual", "__t.openAnnual([2026, 2025])", 1.5),
    ("readme_dark", ESC + "; __t.prefs('dark', 'large'); __t.go('dashboard')", 3.5),
    ("readme_tour", "__t.prefs('light', 'large'); __t.openTour()", 1.5),
]

# (名稱, 截圖前執行的 JS, 等待秒數)
SCENES = [
    ("dashboard", "__t.go('dashboard')", 3),
    ("dashboard_hover", "document.querySelectorAll('.stat')[2].dispatchEvent(new MouseEvent('mouseover', {bubbles: true}))", 1),
    ("dashboard_xlarge", "__t.prefs('light', 'xlarge')", 2.5),
    ("dashboard_dark2", "__t.prefs('dark', 'large')", 2.5),
    ("dashboard_mid", "document.querySelector('.main').scrollTop = 620", 1.5),
    ("tour1", "document.querySelector('.main').scrollTop = 0; __t.openTour()", 1.2),
    ("tour3", "document.querySelectorAll('.tour .btn.primary')[0].click(); document.querySelectorAll('.tour .btn.primary')[0].click()", 1.2),
    ("whatsnew", ESC + "; window.__fakeWhatsNew()", 1.2),
    ("update_pill", ESC + "; window.__fakeUpdate('3.3.0')", 1),
    ("dashboard_lower", "__t.prefs('light', 'large');" +  "document.querySelector('.main').scrollTop = 99999", 1.5),
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
    ("journal_new", ESC + "; __t.prefs('light', 'large'); __t.openJournal()", 2),
    ("journal_template", "__t.journalTemplate('買進股票（借 短期投資／貸 銀行存款）')", 1.5),
    ("journal_user", ESC + "; __t.openUserJournal()", 2.5),
    ("journal_system", ESC + "; __t.openFirstOf('journal')", 2.5),
    ("journal_xlarge", ESC + "; __t.prefs('light', 'xlarge'); __t.openUserJournal()", 2.5),
    ("txn_split", ESC + "; __t.prefs('light', 'large'); __t.openTxn({type: 'expense'})", 1.5),
    ("recurring", ESC + "; __t.prefs('light', 'large'); __t.openRecurring()", 2),
    ("recurring_edit", "document.querySelector('.dialog tbody tr').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))", 2),
    ("reconcile", ESC + "; " + ESC + "; __t.openReconcile(2)", 2),
    ("import", ESC + "; __t.openImport()", 1.5),
    ("search", ESC + "; __t.openSearch()", 1),
    ("search_results", "(() => { const i = document.querySelector('.big-search input'); i.value = '午餐'; i.dispatchEvent(new Event('input', {bubbles: true})); })()", 2),
    ("welcome", ESC + "; __t.openWelcome()", 1.5),
    ("dashboard_dark", ESC + "; __t.prefs('dark', 'large'); __t.go('dashboard')", 3),
    ("min_window", ESC + "; __t.prefs('light', 'xlarge'); __t.go('transactions')", 1),
    ("min_window_dashboard", "__t.prefs('light', 'large'); __t.go('dashboard')", 3),
]


def _grab(win, path: str) -> None:
    from v3.screenshot import grab_window
    grab_window(int(win.native.Handle.ToInt64()), path)


SMOKE_PAGES = ["dashboard", "transactions", "accounts", "investments", "reports", "settings"]


READY_JS = ("!document.getElementById('splash') && !document.querySelector('.skeleton')"
            " && !!document.querySelector('.page > .pagefx > *, .page .head')")


def wait_ready(win, timeout: float = 20) -> bool:
    """等畫面真的畫好（啟動畫面消失、沒有載入中的骨架），而不是固定等幾秒。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if win.evaluate_js(READY_JS):
                time.sleep(0.35)        # 圖表動畫的第一格
                return True
        except Exception:  # noqa: BLE001 — 畫面還沒載入完成
            pass
        time.sleep(0.15)
    return False


def smoke(win, out: str) -> None:
    """煙霧測試（與 v2 相同的 MY_LEDGER_SMOKE_DIR）：每一頁畫好後截圖為 exe_*.png，然後關閉。
    畫面程式的錯誤會自動寫進資料夾的「錯誤紀錄.log」；某一頁一直沒畫好也會記錄下來。"""
    os.makedirs(out, exist_ok=True)
    wait_ready(win, 30)
    for page in SMOKE_PAGES:
        win.evaluate_js(f"__t.go('{page}')")
        time.sleep(0.2)
        if not wait_ready(win):
            win.evaluate_js(f"window.pywebview.api.log_js_error('smoke: {page} 頁 20 秒內沒有畫好')")
        _grab(win, os.path.join(out, f"exe_{page}.png"))
    win.destroy()


def run(win, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    only = [s for s in os.environ.get("MY_LEDGER_V3_SCENES", "").split(",") if s]
    time.sleep(5)
    errors = []
    scenes = README if only == ["readme"] else MOM if only == ["mom"] else SCENES
    if only == ["mom"]:
        win.resize(1280, 720)
        time.sleep(1)
    for name, js, wait in scenes:
        if only and only not in (["readme"], ["mom"]) and not any(name.startswith(o) for o in only):
            continue
        if name == "min_window":
            win.resize(1100, 700)
            time.sleep(0.5)
        try:
            win.evaluate_js(js)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
        time.sleep(wait)
        if name.startswith("mom_") and not name.endswith(("_close", "_combo_open")):
            print(f"{name}: {win.evaluate_js('window.__t.visibleRows()')}", flush=True)
        if name.endswith("_combo_open"):
            print(f"{name}: 下拉選單顯示 {win.evaluate_js("[...document.querySelectorAll('.pop.floating > div')].filter(d => {const r=d.getBoundingClientRect(); const p=d.closest('.pop').getBoundingClientRect(); return r.top>=p.top-1 && r.bottom<=Math.min(p.bottom, innerHeight)+1}).length")} 個項目", flush=True)
        errs = json.loads(win.evaluate_js("JSON.stringify(window.__errors.splice(0))") or "[]")
        errors += [f"{name}: {e}" for e in errs]
        _grab(win, os.path.join(out, f"v3_{name}.png"))
    with open(os.path.join(out, "errors.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(errors))
    print("JS errors:" if errors else "no JS errors", *errors, sep="\n", flush=True)
    win.destroy()


def closing(win, out: str) -> None:
    """測試結束畫面：開啟後像按 ✕ 一樣關閉，擷取「正在儲存」與「已安全儲存」兩個畫面。"""
    import threading
    os.makedirs(out, exist_ok=True)
    time.sleep(4)
    _grab(win, os.path.join(out, "before_close.png"))
    threading.Thread(target=win.destroy, daemon=True).start()     # 與按視窗的 ✕ 相同：觸發結束畫面
    time.sleep(0.35)
    try:
        _grab(win, os.path.join(out, "farewell_saving.png"))
        time.sleep(0.9)
        _grab(win, os.path.join(out, "farewell_done.png"))
    except Exception as e:  # noqa: BLE001
        print("grab failed:", e, flush=True)
