"""畫面介面（desktop/api*.py）的測試：不開視窗。

* 每個已發行版本建立的帳本（tests/fixtures）都要能讓每一個讀取功能正常運作，
  而且數字與 core/ 帳務程式直接計算的結果完全相同。
* 每一個寫入功能（記帳、分錄、投資、對帳、定期交易、結帳…）都要維持帳務平衡。

執行：python tests/test_api.py（Windows 上用 venv3；需要 openpyxl），最後印出 ALL PASSED。
"""

import datetime as dt
import csv
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.database import Database  # noqa: E402
from core.investments import Investments  # noqa: E402
from core.sample_data import load_sample_data  # noqa: E402
from tests.test_core import FIXTURES, balanced, check_books, old_ledgers  # noqa: E402
from desktop.api import Api, DbThread  # noqa: E402

PRESETS = ["本月", "上月", "今年", "去年", "全部"]


def ok(r, where=""):
    """API 傳回錯誤時讓測試失敗（帶上訊息）。"""
    assert not (isinstance(r, dict) and "__error__" in r), (where, r)
    json.dumps(r)                     # 一定能傳給畫面
    return r


def err(r):
    assert isinstance(r, dict) and "__error__" in r and not r.get("__bug__"), r
    return r["__error__"]


class Ledger:
    """在暫存資料夾開一本帳本，透過 Api 操作（與畫面相同的呼叫方式）。"""

    def __init__(self, src: str | None = None, sample: bool = False):
        self.dir = tempfile.mkdtemp(prefix="v3test_")
        self.path = os.path.join(self.dir, "理財帳本.db")
        if src:
            shutil.copy(src, self.path)
        self.dbt = DbThread()
        self.db = self.dbt.run(Database, self.path)
        if sample:
            self.dbt.run(load_sample_data, self.db)
        self.api = Api(self.dbt, self.db, self.dir, False)

    def run(self, fn, *a):
        return self.dbt.run(fn, *a)

    def close(self):
        self.dbt.run(self.db.close)
        self.dbt.close()


def ranges(lg):
    lo, hi = ok(lg.api.date_range())
    t = dt.date.today()
    out = [(lo, hi), (f"{t.year}-01-01", f"{t.year}-12-31"), (f"{t.year - 1}-01-01", f"{t.year - 1}-12-31")]
    m = t.replace(day=1)
    out.append((m.isoformat(), (m + dt.timedelta(days=40)).replace(day=1).isoformat()))
    return out


def db_accounts(lg):
    return lg.run(lambda: [dict(x) for x in lg.db.list_accounts(include_archived=True)])


# ---------------------------------------------------------------------- 讀取：每一本舊帳本
def read_everything(lg: Ledger, where: str):
    a, db = lg.api, lg.db
    meta = ok(a.meta(), where)
    assert meta["base"] == lg.run(lambda: db.base_currency)
    # 總覽與帳戶：數字與 v2 相同
    d = ok(a.dashboard(), where)
    nw = lg.run(db.net_worth)
    assert (d["net"], d["assets"], d["liabilities"]) == (nw["net"], nw["assets"], nw["liabilities"]), where
    ap = ok(a.accounts_page(True), where)
    assert ap["net"] == nw["net"], where
    summ = {x["id"]: x for x in lg.run(db.account_summaries, None, True)}
    for kind in ("asset", "liability"):
        for x in ap["groups"][kind]:
            assert x["balance"] == summ[x["id"]]["balance"], (where, x["name"])
    # 收支明細：每個期間、每種篩選；合計與 v2 的收支損益相同
    f = ok(a.txn_filters(), where)
    for start, end in ranges(lg):
        lst = ok(a.txn_list({"start": start, "end": end}), where)
        ie = lg.run(db.income_expense_totals, start, end)
        assert abs(lst["income"] - ie["income"]) < 0.01 and abs(lst["expense"] - ie["expense"]) < 0.01, (where, start)
        ok(a.txn_list({"start": start, "end": end, "void": True, "keyword": "a"}), where)
        for acc in f["accounts"][:3]:
            ok(a.txn_list({"start": start, "end": end, "account": acc["id"]}), where)
        for t in f["tags"][:2]:
            ok(a.txn_list({"start": start, "end": end, "tag": t}), where)
    allrows = ok(a.txn_list({"start": "1900-01-01", "end": "2999-12-31", "void": True}), where)["rows"]
    for r in allrows[:40] + [x for x in allrows if x["type"] == "journal"][:20]:
        ok(a.voucher(r["id"]), where)
        if r["type"] == "journal":
            jf = ok(a.journal_form(r["id"]), where)
            assert jf["txn"]["lines"], where
        else:
            ok(a.txn_form(r["id"]), where)
        ok(a.audit(r["id"], ""), where)
        ok(a.voucher_html(r["id"]), where)
    ok(a.txn_form(None), where)
    ok(a.journal_form(None), where)
    ok(a.audit(None, ""), where)
    # 投資：持股與 v2 相同、投資科目＝帳面價值
    ip = ok(a.invest_page(None), where)
    hold = lg.run(Investments(db).holdings)
    assert [(h["id"], h["shares"], h["market_value"]) for h in ip["holdings"]] == \
        [(h["id"], h["shares"], h["market_value"]) for h in hold], where
    ok(a.invest_events(None, *ip["range"]), where)
    for s in ip["securities"]:
        ok(a.invest_events(s["id"], *ip["range"]), where)
        ok(a.security_form(s["id"]), where)
        ok(a.trade_form(s["id"], ip["latest"]), where)
        ok(a.sec_info(s["id"]), where)
    ok(a.invest_realized(*ip["range"]), where)
    ok(a.invest_performance(None), where)
    ok(a.price_form(ip["latest"]), where)
    ok(a.rate_form(), where)
    # 財務報表：每個分頁、每種比較方式
    rm = ok(a.reports_meta(), where)
    for start, end in ranges(lg):
        for mode in ("none", "prior_period", "prior_year"):
            bs = ok(a.report_bs(start, end, mode), where)
            grand = [r for r in bs["rows"] if r["style"] == "grand"][0]
            total = [r for r in bs["rows"] if r["name"] == "資產總計"][0]
            assert abs(grand["cur"] - total["cur"]) < 0.05, (where, start, mode)     # 資產＝負債＋淨值
            ok(a.report_is(start, end, mode), where)
        cf = ok(a.report_cf(start, end), where)
        assert abs(cf["check"]) < 0.05, where
        ok(a.report_monthly(start, end), where)
        for k in ("expense", "income"):
            ok(a.report_categories(start, end, k), where)
        for t in ok(a.report_tags(start, end), where)[:3]:
            ok(a.report_tag_detail(t["name"], start, end), where)
        jn = ok(a.report_journal(start, end, ""), where)
        for e in jn:
            assert balanced(e["lines"]), (where, e["voucher"])
        tb = ok(a.report_tb(start, end), where)
        for x, y in (("open_debit", "open_credit"), ("period_debit", "period_credit"), ("debit", "credit")):
            assert abs(sum(r[x] for r in tb) - sum(r[y] for r in tb)) < 1, (where, start, x)
        for acc in rm["accounts"]:
            lgd = ok(a.report_ledger(acc["id"], start, end), where)
            assert abs(lgd["opening"] + lgd["debit_total"] * (1 if lgd["side"] == "借" else -1)
                       - lgd["credit_total"] * (1 if lgd["side"] == "借" else -1) - lgd["closing"]) < 0.05, (where, acc)
        # 分類帳：全部會計科目，每一科目都要與試算表相同
        tb = {r["code"]: r for r in ok(a.report_tb(start, end), where)}
        rates = {f"account:{x['id']}": (x["rate"], x["kind"]) for x in db_accounts(lg)}
        seen = set()
        for s in rm["subjects"]:
            x = ok(a.report_ledger(s["key"], start, end), (where, s))
            code = s["label"].split("　")[0]
            seen.add(code)
            rate = rates.get(s["key"], (1, ""))[0]
            side = 1 if x["side"] == "借" else -1
            t = tb.get(code, {"debit": 0, "credit": 0, "period_debit": 0, "period_credit": 0})
            assert abs(x["closing"] * rate * side - (t["debit"] - t["credit"])) < 0.06, (where, start, end, s, x["closing"], t)
            assert abs(x["opening"] + side * (x["debit_total"] - x["credit_total"]) - x["closing"]) < 0.06, (where, s)
            if not s["key"].startswith(("account:", "equity:")):
                assert abs(x["debit_total"] - t["period_debit"]) < 0.06 and abs(x["credit_total"] - t["period_credit"]) < 0.06, (where, s)
        assert set(tb) <= seen, (where, set(tb) - seen)        # 試算表上的每個科目都查得到分類帳
        assert ok(a.print_html(["vouchers", "journal", "ledger", "trial", "bs", "is", "equity", "ratios", "cashflow"],
                               start, end, "prior_year"), where).startswith("<html>")
    for y in rm["years"]:
        ok(a.report_tax(y), where)
        assert ok(a.annual_html(y, [k for k, _, _ in ok(a.print_options(), where)["annual"]]), where).startswith("<html>")
    # 設定、科目表、結帳預覽、其他
    sp = ok(a.settings_page(), where)
    ok(a.chart(True), where)
    for y in sp["close_years"]:
        ok(a.year_close_preview(y["year"]), where)
    ok(a.recurring_list(), where)
    ok(a.due_list(), where)
    rc = ok(a.recon_load(None, dt.date.today().isoformat()), where)
    for acc in rc["accounts"][:3]:
        ok(a.recon_load(acc["id"], dt.date.today().isoformat()), where)
    ok(a.template_list(), where)
    for q in ("V000001", "2025-03", "114/3/5", "1,000", "餐", "現金 2026"):
        ok(a.search(q), where)
    ok(a.export_form(), where)
    out = os.path.join(lg.dir, "export.xlsx")
    ok(a.export_excel(*ok(a.date_range()), [s[0] for s in ok(a.export_form())["sheets"]], out), where)
    assert os.path.getsize(out) > 5000, where
    ok(a.update_settings(), where)
    ok(a.tour_status(), where)
    dd = ok(a.dashboard(), where)
    assert {"today_count", "streak", "ranking", "insights"} <= dd.keys(), where
    ok(a.first_run(), where)
    ok(a.backup_reminder(), where)
    assert "calendar" in dd, where
    # 3.5：提醒中心、月結、健康檢查、月報、快速記帳
    ru = ok(a.reminders_upcoming(120), where)
    assert all(e["date"] >= (dt.date.today() - dt.timedelta(days=7)).isoformat() for e in ru["events"]), where
    mc = ok(a.month_close(), where)
    assert mc["total"] == 6 and 0 <= mc["done"] <= 6 and mc["months"], where
    for ym in mc["months"][:3]:
        ok(a.month_close(ym), where)
        assert ok(a.monthly_html(ym), where).startswith("<html>"), where
    hr = ok(a.health_run(), where)
    assert hr["bad"] == 0, (where, [c for c in hr["checks"] if c["status"] == "bad"])
    assert {c["key"] for c in hr["checks"]} >= {"file", "trial", "vouchers", "backup", "recurring"}, where
    assert ok(a.health_html(), where).startswith("<html>")
    fc = ok(a.cash_forecast(6), where)
    for acc in fc["accounts"]:
        evs = [e for e in fc["events"] if e["account_id"] == acc["id"]]
        assert abs(acc["start"] + sum(e["amount"] for e in evs) - acc["end"]) < 0.05, (where, acc["name"])
        assert len(acc["series"]) == len(fc["weeks"]), where
    assert ok(a.feedback_diag(), where)["schema"] >= 9
    tf = ok(a.txn_form(None), where)
    assert isinstance(tf["quick"], list) and isinstance(tf["hints"], dict), where


def test_old_ledgers_read():
    files = old_ledgers()
    assert len(files) >= 10, files
    for name in files:
        lg = Ledger(os.path.join(FIXTURES, name))
        try:
            read_everything(lg, name)
            lg.run(check_books, lg.db, name)
        finally:
            lg.close()


def test_sample_ledger_read():
    lg = Ledger(sample=True)
    try:
        read_everything(lg, "sample")
    finally:
        lg.close()


# ---------------------------------------------------------------------- 寫入：每一個功能都要維持帳務平衡
def test_writes_keep_books_balanced():
    lg = Ledger(sample=True)
    a, db = lg.api, lg.db
    try:
        today = dt.date.today().isoformat()
        form = ok(a.txn_form(None))
        cash = form["accounts"][0]["id"]
        bank = form["accounts"][1]["id"]
        exp = form["categories"]["expense"][0]["id"]
        inc = form["categories"]["income"][0]["id"]
        n0 = lg.run(lambda: db._q1("SELECT COUNT(*) n FROM transactions")["n"])
        # 記一筆（含標籤）、修改、作廢、取消作廢、迴轉、復原
        t1 = ok(a.txn_save({"date": today, "type": "expense", "account_id": cash, "amount": 123, "category_id": exp,
                            "note": "v3 測試", "tags": ["測試專案"]}))["id"]
        assert "測試專案" in ok(a.txn_form(t1))["txn"]["tags"]
        ok(a.txn_save({"date": today, "type": "expense", "account_id": cash, "amount": 150, "category_id": exp,
                       "note": "v3 測試（改）", "tags": []}, t1))
        assert lg.run(db.get_transaction, t1)["amount"] == 150
        ok(a.undo())                      # 復原修改
        assert lg.run(db.get_transaction, t1)["amount"] == 123
        t2 = ok(a.txn_save({"date": today, "type": "income", "account_id": bank, "amount": 1000, "category_id": inc}))["id"]
        t3 = ok(a.txn_save({"date": today, "type": "transfer", "account_id": bank, "to_account_id": cash, "amount": 500}))["id"]
        assert "請點選一個分類" in err(a.txn_save({"date": today, "type": "expense", "account_id": cash, "amount": 1}))
        ok(a.txn_void([t2], "輸入錯誤"))
        assert lg.run(db.get_transaction, t2)["void"]
        ok(a.txn_unvoid(t2))
        ok(a.txn_reverse(t3))
        ok(a.tag_add([t2, t3], "旅行"))
        ok(a.tag_remove([t3], "旅行"))
        ok(a.tag_rename("旅行", "日本旅遊"))
        assert lg.run(db.get_tags, t2) == ["日本旅遊"]
        ok(a.adjust_save(9, today, 700000, "保單價值更新"))
        # 複式分錄：連結投資標的的買進（自動手續費）、確認未連結的提示、外幣
        jf = ok(a.journal_form(None))
        invacc = [c for c in jf["chart"] if c["investment"]][0]["key"]
        sid = [s for s in jf["securities"] if f"account:{s['account_id']}" == invacc][0]["id"]
        fee, _ = ok(a.trade_fees(sid, "buy", 100, 100))
        amount = 100 * 100 + fee
        need = ok(a.journal_save({"date": today, "note": "x", "lines": [{"key": invacc, "debit": amount},
                                                                       {"key": f"account:{bank}", "credit": amount}]}))
        assert need.get("need_confirm"), need
        j1 = ok(a.journal_save({"date": today, "note": "買進", "tags": ["投資"], "lines": [
            {"key": invacc, "debit": amount, "security_id": sid, "shares": 100, "price": 100},
            {"key": f"account:{bank}", "credit": amount}]}))["id"]
        assert "借貸不平衡" in err(a.journal_save({"date": today, "lines": [{"key": f"account:{cash}", "debit": 5},
                                                                          {"key": f"account:{bank}", "credit": 4}]}))
        usd = [c for c in jf["chart"] if c["currency"] == "USD"]
        if usd:
            ok(a.journal_save({"date": today, "note": "換匯", "lines": [{"key": usd[0]["key"], "debit": 3200, "orig": 100},
                                                                     {"key": f"account:{bank}", "credit": 3200}]}))
        ok(a.template_add("測試範本", [["debit", f"account:{cash}", "", 100], ["credit", f"account:{bank}", "", 100]]))
        assert any(t["name"] == "測試範本" for t in ok(a.template_list()))
        # 投資管理：買進、賣出、股利、市價評價、刪除交易
        ok(a.trade_save(sid, "buy", {"date": today, "shares": 50, "price": 100, "fee": 20, "cash": bank}))
        ok(a.trade_save(sid, "sell", {"date": today, "shares": 30, "price": 105, "fee": 20, "tax": 3, "cash": bank}))
        ok(a.trade_save(sid, "cash_div", {"date": today, "amount": 25000, "nhi": ok(a.suggest_nhi(25000)), "cash": bank}))
        ok(a.trade_save(sid, "stock_div", {"date": today, "shares": 10}))
        ok(a.price_save(today, [[sid, 120]]))
        ev = ok(a.invest_events(sid, "1900-01-01", "2999-12-31"))
        ok(a.event_delete([e for e in ev if e["kind"] == "stock_div"][0]["id"]))
        ok(a.undo())                      # 復原刪除
        sf = ok(a.security_form(sid))
        ok(a.security_save({**sf["security"], "fee_rate": 0.000855, "fee_min": 1, "tax_rate": 0.001, "type_name": ""}, sid))
        # 帳戶、科目、分類
        aid = ok(a.account_save({"name": "v3 測試帳戶", "kind": "asset", "category": "銀行存款", "currency": "TWD",
                                 "opening_balance": 1000, "opening_date": "2026-01-01"}))["id"]
        ok(a.account_archive(aid, True))
        ok(a.account_archive(aid, False))
        sub = ok(a.subject_save({"nature": "expense", "name": "v3 測試費用", "code": "", "budget": 500, "tax_tag": ""}))
        ok(a.category_update(sub["key"][1], {"budget": 800}))
        ok(a.category_move(sub["key"][1], -1))
        ok(a.category_delete(sub["key"][1]))
        # 定期交易與對帳
        ok(a.recurring_save(None, {"name": "v3 測試月費", "type": "expense", "account_id": bank, "category_id": exp,
                                   "amount": 300, "freq": "monthly", "day": 1, "start_date": "2026-01-01"}))
        due = ok(a.due_list())
        if due:
            ok(a.due_post([{"rec_id": d["rec_id"], "date": d["date"], "amount": d["amount"]} for d in due[:2]]))
        rc = ok(a.recon_load(bank, today))
        ok(a.recon_save(bank, today, rc["book"], [i["txn_id"] for i in rc["items"]]))
        # 帳務仍然平衡、投資科目＝帳面價值
        lg.run(check_books, db, "after writes")
        assert lg.run(lambda: db._q1("SELECT COUNT(*) n FROM transactions")["n"]) > n0
        # 結帳後不能修改已結帳期間；可以加標籤
        ok(a.set_closed(today))
        assert "已結帳" in err(a.txn_save({"date": today, "type": "expense", "account_id": cash, "amount": 1, "category_id": exp}))
        ok(a.tag_add([t1], "結帳後仍可加標籤"))
        ok(a.set_closed(""))
        # 年度結帳（去年）
        last = dt.date.today().year - 1
        pv = ok(a.year_close_preview(last))
        if not pv["blocked"]:
            ok(a.year_close(last))
            assert ok(a.year_close_preview(last))["done"]
            ok(a.set_closed(""))
        # 備份、第二份備份、還原
        bk = os.path.join(lg.dir, "backup.db")
        ok(a.backup_to(bk))
        assert Database.is_valid_ledger(bk)
        extra = tempfile.mkdtemp(prefix="v3extra_")
        r = ok(a.extra_set(extra, True))
        assert os.path.exists(r["path"]), r
        ok(a.extra_disable())
        lg.run(check_books, db, "before restore")
        ok(a.restore_from(bk))
        lg.run(check_books, db, "after restore")
        assert "不是帳本" in err(a.restore_from(os.path.join(ROOT, "README.md"))) if os.path.exists(os.path.join(ROOT, "README.md")) else True
        # 設定
        for k, v in (("owner_name", "游媽媽"), ("online_updates", True), ("update_auto", False), ("theme_mode", "dark"),
                     ("font_scale", "xlarge"), ("animations", False)):
            ok(a.set_pref_setting(k, v))
        assert lg.run(db.get_setting, "theme_mode") == "dark" and lg.run(db.get_setting, "update_auto") == "0"
        assert err(a.set_pref_setting("closed_until", "2099-01-01"))       # 只能改允許的設定
        lg.run(check_books, db, "end")
    finally:
        lg.close()


def test_welcome_and_sample():
    lg = Ledger()
    a = lg.api
    try:
        assert ok(a.first_run())
        ok(a.welcome_finish("游媽媽", "sample"))
        assert ok(a.whats_new()) is None                    # 全新安裝不顯示「已更新到…」
        assert not ok(a.first_run()) and ok(a.meta())["owner"] == "游媽媽"
        assert ok(a.dashboard())["sample"]
        ok(a.clear_sample())
        assert not ok(a.dashboard())["sample"]
        names = [x["name"] for x in ok(a.accounts_page(False))["groups"]["asset"]]
        assert names, names
    finally:
        lg.close()


def test_whats_new_after_update():
    """每個版本第一次開啟顯示一次「已更新到…」：更新時存下的說明優先，否則用內附的 whatsnew.md。"""
    from core.version import APP_VERSION
    lg = Ledger(sample=True)
    a, db = lg.api, lg.db
    try:
        bundled = open(os.path.join(ROOT, "desktop", "whatsnew.md"), encoding="utf-8").read()
        assert ok(a.whats_new())["notes"] == bundled        # 從沒記錄版本的舊版（v2、3.1）更新上來：顯示內附說明
        assert ok(a.whats_new()) is None                    # 同一版本不重複顯示
        assert ok(a.tour_status())
        ok(a.tour_done())
        assert not ok(a.tour_status())
        lg.run(db.set_setting, "last_seen_version", "3.1.0")    # 從舊版更新上來（舊版沒有存說明）
        w = ok(a.whats_new())
        assert w["version"] == APP_VERSION and w["notes"] == bundled, w
        assert ok(a.whats_new()) is None
        lg.run(db.set_setting, "last_seen_version", "3.1.0")    # 更新時存下的 GitHub 說明優先
        lg.run(db.set_setting, "update_notes", json.dumps({"version": APP_VERSION, "notes": "* 網路上的說明"}))
        assert ok(a.whats_new())["notes"] == "* 網路上的說明"
    finally:
        lg.close()


def test_journal_without_account():
    """複式分錄不限定要有資產或負債科目（1151125 意見）：存、改、迴轉、作廢、復原與所有報表都要正常。"""
    lg = Ledger(sample=True)
    try:
        a, db = lg.api, lg.db
        today = dt.date.today().isoformat()
        chart = ok(a.journal_form(None))["chart"]
        exp = [c["key"] for c in chart if c["kind"] == "expense"][:2]
        inc = next(c["key"] for c in chart if c["kind"] == "income")
        net0 = lg.run(lambda: db.net_worth()["net"])
        year = (today[:4] + "-01-01", today[:4] + "-12-31")
        tot0 = {c["id"]: c["total"] for c in lg.run(db.category_totals, *year, "expense")}

        def line(key, dr=0, cr=0):
            return {"key": key, "debit": dr, "credit": cr}
        lines = [line(exp[0], dr=1200), line(exp[1], cr=1200)]
        r = ok(a.journal_save({"date": today, "note": "費用重分類", "lines": lines, "tags": ["重分類"]}, None))
        tid = r["id"] if isinstance(r, dict) else r
        tot1 = {c["id"]: c["total"] for c in lg.run(db.category_totals, *year, "expense")}
        i0, i1 = int(exp[0].split(":")[1]), int(exp[1].split(":")[1])
        assert abs(tot1.get(i0, 0) - tot0.get(i0, 0) - 1200) < 0.01 and abs(tot1.get(i1, 0) - tot0.get(i1, 0) + 1200) < 0.01
        # 損益轉淨值調整：淨資產不變、試算表仍平衡
        t2 = ok(a.journal_save({"date": today, "note": "轉淨值調整", "lines": [line(inc, dr=500), line("special:equity", cr=500)],
                                "tags": []}, None))
        t2 = t2["id"] if isinstance(t2, dict) else t2
        assert abs(lg.run(lambda: db.net_worth()["net"]) - net0) < 0.01
        lg.run(check_books, db, "journal without account")
        ok(a.journal_save({"date": today, "note": "費用重分類（改）", "lines": [line(exp[0], dr=900), line(exp[1], cr=900)],
                           "tags": []}, tid))
        read_everything(lg, "journal without account")
        row = next(x for x in ok(a.txn_list({"start": today, "end": today}))["rows"] if x["id"] == tid)
        assert row["account"] == "" and row["category"] and row["amount"] == 900
        for q in ("重分類", "900"):
            assert any(x["id"] == tid for x in ok(a.search(q))["rows"] if x["kind"] == "voucher"), q
        ok(a.voucher(tid)); ok(a.voucher_html(tid)); ok(a.journal_form(tid))
        rev = lg.run(db.reverse_transaction, tid)
        ok(a.txn_void([rev], "測試"))
        ok(a.undo())
        ok(a.undo())
        lg.run(check_books, db, "journal without account after undo")
        assert lg.run(lambda: db.net_worth()["net"]) == net0
        assert "兩行" in err(a.journal_save({"date": today, "note": "x", "lines": [line(exp[0], dr=1)], "tags": []}, None))
        assert "不平衡" in err(a.journal_save({"date": today, "note": "x", "lines": [line(exp[0], dr=2), line(exp[1], cr=1)], "tags": []}, None))
        path = lg.path
    finally:
        lg.close()
    db2 = Database(path)          # 重新開啟帳本也正常
    check_books(db2, "reopened")
    db2.close()


def test_display_info():
    import desktop.api_tools as tools
    d = tools._display_info()
    assert d["screen"] and d["screen"][0] >= 640 and 100 <= d["dpi_scale"] <= 500 and 100 <= d["text_scale"] <= 225


def test_quick_entry():
    """常記的項目：同一說明＋分類記過 2 次以上才列出；說明會帶出上次的分類與帳戶。"""
    lg = Ledger(sample=True)
    try:
        a = lg.api
        f = ok(a.txn_form(None))
        assert f["quick"], "範例帳本應該有常記的項目"
        for q in f["quick"]:
            assert q["count"] >= 2 and q["note"] and q["category"] and q["type"] in ("income", "expense"), q
        counts = [q["count"] for q in f["quick"]]
        assert counts == sorted(counts, reverse=True)
        q = f["quick"][0]
        h = f["hints"][q["note"]]
        assert h["type"] == q["type"] and h["category_id"] and h["account_id"]
        # 新記一筆後，提示改用最新的帳戶
        acc2 = next(x["id"] for x in f["accounts"] if x["id"] != h["account_id"] and x["kind"] == "asset")
        ok(a.txn_save({"date": dt.date.today().isoformat(), "type": q["type"], "account_id": acc2, "amount": 123,
                       "note": q["note"], "category_id": q["category_id"], "tags": []}))
        assert ok(a.txn_form(None))["hints"][q["note"]]["account_id"] == acc2
        assert ok(a.txn_form(1))["quick"] == []          # 編輯時不需要
    finally:
        lg.close()


def test_reminders_custom():
    from core import reminders
    lg = Ledger(sample=True)
    try:
        a = lg.api
        today = dt.date.today()
        assert "名稱" in err(a.reminder_save({"title": " ", "date": today.isoformat()}))
        assert "日期" in err(a.reminder_save({"title": "保費", "date": ""}))
        day = (today + dt.timedelta(days=5)).isoformat()
        r = ok(a.reminder_save({"title": "國泰人壽保費", "kind": "insurance", "freq": "yearly", "date": day,
                                "amount": 36000, "lead": 10}))
        m = ok(a.reminder_save({"title": "信用卡繳款", "kind": "card", "freq": "monthly",
                                "date": (today.replace(day=1) - dt.timedelta(days=40)).replace(day=15).isoformat()}))
        ev = ok(a.reminders_upcoming(90))["events"]
        ins = [e for e in ev if e.get("id") == r["id"]]
        assert len(ins) == 1 and ins[0]["date"] == day and ins[0]["urgent"] and ins[0]["amount"] == 36000
        cards = [e for e in ev if e.get("id") == m["id"]]
        assert 2 <= len(cards) <= 4 and all(e["date"][8:] == "15" for e in cards), cards
        assert any(x["kind"] == "event" and x["event"].get("id") == r["id"] for x in ok(a.dashboard())["reminders"])
        ok(a.reminder_save({**r, "title": "國泰人壽年繳保費"}))
        assert [c["title"] for c in ok(a.reminders_upcoming())["custom"]].count("國泰人壽年繳保費") == 1
        ok(a.reminder_delete(r["id"]))
        assert all(c["id"] != r["id"] for c in ok(a.reminders_upcoming())["custom"])
        # 每月 31 日在小月改為月底；報稅季
        item = {"id": "x", "title": "t", "kind": "other", "freq": "monthly", "date": "2026-01-31", "lead": 7}
        assert reminders.occurrences(item, dt.date(2026, 2, 1), dt.date(2026, 3, 31)) == [dt.date(2026, 2, 28),
                                                                                         dt.date(2026, 3, 31)]
        tax = [e for e in lg.run(reminders.upcoming, lg.db, 60, dt.date(2027, 4, 20)) if e["kind"] == "tax"]
        assert [e["date"] for e in tax] == ["2027-05-01", "2027-05-31"] and tax[0]["year"] == 2026
        lg.run(check_books, lg.db, "reminders")
    finally:
        lg.close()


def test_month_close_flow():
    from core import monthclose
    lg = Ledger(sample=True)
    try:
        a = lg.api
        ym = monthclose.previous_month()
        st = ok(a.month_close(ym))
        assert st["ym"] == ym and [s["key"] for s in st["steps"]] == [k for k, _, _ in monthclose.STEPS]
        assert not next(s for s in st["steps"] if s["key"] == "budget")["ok"]        # 需要她自己確認
        for k in ("budget", "health", "report"):
            ok(a.month_close_check(ym, k, True))
        st2 = ok(a.month_close(ym))
        assert st2["done"] == st["done"] + 3
        ok(a.month_close_check(ym, "report", False))
        assert ok(a.month_close(ym))["done"] == st["done"] + 2
        assert "步驟" in err(a.month_close_check(ym, "nope", True))
        ok(a.month_close_finish(ym))
        assert ok(a.month_close(ym))["finished"]
        assert not any(x["kind"] == "monthclose" for x in ok(a.dashboard())["reminders"])
        # 開啟時的提醒：每月最多一次
        lg.run(lg.db.set_setting, "month_close", "")
        first = lg.run(monthclose.should_prompt, lg.db, dt.date.today().replace(day=3))
        if first:
            lg.run(monthclose.mark_prompted, lg.db, first)
            assert lg.run(monthclose.should_prompt, lg.db, dt.date.today().replace(day=3)) == ""
        assert lg.run(monthclose.should_prompt, lg.db, dt.date.today().replace(day=25)) == ""
        lg.run(check_books, lg.db, "month close")
    finally:
        lg.close()


def test_smart_recon():
    """銀行明細（存入／提出／餘額欄）自動勾選：金額相同、日期差 3 天內；帳上沒有的列出來。"""
    lg = Ledger(sample=True)
    try:
        a = lg.api
        today = dt.date.today().isoformat()
        rc = ok(a.recon_load(None, today))
        acc = next(x for x in rc["accounts"] if "活存" in x["name"] or "活儲" in x["name"])
        items = ok(a.recon_load(acc["id"], today))["items"][-8:]
        assert len(items) >= 4
        path = os.path.join(lg.dir, "bank.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["交易日期", "摘要", "提出", "存入", "餘額"])
            bal = 100000
            for i, it in enumerate(items[:-1]):          # 最後一筆故意不在銀行明細裡
                d = dt.date.fromisoformat(it["date"]) + dt.timedelta(days=2 if i == 0 else 0)
                bal += it["effect"]
                w.writerow([d.isoformat().replace("-", "/"), it["note"], f"{-it['effect']:,.0f}" if it["effect"] < 0 else "",
                            f"{it['effect']:,.0f}" if it["effect"] > 0 else "", f"{bal:,.0f}"])
            w.writerow([items[-2]["date"].replace("-", "/"), "銀行手續費", "15", "", f"{bal - 15:,.0f}"])
        r = ok(a.recon_match(acc["id"], today, path))
        assert set(r["matched"]) == {it["txn_id"] for it in items[:-1]}, r
        assert items[-1]["txn_id"] in r["book_only"]
        assert [b["amount"] for b in r["bank_only"]] == [-15.0] and r["last_balance"] == bal - 15
        bad = os.path.join(lg.dir, "bad.csv")
        open(bad, "w", encoding="utf-8").write("名稱,數量\na,1\n")
        assert "日期" in err(a.recon_match(acc["id"], today, bad))
    finally:
        lg.close()


def test_cash_forecast():
    """現金流預測：定期交易與指定帳戶的提醒會改變餘額；低於低水位時總覽提醒；轉帳兩邊都算到。"""
    lg = Ledger(sample=True)
    try:
        a = lg.api
        f = ok(a.cash_forecast(6))
        assert f["events"] and f["events"] == sorted(f["events"], key=lambda e: e["date"])
        assert all(e["date"] >= f["today"] for e in f["events"])
        recs = ok(a.recurring_list())["rows"]
        names = {e["title"] for e in f["events"]}
        assert {r["name"] for r in recs if r["active"]} <= names, (names, [r["name"] for r in recs])
        tr = next((r for r in recs if r["type"] == "transfer" and r["active"]), None)
        if tr:
            sides = {e["account"] for e in f["events"] if e["title"] == tr["name"]}
            assert len(sides) == 2, sides
        bank = next(x for x in f["accounts"] if x["kind"] == "asset" and x["events"])
        day = (dt.date.today() + dt.timedelta(days=20)).isoformat()
        ok(a.reminder_save({"title": "年繳保費", "kind": "insurance", "freq": "once", "date": day,
                            "amount": bank["start"] + 500000, "account_id": bank["id"]}))
        f2 = ok(a.cash_forecast(6))
        w = next(x for x in f2["warnings"] if x["id"] == bank["id"])
        assert w["negative"] and w["min_date"] >= day and w["min"] < 0
        ev = next(e for e in f2["events"] if e["title"] == "年繳保費")
        assert ev["amount"] < 0 and not ev["inflow"]
        assert any(x["kind"] == "forecast" and x["name"] == bank["name"] for x in ok(a.dashboard())["reminders"])
        # 不指定帳戶的提醒不計入
        ok(a.reminder_save({"title": "只提醒", "kind": "other", "freq": "once", "date": day, "amount": 99}))
        assert not any(e["title"] == "只提醒" for e in ok(a.cash_forecast(6))["events"])
        assert "0 以上" in err(a.set_forecast_low(-1))
        ok(a.set_forecast_low(2000000))
        assert ok(a.cash_forecast(3))["low"] == 2000000 and ok(a.cash_forecast(3))["warnings"]
        lg.run(check_books, lg.db, "forecast")
    finally:
        lg.close()


TINY_JPEG = ("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP////////////////////////////////////////////////////////////"
             "//////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")


def test_feedback_pdf():
    """意見回饋：可累積多則（附畫面），產生 PDF 後清單清空；PDF 結構正確；不碰使用者的剪貼簿。"""
    import base64
    import re
    import struct
    import zlib
    import desktop.api_tools as tools
    from core import pdfimages
    real, tools._copy_file = tools._copy_file, lambda path: False
    lg = Ledger(sample=True)
    try:
        a = lg.api

        def chunk(k, b):
            return struct.pack(">I", len(b)) + k + b + struct.pack(">I", zlib.crc32(k + b) & 0xffffffff)
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))
        shot = "data:image/png;base64," + base64.b64encode(png).decode()
        assert ok(a.feedback_items()) == [] and not os.path.exists(os.path.join(lg.dir, "意見回饋"))   # 只讀取不建立資料夾
        assert "寫下" in err(a.feedback_add({"note": " ", "tag": ""}))
        photo_only = ok(a.feedback_add({"note": "", "tag": "", "shot": shot}))          # 只貼照片也可以
        ok(a.feedback_remove(photo_only[0]["id"]))
        l1 = ok(a.feedback_add({"tag": "看不清楚", "note": "字太小", "page": "收支明細", "shot": shot}))
        l2 = ok(a.feedback_add({"tag": "", "note": "月結第 2 步不知道按哪裡", "page": "總覽", "shot": ""}))
        assert len(l1) == 1 and len(l2) == 2 and l2[0]["shot"] == shot and l2[1]["shot"] == ""
        l3 = ok(a.feedback_add({"tag": "其他", "note": "要刪掉的", "page": "", "shot": shot}))
        l4 = ok(a.feedback_remove(l3[2]["id"]))
        assert [x["note"] for x in l4] == ["字太小", "月結第 2 步不知道按哪裡"]
        assert not os.path.exists(os.path.join(lg.dir, "意見回饋", "待傳送", l3[2]["id"] + ".png"))
        d = ok(a.feedback_diag())
        assert d["version"] and d["vouchers"] > 0 and "windows" in d
        assert ok(a.feedback_capture()) == "" and "失敗" in ok(a.feedback_diag())["capture"]      # 測試沒有視窗：原因要留在診斷資訊
        jpg = "data:image/jpeg;base64," + TINY_JPEG
        assert pdfimages.jpeg_size(base64.b64decode(TINY_JPEG)) == (1, 1)
        r = ok(a.feedback_pdf([jpg, jpg, jpg], True))
        data = open(r["path"], "rb").read()
        assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF") and b"/Count 3" in data
        xref = int(re.search(rb"startxref\n(\d+)", data).group(1))
        offs = [int(x) for x in re.findall(rb"(\d{10}) 00000 n", data[xref:])]
        for n, o in enumerate(offs, start=1):          # 每個物件的位置都正確，PDF 閱讀程式才打得開
            assert data[o:o + 12].startswith(b"%d 0 obj" % n), n
        assert r["copied"] is False and ok(a.feedback_items()) == []
        assert not [f for f in os.listdir(os.path.join(lg.dir, "意見回饋", "待傳送")) if f.endswith(".png")]
        assert ok(a.feedback_copy(r["path"])) is False                       # 測試中不碰剪貼簿
        assert "找不到" in err(a.feedback_copy(os.path.join(lg.dir, "理財帳本.db")))
        r2 = ok(a.feedback_pdf([jpg], False))
        assert r2["path"] != r["path"] and os.path.exists(r2["path"])
        assert "沒有" in err(a.feedback_pdf([], True))
    finally:
        tools._copy_file = real
        lg.close()


def test_errors_are_messages_not_crashes():
    """帳務規則錯誤傳回訊息；程式錯誤傳回友善訊息並寫進錯誤紀錄.log。"""
    lg = Ledger(sample=True)
    try:
        assert "找不到" in err(lg.api.voucher(999999))
        r = lg.api.report_bs("not-a-date", "2026-01-01", "none")
        assert "__error__" in r
        if r.get("__bug__"):
            assert os.path.exists(os.path.join(lg.dir, "錯誤紀錄.log"))
    finally:
        lg.close()


if __name__ == "__main__":
    failed = 0
    for k, f in list(globals().items()):
        if k.startswith("test_") and callable(f):
            try:
                f()
                print("PASS", k, flush=True)
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print("FAIL", k, e, flush=True)
                failed += 1
    print("ALL PASSED" if not failed else f"FAILED {failed}")
    sys.exit(1 if failed else 0)
