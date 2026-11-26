"""自動操作畫面並截圖：開發用的場景截圖（run）與 exe 煙霧測試（smoke）。

MY_LEDGER_SHOT=<資料夾> 啟動時執行；MY_LEDGER_SCENES=名稱前綴,… 只跑部分場景。
每個場景先執行一段 JS（透過 window.__t 的測試掛鉤操作畫面），再截下視窗；JS 錯誤會印出來並寫進 errors.txt。
"""

from __future__ import annotations

import json
import os
import time

ESC = "window.dispatchEvent(new MouseEvent('mousedown')); __t.closeTop()"          # 關選單與最上面的對話框（不詢問）
REAL_ESC = "window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))"   # 真的按 Esc（會詢問尚未儲存的內容）

# 她的螢幕（約 1280×720）：每一頁量測看得到的列數，再截圖（MY_LEDGER_SCENES=mom）
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
        (f"mom_{scale}_journal_combo_open", "const i = document.querySelector('.combo input'); i.focus(); i.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))", 1),
        (f"mom_{scale}_journal_up_combo_open", "document.body.click(); const i = document.querySelectorAll('.combo input')[2]; i.focus(); i.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))", 1),
        (f"mom_{scale}_close", ESC + "; " + ESC, 0.5),
    ]

# 每一頁、每個分頁與有清單的對話框，在她的螢幕（1280×720）量測看得到的列數（MY_LEDGER_SCENES=audit）
_SEARCH = ("const i = document.querySelector('.dialog input'); i.value = '2026';"
           "i.dispatchEvent(new Event('input', {bubbles: true}))")
AUDIT = []
for scale in ("normal", "large"):
    s = f"audit_{scale}_"
    AUDIT += [(s + "dashboard", f"__t.prefs('light', '{scale}'); __t.go('dashboard')", 3),
              (s + "transactions", "__t.go('transactions')", 2.5),
              (s + "accounts", "__t.go('accounts')", 2.5)]
    AUDIT += [(s + "invest_" + k, "__t.go('investments')" if i == 0 else f"__t.tab('{t}')", 2.5)
              for i, (k, t) in enumerate([("hold", "持股明細"), ("events", "交易紀錄"), ("realized", "已實現損益"), ("perf", "報酬分析")])]
    AUDIT += [(s + "reports_" + k, "__t.go('reports')" if i == 0 else f"__t.tab('{t}')", 2.5)
              for i, (k, t) in enumerate([("bs", "資產負債表"), ("is", "收支損益表"), ("cf", "現金流量表"), ("monthly", "月度收支"),
                                          ("cats", "分類與預算"), ("tags", "標籤／專案"), ("journal", "日記帳"), ("ledger", "分類帳"),
                                          ("tb", "試算表"), ("tax", "報稅彙總")])]
    AUDIT += [(s + "settings", "__t.go('settings')", 2.5),
              (s + "settings_cats", "__t.tab('收支分類')", 1.5), (s + "settings_close", "__t.tab('結帳')", 1.5),
              (s + "settings_data", "__t.tab('資料管理與備份')", 1.5), (s + "settings_net", "__t.tab('網路與更新')", 1.5),
              (s + "dashboard_mid", "__t.go('dashboard'); setTimeout(() => { document.querySelector('.main').scrollTop = 430; }, 1500)", 3),
              (s + "dashboard_end", "document.querySelector('.main').scrollTop = 9999", 1.5),
              (s + "mini_dashboard", "__t.side(true); __t.go('dashboard')", 2.5), (s + "mini_accounts", "__t.go('accounts')", 2.5),
              (s + "mini_tb", "window.__pendingReport = {tab: 'tb'}; __t.go('reports')", 2.5), (s + "mini_transactions", "__t.go('transactions'); ", 2.5),
              (s + "full_again", "__t.side(false)", 1),
              (s + "settings_back", "__t.go('settings')", 2),
              (s + "dlg_chart", "__t.openChart()", 2),
              (s + "dlg_recurring", ESC + "; __t.openRecurring()", 2),
              (s + "dlg_due", ESC + "; __t.openDue()", 2),
              (s + "dlg_reconcile", ESC + "; __t.openReconcile()", 2),
              (s + "dlg_search", ESC + "; __t.openSearch()", 1),
              (s + "dlg_search_results", _SEARCH, 2),
              (s + "dlg_audit", ESC + "; __t.openAudit()", 2),
              (s + "dlg_securities", ESC + "; __t.openSecurityList()", 2),
              (s + "dlg_prices", ESC + "; __t.openPrices()", 2),
              (s + "ledger_expense", ESC + "; window.__pendingReport = {tab: 'ledger'}; __t.go('reports')", 2.5),
              (s + "ledger_combo", "const li = document.querySelector('.ledger-pick input'); li.focus();"
               " li.value = '51'; li.dispatchEvent(new Event('input', {bubbles: true}))", 1),
              (s + "ledger_picked", "document.querySelector('.pop.floating > div').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))", 2),
              (s + "dlg_journal", ESC + "; __t.openUserJournal()", 2),
              (s + "dlg_voucher", ESC + "; __t.openFirstOf('journal')", 2),
              (s + "close", ESC + "; " + ESC + "; " + ESC, 0.5)]

def _bank_csv(win, out: str) -> None:
    """智慧對帳截圖用：把對帳視窗最後 6 筆寫成銀行明細（另加一筆帳上沒有的手續費），並讓「選擇檔案」直接傳回它。"""
    rows = json.loads(win.evaluate_js(
        "JSON.stringify([...document.querySelectorAll('table.recon tbody tr')].slice(-6)"
        ".map(tr => [...tr.cells].map(c => c.textContent.trim())))") or "[]")
    path = os.path.join(out, "bank_demo.csv")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("交易日期,摘要,提出,存入,餘額\n")
        for r in rows:
            f.write(f'{r[1]},{r[3]},"{r[5]}","{r[4]}",\n')
        if rows:
            f.write(f"{rows[-1][1]},跨行手續費,15,,\n")
    win.evaluate_js("window.pywebview.api.pick_files = async () => [%s]" % json.dumps(path))


# 3.5 新功能（MY_LEDGER_SCENES=features）：在她的螢幕（1280×720）以標準與大字體截圖
_BTN = "[...document.querySelectorAll('.dialog .btn')].find(b => b.textContent.includes('{}')).click()"
_PREV = "(() => { const d = new Date(); d.setDate(0); return d.toISOString().slice(0, 7); })()"
FEATURES = []
for scale in ("normal", "large"):
    s = f"feat_{scale}_"
    FEATURES += [(s + "dashboard", f"__t.prefs('light', '{scale}'); __t.go('dashboard')", 3),
                 (s + "calendar", "document.querySelector('.soon').scrollIntoView({block: 'center'})", 1),
                 (s + "txn_quick", "document.querySelector('.main').scrollTop = 0; __t.openTxn({type: 'expense'})", 1.5),
                 (s + "txn_quick_used", "document.querySelector('.qchip').click()", 1),
                 (s + "reminders", ESC + "; __t.openReminders()", 1.5),
                 (s + "reminder_new", _BTN.format("新增提醒"), 1),
                 (s + "health", ESC + "; " + ESC + "; __t.openHealth()", 3),
                 (s + "monthclose", ESC + "; __t.openMonthClose()", 2),
                 (s + "monthly", ESC + f"; __t.previewMonthly({_PREV})", 2.5),
                 (s + "forecast", ESC + "; __t.go('dashboard'); __t.openForecast()", 2.5),
                 (s + "feedback", ESC + "; __t.openFeedback()", 2),
                 (s + "feedback_pasted", "(() => { const c = document.createElement('canvas'); c.width = 400; c.height = 300;"
                  " const g = c.getContext('2d'); g.fillStyle = '#FDE68A'; g.fillRect(0, 0, 400, 300); g.fillStyle = '#92400E';"
                  " g.font = '40px sans-serif'; g.fillText('手機照片（測試）', 40, 160);"
                  " c.toBlob((b) => { const dt = new DataTransfer(); dt.items.add(new File([b], 'photo.png', {type: 'image/png'}));"
                  " document.querySelector('.fb-text').dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})); }); })()", 1.2),
                 (s + "feedback_typed", "document.querySelector('.pillbtn').click(); const t = document.querySelector('.fb-text');"
                  " t.value = '收支明細的字可以再大一點，月結第 2 步不知道要按哪裡。'; t.dispatchEvent(new Event('input', {bubbles: true}))", 1),
                 (s + "feedback_added", _BTN.format("加入清單"), 1.5),
                 (s + "feedback_second", ESC + "; __t.go('transactions'); setTimeout(() => __t.openFeedback(), 1500)", 3.5),
                 (s + "feedback_second_typed", "document.querySelectorAll('.pillbtn')[3].click(); const t = document.querySelector('.fb-text');"
                  " t.value = '希望可以把收支明細匯出成 PDF。'; t.dispatchEvent(new Event('input', {bubbles: true}))", 1),
                 (s + "feedback_done", _BTN.format("產生 PDF"), 4),
                 (s + "reports_head", ESC + "; __t.go('reports')", 2.5),
                 (s + "recon_open", "__t.openReconcile()", 2),
                 (s + "recon_prep", _bank_csv, 0.5),
                 (s + "recon_smart", _BTN.format("匯入銀行明細"), 2),
                 (s + "recon_close", ESC, 0.5),
                 (s + "close", ESC + "; " + ESC, 0.5)]

# 3.8：報表點選查分類帳、分錄帶入／複製／定期、年度結帳、貼上價格（MY_LEDGER_SCENES=flow）
_CLICK = "[...document.querySelectorAll('{}')].find(b => b.textContent.includes('{}')).click()"
_SETNOTE = ("(() => {{ const i = [...document.querySelectorAll('.dialog.journal .jtop .field.wide input')][0]; i.focus(); i.value = '{}';"
            " i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()")
_MKJ = ("(async () => {{ const f = await pywebview.api.journal_form(null); const k = (n) => f.chart.find(c => c.name === n).key;"
        " for (const m of [9, 10]) await pywebview.api.journal_save({{date: `2026-${{String(m).padStart(2, '0')}}-10`, note: `房貸繳款 ${{m}} 月`, tags: [],"
        " lines: [{{key: k('房貸利息'), debit: 3200}}, {{key: k('房租房貸'), debit: 12800}}, {{key: k('台銀活存'), credit: 16000}}]}}); }})()").replace("{{", "{").replace("}}", "}")
XL = [("xl_" + p, f"__t.prefs('light', 'xlarge'); __t.go('{p}')", 2.5) for p in ("dashboard", "transactions", "accounts", "investments", "reports", "settings")]
XL += [("xl_dark_dashboard", "__t.prefs('dark', 'normal'); __t.go('dashboard')", 2.5), ("xl_dark_reports", "__t.go('reports')", 2.5), ("xl_dark_tx", "__t.go('transactions')", 2.5),
       ("xl_dark_txn", "__t.openTxn({type: 'expense'})", 2), ("xl_dark_settings", ESC + "; __t.go('settings')", 2)]
FLOW = []
for scale in ("normal", "large"):
    s = f"flow_{scale}_"
    FLOW += [(s + "seed", f"__t.prefs('light', '{scale}'); " + _MKJ, 2),
             (s + "tb", "__t.go('dashboard'); setTimeout(() => { window.__pendingReport = {tab: 'tb'}; __t.go('reports'); }, 300)", 3),
             (s + "tb_scrolled", "document.querySelector('.page-fill .tablewrap').scrollTop = 200", 0.5),
             (s + "tb_drill", "[...document.querySelectorAll('a.drill')].find(x => x.textContent.includes('餐飲')).click()", 2),
             (s + "tb_back", _CLICK.format(".page-fill .btn", "回到試算表"), 2),
             (s + "bs_drill", "__t.tab('資產負債表'); setTimeout(() => [...document.querySelectorAll('tr.drill')].find(x => x.textContent.includes('1102')).click(), 1500)", 3.5),
             (s + "is_drill", "__t.tab('收支損益表'); setTimeout(() => [...document.querySelectorAll('tr.drill')].find(x => x.textContent.includes('證券買賣')).click(), 1500)", 3.5),
             (s + "journal_new", "__t.openJournal()", 2),
             (s + "journal_hint", _SETNOTE.format("房貸繳款 11 月"), 1),
             (s + "journal_reused", _CLICK.format(".jq .qchip", "帶入"), 1.5),
             (s + "journal_recurring", _CLICK.format(".dialog .btn", "設為定期"), 2),
             (s + "journal_recurring2", "1", 1.5),
             (s + "recurring_saved", "[...document.querySelectorAll('.dialog')].pop().querySelector('.btn.primary').click()", 1.5),
             (s + "recurring_list", ESC + "; " + ESC + "; __t.openRecurring()", 2),
             (s + "due", ESC + "; pywebview.api.recurring_list().then(d => { const r = d.rows.find(x => x.type === 'journal'); __t.openDue([{rec_id: r.id,"
              " date: '2026-11-10', name: r.name, type: 'journal', type_label: '分錄', amount: r.amount}]); })", 2),
             (s + "due_edit", "[...document.querySelectorAll('.dialog td .btn')].find(b => b.textContent.includes('修改')).click()", 2),
             (s + "due_posted", "[...document.querySelectorAll('.dialog')].pop().querySelector('.btn.primary').click()", 2),
             (s + "voucher_copy", ESC + "; " + ESC + "; __t.openUserJournal()", 2.5),
             (s + "prices_paste", ESC + "; __t.openPrices()", 1.5),
             (s + "paste_dialog", _CLICK.format(".dialog .btn", "貼上價格"), 1),
             (s + "paste_result", "(() => { const t = [...document.querySelectorAll('.fb-text')].pop(); t.value = '50\\t111.5\\n2330\\t3,900\\n1234\\t2330\\n56\\t--';"
              " t.dispatchEvent(new Event('input', {bubbles: true})); })()", 1.5),
             (s + "paste_result2", "1", 1.5),
             (s + "paste_filled", "[...document.querySelectorAll('.dialog')].pop().querySelector('.btn.primary').click()", 1),
             (s + "year", ESC + "; " + ESC + "; __t.openYearAssist()", 2),
             (s + "year_this", ESC + "; __t.openYearAssist(new Date().getFullYear())", 2),
             (s + "close", ESC + "; " + ESC + "; " + ESC, 0.5)]

# 3.9：尚未儲存的內容不會因為 Esc、點外面、✕、取消、關視窗而不見；沒改過的表單不會多問（MY_LEDGER_SCENES=guard）
_TITLES = "[...document.querySelectorAll('.dialog h2')].map(x => x.textContent).join(' > ')"
_TYPE = "(() => {{ const i = [...document.querySelectorAll('.dialog')].pop().querySelector('{}'); i.focus(); i.value = '{}'; i.dispatchEvent(new Event('input', {{bubbles: true}})); }})()"
_TOPBTN = "[...[...document.querySelectorAll('.dialog')].pop().querySelectorAll('.dfoot .btn')].find(b => b.textContent.includes('{}')).click()"
_OUTSIDE = ("(() => { const o = [...document.querySelectorAll('.overlay')].pop(); for (const t of ['mousedown', 'mouseup']) o.dispatchEvent(new MouseEvent(t, {bubbles: true})); })()")
_XBTN = "[...document.querySelectorAll('.dialog')].pop().querySelector('.dhead .x').click()"
_TOUCH = "[...document.querySelectorAll('.dialog')].pop().querySelector('.dbody').dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))"
_JN = ".jtop .field.wide input"
GUARD_STEPS = [     # (說明, 動作, 等幾秒, 之後對話框應該是)
    ("沒輸入：Esc 直接關", "__t.openJournal()", 1.5, "複式分錄（傳票）"), ("", REAL_ESC, .6, ""),
    ("開啟分錄", "__t.openJournal()", 1.5, "複式分錄（傳票）"), ("打摘要", _TYPE.format(_JN, "還沒存的分錄"), .6, "複式分錄（傳票）"),
    ("下拉開著按 Esc：只收清單", "[...document.querySelectorAll('.jtable .combo input')][0].focus()", .6, "複式分錄（傳票）"), ("", REAL_ESC, .6, "複式分錄（傳票）"),
    ("Esc 先問", REAL_ESC, .6, "複式分錄（傳票） > 尚未儲存"), ("再按 Esc：回到編輯", REAL_ESC, .6, "複式分錄（傳票）"),
    ("點外面先問", _OUTSIDE, .6, "複式分錄（傳票） > 尚未儲存"), ("繼續編輯", _TOPBTN.format("繼續編輯"), .6, "複式分錄（傳票）"),
    ("✕ 先問", _XBTN, .6, "複式分錄（傳票） > 尚未儲存"), ("繼續編輯", _TOPBTN.format("繼續編輯"), .6, "複式分錄（傳票）"),
    ("取消先問", _TOPBTN.format("取消"), .6, "複式分錄（傳票） > 尚未儲存"), ("放棄", _TOPBTN.format("放棄"), .6, ""),
    ("記一筆：打金額後 Esc 先問", "__t.openTxn({type: 'expense'})", 1.5, "記一筆"), ("", _TYPE.format(".amount input", "120"), .5, "記一筆"), ("", REAL_ESC, .6, "記一筆 > 尚未儲存"),
    ("放棄", _TOPBTN.format("放棄"), .6, ""),
    ("改回原樣不用問", "__t.openTxn({type: 'expense'})", 1.5, "記一筆"), ("", _TYPE.format(".amount input", "120"), .5, "記一筆"), ("", _TYPE.format(".amount input", ""), .5, "記一筆"), ("", REAL_ESC, .6, ""),
    ("帳戶：打名稱後 ✕ 先問", "__t.openAccount()", 1.5, "新增帳戶"), ("", _TYPE.format("input", "測試"), .5, "新增帳戶"), ("", _XBTN, .6, "新增帳戶 > 尚未儲存"), ("放棄", _TOPBTN.format("放棄"), .6, ""),
]
for _n, _open, _t in [("編輯帳戶", "__t.openAccount(1)", "編輯帳戶"), ("買進", "__t.openTrade('buy')", "買進"), ("市價評價", "__t.openPrices()", "市價評價"), ("匯率", "__t.openRates()", "更新匯率"),
                      ("銀行對帳", "__t.openReconcile()", "銀行對帳"), ("標的", "__t.openSecurity(1)", "編輯投資標的"), ("更新餘額", "__t.openAdjust()", "更新餘額／市值"),
                      ("定期", "__t.openRecurringEdit(null)", "新增定期交易"), ("科目", "__t.openSubject('expense')", "新增會計科目")]:
    GUARD_STEPS += [(f"{_n}：點一下、沒改內容，Esc 直接關", _open, 1.8, _t), ("", _TOUCH, .4, _t), ("", REAL_ESC, .6, "")]


def _guard_check(win, out: str) -> None:
    bad = 0
    for label, js, wait, want in GUARD_STEPS:
        win.evaluate_js(js)
        time.sleep(wait)
        got = win.evaluate_js(_TITLES) or ""
        ok = got == want
        bad += not ok
        print(("OK  " if ok else "BAD ") + (label or "　〃") + ("" if ok else f"：預期「{want}」，實際「{got}」"), flush=True)
        if label == "Esc 先問":
            _grab(win, os.path.join(out, "guard_ask.png"))
        if not ok:
            for _ in range(4):
                win.evaluate_js(ESC)
    # 股數不顯示多餘的小數
    win.evaluate_js("__t.openUserJournal()")
    time.sleep(2)
    v = win.evaluate_js("[...document.querySelectorAll('.jtable input[placeholder=\"股數\"]')].map(i => i.value + '|' + (i.scrollWidth <= i.clientWidth)).join(' ')")
    print("股數欄：", v, flush=True)
    win.evaluate_js(ESC)
    # 側邊欄與設定頁的字體大小同步
    win.evaluate_js("__t.go('settings')")
    time.sleep(1.5)
    sync = "[...document.querySelectorAll('.seg')].map(s => [...s.querySelectorAll('.on')].map(b => b.textContent).join('')).join(',')"
    for lab in ("特大", "標準", "大"):
        win.evaluate_js(f"[...document.querySelectorAll('.side .seg button')].find(b => b.textContent === '{lab}').click()")
        time.sleep(.6)
        print("字體同步", lab, "→", win.evaluate_js(sync), flush=True)
    win.evaluate_js("[...document.querySelectorAll('.main .seg button')].find(b => b.textContent === '標準').click()")
    time.sleep(.6)
    print("設定頁改標準 →", win.evaluate_js(sync), flush=True)
    win.evaluate_js("[...document.querySelectorAll('.main .seg button')].find(b => b.textContent.includes('Windows')).click()")
    time.sleep(.6)
    win.evaluate_js("[...document.querySelectorAll('.side .seg button')].find(b => b.textContent === '大').click()")
    time.sleep(.6)
    print("跟隨 Windows 後換字體，外觀設定仍是 →", win.evaluate_js("[...document.querySelectorAll('.main .seg')].pop().querySelector('.on').textContent"), flush=True)
    print("GUARD", "ALL PASSED" if not bad else f"{bad} FAILED", flush=True)


# 3.10：每一個操作導覽都走一遍：目標都找得到、打亮的框與說明卡都在畫面內、說明卡不蓋住打亮的地方（MY_LEDGER_SCENES=guide）
def _guide_check(win, out: str) -> None:
    bad, total = 0, 0
    ids = json.loads(win.evaluate_js("JSON.stringify(Object.keys(__t.guides()))"))
    # 打到一半的分錄：F1 看這個視窗的導覽，按 Enter、Esc、↑ 都不會動到分錄；看完內容還在
    key = "window.dispatchEvent(new KeyboardEvent('keydown', {{key: '{}', bubbles: true, cancelable: true}}))"
    val = f"(document.querySelector('.dialog.journal {_JN}') || {{}}).value"
    where = "[window.__guideOpen || '', window.__guideStep ? window.__guideStep.i : '', document.querySelectorAll('.dialog').length].join('|')"
    win.evaluate_js("__t.openJournal()")
    time.sleep(1.5)
    win.evaluate_js(_TYPE.format(_JN, "還沒存的分錄"))
    time.sleep(0.5)
    win.evaluate_js(key.format("F1"))
    time.sleep(2)
    for k, want in (("", "journal|"), ("Enter", "journal|"), ("ArrowLeft", "journal|"), ("Escape", "||1")):
        if k:
            win.evaluate_js(key.format(k))
            time.sleep(1.3)
        got = win.evaluate_js(where)
        ok = (got.startswith(want) and got.endswith("|1")) and win.evaluate_js(val) == "還沒存的分錄"
        bad += not ok
        print(("OK  " if ok else "BAD ") + f"分錄打到一半看導覽，按 {k or 'F1'} → {got}", flush=True)
    win.evaluate_js(REAL_ESC)
    time.sleep(0.6)
    got = win.evaluate_js(_TITLES)
    print(("OK  " if got.endswith("尚未儲存") else "BAD ") + f"看完再按 Esc 仍會問 → {got}", flush=True)
    bad += not got.endswith("尚未儲存")
    win.evaluate_js(_TOPBTN.format("放棄"))
    time.sleep(0.6)
    win.evaluate_js(key.format("F1"))
    time.sleep(1)
    got = win.evaluate_js(_TITLES)
    print(("OK  " if got == "操作導覽" else "BAD ") + f"沒有視窗時按 F1 → {got}", flush=True)
    bad += got != "操作導覽"
    win.evaluate_js(ESC)
    for scale, mini in (("normal", False), ("large", False), ("normal", True))[:1 if os.environ.get("MY_LEDGER_DATA_DIR") else 3]:
        win.evaluate_js(f"__t.prefs('light', '{scale}'); __t.side({str(mini).lower()}); __t.go('dashboard')")
        time.sleep(1.5)
        for gid in ids:
            win.evaluate_js(f"__t.startGuide('{gid}'); 0")
            prev, shots = None, 0
            for _ in range(20):
                for _ in range(45):          # 等這一步的畫面出來
                    time.sleep(0.15)
                    st = json.loads(win.evaluate_js("JSON.stringify({s: window.__guideStep, open: window.__guideOpen || null, miss: window.__guideMissing || '', w: innerWidth, h: innerHeight,"
                                                    " c: (() => { const c = document.querySelector('.g-card'); if (!c || c.style.visibility === 'hidden') return null; const r = c.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()})"))
                    if not st["open"] or (st["s"] and st["c"] and st["s"]["i"] != prev and (st["s"]["hole"] or st["miss"])):
                        break
                if not st["open"] or not st["s"] or st["s"]["i"] == prev:
                    break
                time.sleep(0.45)             # 移動動畫結束
                st = json.loads(win.evaluate_js("JSON.stringify({s: window.__guideStep, w: innerWidth, h: innerHeight, miss: window.__guideMissing || '', c: (() => { const r = document.querySelector('.g-card').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })()})"))
                s, c, total = st["s"], st["c"], total + 1
                prev, h = s["i"], s["hole"]
                why = []
                if not h:
                    why.append("找不到要打亮的地方")
                else:
                    if h["w"] < 12 or h["h"] < 12 or h["x"] < 0 or h["y"] < 0 or h["x"] + h["w"] > st["w"] + 1 or h["y"] + h["h"] > st["h"] + 1:
                        why.append(f"打亮的框超出畫面 {h}")
                    if s["pos"]["side"] != "none" and c[0] < h["x"] + h["w"] - 1 and c[2] > h["x"] + 1 and c[1] < h["y"] + h["h"] - 1 and c[3] > h["y"] + 1:
                        why.append("說明卡蓋住打亮的地方")
                if c[0] < 0 or c[1] < 0 or c[2] > st["w"] + 1 or c[3] > st["h"] + 1:
                    why.append(f"說明卡超出畫面 {c}")
                if why:
                    bad += 1
                    print(f"BAD {scale}{' mini' if mini else ''} {gid} 第 {s['i'] + 1} 步「{s['title']}」：{'；'.join(why)}", flush=True)
                if scale == "normal" and not mini or why or (shots < 2 and scale == "large"):
                    _grab(win, os.path.join(out, f"guide_{scale}{'_mini' if mini else ''}_{gid}_{s['i'] + 1}.png"))
                    shots += 1
                win.evaluate_js("window.__guideMove(1)")
            left = win.evaluate_js("[window.__guideOpen || '', document.querySelectorAll('.dialog').length].join('|')")
            if prev is None and "請先新增帳戶" in (win.evaluate_js("document.body.innerText") or ""):
                print(f"略過 {gid}：還沒有帳戶，畫面說明「請先新增帳戶」", flush=True)
                win.evaluate_js(ESC)
                continue
            if left != "|0":
                bad += 1
                print(f"BAD {scale} {gid} 結束後還留著：{left}", flush=True)
                win.evaluate_js("window.__guideOpen = null; " + ESC)
            if prev is None:
                bad += 1
                print(f"BAD {scale} {gid} 沒有開始", flush=True)
    seen = json.loads(win.evaluate_js("JSON.stringify(Object.keys(__t.guides()).length)"))
    print(f"導覽 {seen} 個，共走了 {total} 步", flush=True)
    print("GUIDE", "ALL PASSED" if not bad else f"{bad} FAILED", flush=True)
    for name, js, w in [("center", "__t.side(false); __t.prefs('light', 'normal'); __t.go('reports'); setTimeout(() => __t.openGuides(), 1500)", 3),
                        ("center_large", ESC + "; __t.prefs('light', 'large'); __t.openGuides()", 1.5), ("center_dark", "__t.prefs('dark', 'normal')", 1),
                        ("search", ESC + "; __t.prefs('light', 'normal'); __t.openSearch(); setTimeout(() => { const i = document.querySelector('.dialog input'); i.value = '對帳'; i.dispatchEvent(new Event('input', {bubbles: true})); }, 600)", 2.5),
                        ("nudge", ESC + "; __t.resetGuides().then(() => { __t.guidesReady(); })", 1), ("nudge2", "__t.go('transactions')", 3.5), ("nudge_again", "__t.go('accounts'); setTimeout(() => __t.go('transactions'), 500)", 4), ("fresh", "__t.openJournal()", 2),
                        ("settings", ESC + "; __t.go('settings'); setTimeout(() => __t.tab('個人與外觀'), 1200)", 2.5), ("tour", "__t.openTour()", 1.5), ("tour3", "for (const k of [1, 2]) setTimeout(() => document.querySelector('.tour .btn.primary').click(), k * 300)", 1.5),
                        ("dark_step", ESC + "; __t.prefs('dark', 'large'); __t.startGuide('dashboard'); 0", 2.5)]:
        win.evaluate_js(js)
        time.sleep(w)
        _grab(win, os.path.join(out, f"g_{name}.png"))


# 3.10.1：她的回饋 1151126（MY_LEDGER_SCENES=fb1126）：分類帳與日記帳的行備註、收支損益表沒有筆數、自訂比較期間
_MKMEMO = ("(async () => { const f = await pywebview.api.journal_form(null); const k = (n) => f.chart.find(c => c.name === n).key;"
           " await pywebview.api.journal_save({date: new Date().toISOString().slice(0, 10), note: '1151101-1151122 台銀NT 彙整', tags: [],"
           " lines: [{key: k('日常用品'), debit: 2930, memo: '玉山信用卡費'}, {key: k('日常用品'), debit: 9223, memo: '星展信用卡費'},"
           " {key: k('居家水電'), debit: 2442, memo: '電費'}, {key: k('台銀活存'), credit: 14595, memo: '1151101-1151122'}]}); })()")
_SELCMP = ("(() => {{ const s = [...document.querySelectorAll('.cmpbar select')].pop(); const i = [...s.options].findIndex(o => o.text.includes('{}'));"
           " s.value = i; s.dispatchEvent(new Event('change', {{bubbles: true}})); }})()")
FB1126 = []
for scale in ("normal", "large"):
    s = f"fb_{scale}_"
    FB1126 += [(s + "seed", f"__t.prefs('light', '{scale}'); " + (_MKMEMO if scale == "normal" else "0"), 1.5),
               (s + "ledger", "window.__pendingReport = {tab: 'ledger'}; __t.go('dashboard'); setTimeout(() => __t.go('reports'), 300)", 3),
               (s + "ledger_pick", "const li = document.querySelector('.ledger-pick input'); li.focus(); li.value = '日常用品';"
                " li.dispatchEvent(new Event('input', {bubbles: true})); setTimeout(() => document.querySelector('.pop.floating > div').dispatchEvent(new MouseEvent('mousedown', {bubbles: true})), 400)", 2),
               (s + "ledger_end", "document.querySelector('.page-fill .tablewrap').scrollTop = 99999", 1),
               (s + "journal", "__t.tab('日記帳')", 2), (s + "journal_kw", "const i = document.querySelector('.page-fill .text input'); i.value = '星展';"
                " i.dispatchEvent(new Event('input', {bubbles: true}))", 2),
               (s + "is", "__t.tab('收支損益表')", 2), (s + "is_custom", _SELCMP.format("自訂"), 2),
               (s + "bs", "__t.tab('資產負債表')", 2), (s + "bs_custom", _SELCMP.format("自訂"), 2),
               (s + "bs_back", _SELCMP.format("不比較") + "; setTimeout(() => " + _SELCMP.format("不比較").replace("{{", "{").replace("}}", "}") + ", 50)", 1.5),
               (s + "print", "__t.openPrint && 0", 0.5)]
FB1126 = [(n, j.replace("{{", "{").replace("}}", "}") if n.endswith(("_custom", "_back")) else j, w) for n, j, w in FB1126]


# README 用的截圖（MY_LEDGER_SCENES=readme）：淺色、大字，範例帳本
README = [
    ("readme_dashboard", "__t.prefs('light', 'large'); __t.go('dashboard')", 3.5),
    ("readme_insights", "document.querySelector('.insights-row').scrollIntoView()", 2),
    ("readme_transactions", "document.querySelector('.main').scrollTop = 0; __t.go('transactions')", 2.5),
    ("readme_txn_dialog", "__t.openTxn({type: 'expense'})", 1.8),
    ("readme_journal", ESC + "; __t.openUserJournal()", 2.5),
    ("readme_investments", ESC + "; __t.go('investments')", 3),
    ("readme_reports", "__t.go('reports')", 3),
    ("readme_annual", "__t.openAnnual([2026, 2025])", 1.5),
    ("readme_monthclose", ESC + "; __t.openMonthClose()", 2),
    ("readme_health", ESC + "; __t.openHealth()", 3),
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
    ("settings_mid", "__t.tab('收支分類')", 1.2),
    ("settings_lower", "__t.tab('資料管理與備份')", 1.2),
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
    from desktop.screenshot import grab_window
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


def _guard(fn):
    """測試執行緒若出錯，寫下原因並關閉視窗；否則視窗會一直開著，看起來像程式當掉。"""
    def call(win, out: str) -> None:
        import sys
        import traceback
        for st in (sys.stdout, sys.stderr):
            try:
                st.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001 — 沒有主控台時
                pass
        try:
            fn(win, out)
        except Exception:  # noqa: BLE001
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "driver_error.txt"), "w", encoding="utf-8") as f:
                try:          # 視窗當時顯示的是什麼
                    f.write(str(win.evaluate_js("JSON.stringify({href: location.href, title: document.title, state: document.readyState,"
                                                " scripts: [...document.scripts].map(x => x.src), res: performance.getEntriesByType('resource')"
                                                ".map(x => [x.name, x.responseStatus, Math.round(x.duration)]), html: document.documentElement.outerHTML.slice(0, 1500)})")) + "\n")
                except Exception as e:  # noqa: BLE001
                    f.write(f"（無法讀取畫面：{e}）\n")
                f.write(traceback.format_exc())
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                os._exit(1)
    return call


@_guard
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


@_guard
def run(win, out: str) -> None:
    os.makedirs(out, exist_ok=True)
    only = [s for s in os.environ.get("MY_LEDGER_SCENES", "").split(",") if s]
    time.sleep(5)
    errors = []
    scenes = {"readme": README, "mom": MOM, "audit": AUDIT, "features": FEATURES, "flow": FLOW, "xl": XL, "fb1126": FB1126, "guard": [("guard", _guard_check, 0.5)], "guide": [("guide", _guide_check, 0.5)]}.get(only[0] if len(only) == 1 else "", SCENES)
    if only in (["mom"], ["audit"], ["features"], ["flow"], ["guard"], ["guide"], ["fb1126"]) or (only and os.environ.get("MY_LEDGER_VIEW")):
        view = os.environ.get("MY_LEDGER_VIEW")
        if view:          # 畫面可用範圍（CSS 像素）× 放大倍率 ＋ 視窗外框
            size, scale = view.split("@")
            tw, th = (int(x) for x in size.split("x"))
            w, h = round(tw * float(scale)) + 16, round(th * float(scale)) + 39
            for _ in range(6):        # 視窗大小的單位會隨這台電腦的 Windows 縮放而不同：量畫面內的大小再修正，直到剛好是她的 1024×528
                win.resize(w, h)
                time.sleep(0.8)
                vw, vh = (int(x) for x in win.evaluate_js("innerWidth + 'x' + innerHeight").split("x"))
                if (vw, vh) == (tw, th):
                    break
                w = round(w + (tw - vw) * (w - 16) / max(vw, 1))      # 依目前「視窗單位 ÷ 畫面像素」的比例補差
                h = round(h + (th - vh) * (h - 39) / max(vh, 1))
        else:
            win.resize(1280, 720)
        time.sleep(1.5)
        print("viewport", win.evaluate_js("innerWidth + 'x' + innerHeight + '@' + devicePixelRatio"), flush=True)
    for name, js, wait in scenes:
        if only and scenes is SCENES and not any(name.startswith(o) for o in only):
            continue
        if name == "min_window":
            win.resize(1100, 700)
            time.sleep(0.5)
        try:
            js(win, out) if callable(js) else win.evaluate_js(js)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
        time.sleep(wait)
        if name.startswith("mom_") and not name.endswith(("_close", "_combo_open")):
            print(f"{name}: {win.evaluate_js('window.__t.visibleRows()')}", flush=True)
        if name.startswith(("audit_", "feat_", "flow_", "fb_")) and not name.endswith(("_close", "_dlg_search")):
            print(f"{name}: {win.evaluate_js('window.__t.audit()')}", flush=True)
        if name.startswith("flow_"):
            print(f"   對話框：{win.evaluate_js("[...document.querySelectorAll('.dialog h2')].map(x => x.textContent).join(' > ')")}", flush=True)
        if name.endswith("_combo_open"):
            print(f"{name}: 下拉選單顯示 {win.evaluate_js("[...document.querySelectorAll('.pop.floating > div')].filter(d => {const r=d.getBoundingClientRect(); const p=d.closest('.pop').getBoundingClientRect(); return r.top>=p.top-1 && r.bottom<=Math.min(p.bottom, innerHeight)+1}).length")} 個項目", flush=True)
        errs = json.loads(win.evaluate_js("JSON.stringify(window.__errors.splice(0))") or "[]")
        errors += [f"{name}: {e}" for e in errs]
        _grab(win, os.path.join(out, f"{name}.png"))
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
    if os.environ.get("MY_LEDGER_CLOSE_DIRTY") == "boot":     # 真正的開啟流程：更新說明 → 帶我看看新功能 → 歡迎導覽 → 帶我看一圈 → 第一次的提示
        st = "JSON.stringify([window.__guideOpen || '', window.__guideStep ? window.__guideStep.title : '', [...document.querySelectorAll('.dialog h2')].map(x => x.textContent).join(' > '), (document.querySelector('.nudge-card b') || {}).textContent || ''])"
        def say(label, js=None, wait=2.0):
            if js:
                win.evaluate_js(js)
            time.sleep(wait)
            print(label, win.evaluate_js(st), flush=True)
            _grab(win, os.path.join(out, f"boot_{label}.png"))
        say("1_更新說明")
        say("2_看新功能", _TOPBTN.format("帶我看看新功能"), 2.5)
        for _ in range(4):
            win.evaluate_js("window.__guideOpen && window.__guideMove(1)")
            time.sleep(2)
        say("3_看完", None, 1)
        for _ in range(2):
            win.evaluate_js("(document.querySelector('.tour .btn.primary') || {click() {}}).click()")
            time.sleep(0.6)
        say("4_歡迎導覽", None, 0.5)
        say("5_帶我看一圈", "([...document.querySelectorAll('.tour .btn')].find(b => b.textContent.includes('帶我看一圈')) || {click() {}}).click()", 2.5)
        for _ in range(6):
            win.evaluate_js("window.__guideOpen && window.__guideMove(1)")
            time.sleep(1.2)
        say("6_看完", None, 2)
        for _ in range(3):
            win.evaluate_js(ESC)
        say("7_提示", None, 3)
        win.evaluate_js("__t.go('reports')")
        time.sleep(22)
        say("8_換頁", "__t.go('transactions')", 3)
        print("紀錄", win.evaluate_js("pywebview.api.guide_state().then(s => { window.__gs = JSON.stringify(s); }); 1") and (time.sleep(0.5) or win.evaluate_js("window.__gs")), flush=True)
        threading.Thread(target=win.destroy, daemon=True).start()
        return
    if os.environ.get("MY_LEDGER_CLOSE_DIRTY"):        # 有打到一半的傳票時關視窗：先問；繼續編輯後內容還在；放棄才結束
        win.evaluate_js("__t.openJournal()")
        time.sleep(1.5)
        win.evaluate_js(_TYPE.format(_JN, "還沒存的分錄"))
        time.sleep(0.5)
        threading.Thread(target=win.destroy, daemon=True).start()
        time.sleep(1.5)
        print("關視窗 →", win.evaluate_js(_TITLES), flush=True)
        _grab(win, os.path.join(out, "close_ask.png"))
        win.evaluate_js(_TOPBTN.format("繼續編輯"))
        time.sleep(0.6)
        print("繼續編輯 →", win.evaluate_js(_TITLES), "｜", win.evaluate_js(f"document.querySelector('.dialog.journal {_JN}').value"), flush=True)
        threading.Thread(target=win.destroy, daemon=True).start()
        time.sleep(1.5)
        win.evaluate_js("setTimeout(() => " + _TOPBTN.format("放棄並結束") + ", 50)")
        time.sleep(0.5)
        print("放棄並結束 →", win.evaluate_js("!!document.getElementById('farewell')"), flush=True)
        return
    threading.Thread(target=win.destroy, daemon=True).start()     # 與按視窗的 ✕ 相同：觸發結束畫面
    time.sleep(0.35)
    try:
        _grab(win, os.path.join(out, "farewell_saving.png"))
        time.sleep(0.9)
        _grab(win, os.path.join(out, "farewell_done.png"))
    except Exception as e:  # noqa: BLE001
        print("grab failed:", e, flush=True)
