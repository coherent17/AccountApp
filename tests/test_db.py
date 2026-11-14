import datetime as _dt
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.analytics import cash_flow, tax_summary  # noqa: E402
from app.database import SCHEMA_VERSION, Database, money_round, month_keys  # noqa: E402
from app.investments import Investments  # noqa: E402
from app.sample_data import load_sample_data  # noqa: E402

_CACHE = {}


def make():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "t.db"))
    load_sample_data(db)
    return db


def ranges(db):
    lo, hi = db.date_range()
    return [(lo, hi), (lo[:4] + "-01-01", lo[:4] + "-12-31"), (hi[:4] + "-01-01", hi),
            (hi[:4] + "-03-01", hi[:4] + "-06-30")]


def balanced(rows):
    return abs(sum(r["debit"] for r in rows) - sum(r["credit"] for r in rows)) < 0.05


def test_trial_balance_balances():
    db = make()
    for start, end in ranges(db):
        assert balanced(db.trial_balance(start, end)), (start, end)


def test_journal_entries_balanced():
    db = make()
    lo, hi = db.date_range()
    for e in db.journal(lo, hi):
        assert balanced(e["lines"]), e


def test_ledger_matches_balance():
    db = make()
    lo, hi = db.date_range()
    for acc in db.account_summaries():
        lg = db.ledger(acc["id"], lo, hi)
        assert abs(lg["closing"] - acc["balance"]) < 0.01, (acc["name"], lg["closing"], acc["balance"])


def test_bs_equals_networth():
    db = make()
    bs = db.balance_sheet("9999-12-31")
    assert abs(bs["net"] - db.net_worth()["net"]) < 0.01


def investment_accounts_match(db):
    inv = Investments(db)
    hold = inv.holdings()
    accs = {s["account_id"] for s in inv.list_securities(include_archived=True)}
    for a in db.account_summaries(include_archived=True):
        if a["id"] in accs:
            mv = sum(h["market_value"] for h in hold if h["account_id"] == a["id"])
            assert abs(a["balance"] - mv) < 1, (a["name"], a["balance"], mv)
    return True


def test_investment_account_equals_market_value():
    db = make()
    inv = Investments(db)
    assert investment_accounts_match(db)
    s = inv.period_summary(*db.date_range())
    assert s["realized"] != 0 and s["dividends"] > 0 and s["nhi"] > 0
    # 範例中有一筆以複式分錄買進的 0056
    assert any(e["kind"] == "jbuy" for e in inv.events())


def _plain_ledger():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "t.db"))
    bank = db.add_account("台銀活存", "asset", "銀行存款", opening_balance=100000,
                          opening_date="2026-01-01")
    st = db.add_account("短期投資", "asset", "短期投資", opening_date="2026-01-01")
    inv = Investments(db)
    sid = inv.add_security(st, "0050", "元大台灣50")
    return db, inv, bank, st, sid


def test_account_codes():
    db, inv, bank, st, sid = _plain_ledger()
    codes = db.account_codes()
    assert codes[bank] == "1101" and codes[st] == "1102"
    lt = db.add_account("長期投資", "asset", "長期投資", opening_date="2026-01-01")
    assert db.account_codes()[lt] == "1201"
    assert db.find_category("income", "薪資")["code"] == "4101"
    assert db.find_category("expense", "餐飲")["code"] == "5101"
    custom = db.add_account("備償專戶", "asset", "銀行存款", code="1150")
    assert db.account_codes()[custom] == "1150"
    for bad, why in (("1101", "已被使用"), ("2150", "開頭"), ("11a", "數字"), ("3101", "")):
        try:
            db.add_account("x", "asset", "現金", code=bad)
            raise AssertionError(bad)
        except ValueError as e:
            assert why in str(e), (bad, e)
    cid = db.add_category("顧問收入", "income", code="7105")
    assert db.get_category(cid)["code"] == "7105"
    try:
        db.add_category("顧問收入", "income")
        raise AssertionError("dup name")
    except ValueError:
        pass
    db.update_account(bank, code="1110")
    assert db.account_codes()[bank] == "1110"
    chart = [a["code"] for a in db.chart_of_accounts()]
    assert chart == sorted(chart) and len(chart) == len(set(chart))


def test_journal_linked_investment():
    db, inv, bank, st, sid = _plain_ledger()
    # 借 短期投資 10,000／貸 銀行存款 10,000（0050 100 股）
    j1 = db.add_journal("2026-02-01", "買進 0050", [
        {"account_id": st, "debit": 10000, "security_id": sid, "shares": 100},
        {"account_id": bank, "credit": 10000}])
    h = inv.holdings()[0]
    assert h["shares"] == 100 and h["cost"] == 10000 and h["unrealized"] == 0
    # 手動輸入市價 → 評價：借 短期投資／貸 未實現評價損益
    # 評價至預估淨售價：12,000 − 手續費 20（最低）− ETF 證交稅 12 ＝ 11,968
    inv.set_prices([(sid, 120)], "2026-03-31")
    h = inv.holdings()[0]
    assert h["market_value"] == 11968 and h["unrealized"] == 1968, h
    assert investment_accounts_match(db)
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 1968) < 0.01
    # 分錄賣出一半：借 銀行存款 6,500／貸 短期投資 6,500（系統依平均成本調整處分損益）
    db.add_journal("2026-04-10", "賣出 0050", [
        {"account_id": bank, "debit": 6500},
        {"account_id": st, "credit": 6500, "security_id": sid, "shares": 50}])
    h = inv.holdings()[0]
    assert h["shares"] == 50 and abs(h["cost"] - 5000) < 0.01
    assert investment_accounts_match(db)
    ps = inv.period_summary("2026-01-01", "2026-12-31")
    assert abs(ps["realized"] - 1500) < 0.01, ps
    assert abs(db.realized_totals("2026-01-01", "2026-12-31") - 1500) < 0.01
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 984) < 0.01
    assert balanced(db.trial_balance("2026-01-01", "2026-12-31"))
    for e in db.journal("2026-01-01", "2026-12-31"):
        assert balanced(e["lines"]), e
    # 自行列出處分損益的寫法，結果相同
    db2, inv2, bank2, st2, sid2 = _plain_ledger()
    db2.add_journal("2026-02-01", "買進", [
        {"account_id": st2, "debit": 10000, "security_id": sid2, "shares": 100},
        {"account_id": bank2, "credit": 10000}])
    db2.add_journal("2026-04-10", "賣出", [
        {"account_id": bank2, "debit": 6500},
        {"account_id": st2, "credit": 5000, "security_id": sid2, "shares": 50},
        {"special": "realized", "credit": 1500}])
    assert abs(inv2.period_summary("2026-01-01", "2026-12-31")["realized"] - 1500) < 0.01
    assert investment_accounts_match(db2)
    # 賣超過持股：拒絕且不留下資料
    n = len(db.query_transactions())
    try:
        db.add_journal("2026-05-01", "賣太多", [
            {"account_id": bank, "debit": 99999},
            {"account_id": st, "credit": 99999, "security_id": sid, "shares": 500}])
        raise AssertionError("oversell")
    except ValueError as e:
        assert "超過" in str(e)
    assert len(db.query_transactions()) == n
    # 作廢買進會造成之前的賣出超賣 → 拒絕
    try:
        db.void_transactions([j1], "test")
        raise AssertionError("void")
    except ValueError as e:
        assert "無法作廢" in str(e)
    assert not db.get_transaction(j1)["void"]
    # 標的與科目不符
    try:
        db.add_journal("2026-05-01", "x", [
            {"account_id": bank, "debit": 1, "security_id": sid, "shares": 1},
            {"account_id": st, "credit": 1}])
        raise AssertionError("mismatch")
    except ValueError:
        pass


def adjust_vouchers(db):
    return db._q("SELECT DISTINCT t.id, t.date, t.note FROM transactions t JOIN txn_lines l ON l.txn_id = t.id"
                 " WHERE t.void = 0 AND l.special = 'adjust'")


def test_trades_never_auto_value():
    db, inv, bank, st, sid = _plain_ledger()
    # 買賣價差很大也不產生評價分錄（回報案例：分錄買進後重新評價）
    inv.add_event(sid, "buy", "2026-02-01", shares=100, price=100, fee=20, cash_account_id=bank)
    db.add_journal("2026-02-05", "分錄買進", [
        {"account_id": st, "debit": 15000, "security_id": sid, "shares": 100},
        {"account_id": bank, "credit": 15000}])
    inv.add_event(sid, "stock_div", "2026-02-10", shares=20)
    inv.add_event(sid, "sell", "2026-02-20", shares=50, price=200, fee=20, tax=30, cash_account_id=bank)
    assert not adjust_vouchers(db), adjust_vouchers(db)
    h = inv.holdings()[0]
    assert h["price"] == 0 and h["unrealized"] == 0 and abs(h["market_value"] - h["cost"]) < 0.01
    assert investment_accounts_match(db)
    assert balanced(db.trial_balance("2026-01-01", "2026-12-31"))


def test_manual_valuation_on_chosen_date():
    db, inv, bank, st, sid = _plain_ledger()
    inv.add_event(sid, "buy", "2026-02-01", shares=100, price=100, cash_account_id=bank)
    inv.add_event(sid, "buy", "2026-05-01", shares=100, price=150, cash_account_id=bank)
    # 選擇過去的日期評價：以當時持股 100 股計算
    inv.set_prices([(sid, 130)], "2026-03-31")
    v = adjust_vouchers(db)
    assert [x["date"] for x in v] == ["2026-03-31"], v
    # 13,000 − 手續費 20 − 證交稅 13 ＝ 12,967
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 2967) < 0.01
    h = inv.holdings()[0]
    assert h["price"] == 130 and abs(h["market_value"] - 27967) < 0.01 and h["unrealized"] == 2967
    assert inv.holdings("2026-03-31")[0]["shares"] == 100
    assert investment_accounts_match(db)
    # 同一天重新評價取代先前市價
    inv.set_prices([(sid, 120)], "2026-03-31")
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 1968) < 0.01
    # 賣出迴轉所售股份的評價，剩餘持股不重新評價
    inv.add_event(sid, "sell", "2026-06-01", shares=100, price=200, cash_account_id=bank)
    assert abs(inv.holdings()[0]["unrealized"] - 984) < 0.01
    assert investment_accounts_match(db)
    # 刪除評價後，分錄一併消失
    e = next(x for x in inv.events(sid) if x["kind"] == "price")
    inv.delete_event(e["id"])
    assert not adjust_vouchers(db) and investment_accounts_match(db)
    assert balanced(db.trial_balance("2026-01-01", "2026-12-31"))


def test_migration_v3_removes_auto_valuation():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v3.db")
    db = Database(path)
    bank = db.add_account("銀行", "asset", "銀行存款", opening_balance=100000, opening_date="2026-01-01")
    st = db.add_account("短期投資", "asset", "短期投資", opening_date="2026-01-01")
    inv = Investments(db)
    sid = inv.add_security(st, "0050", "元大台灣50")
    inv.add_event(sid, "buy", "2026-02-01", shares=100, price=100, cash_account_id=bank)
    inv.add_event(sid, "buy", "2026-02-01", shares=100, price=100, cash_account_id=bank)
    inv.set_prices([(sid, 120)], "2026-03-31")
    # 舊版自動產生的評價傳票（已結帳期間）
    db.add_journal("2026-02-10", "元大台灣50 分錄買進後重新評價", [
        {"account_id": st, "credit": 1000}, {"special": "adjust", "debit": 1000}], source=f"inv:{sid}")
    buys = db._q("SELECT id FROM transactions WHERE source = ? AND date = '2026-02-01' ORDER BY id",
                 (f"inv:{sid}",))
    c = db.conn
    rid = c.execute("INSERT INTO reconciliations(account_id, statement_date, statement_balance, created_at)"
                    " VALUES (?, '2026-02-28', 0, '2026-03-01')", (bank,)).lastrowid
    c.execute("INSERT INTO recon_items VALUES (?, ?, ?)", (rid, buys[1]["id"], bank))
    c.execute("INSERT INTO attachments(txn_id, name, path, added_at) VALUES (?, 'a', 'a', 'x')",
              (buys[1]["id"],))
    db.set_setting("closed_until", "2026-02-28")
    tx = c.execute("SELECT COUNT(*) FROM transactions WHERE source = ''").fetchone()[0]
    cash = db.signed_balances()[bank]
    c.execute("PRAGMA user_version = 3")
    c.commit()
    db.close()
    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert os.path.exists(os.path.join(d, "v3_升級前備份_v3.db"))
    assert [x["date"] for x in adjust_vouchers(db)] == ["2026-03-31"]
    # 24,000 − 手續費 34 − 證交稅 24 ＝ 23,942，成本 20,000
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 3942) < 0.01
    assert investment_accounts_match(db)
    # 現金、一般傳票、結帳日、對帳勾選與附件都保留
    assert db.signed_balances()[bank] == cash
    assert db.conn.execute("SELECT COUNT(*) FROM transactions WHERE source = ''").fetchone()[0] == tx
    assert db.closed_until == "2026-02-28"
    ids = [r["id"] for r in db._q("SELECT id FROM transactions WHERE source = ? AND date = '2026-02-01'"
                                  " ORDER BY id", (f"inv:{sid}",))]
    assert len(ids) == 2
    assert [r["txn_id"] for r in db._q("SELECT txn_id FROM recon_items")] == [ids[1]]
    assert [r["txn_id"] for r in db._q("SELECT txn_id FROM attachments")] == [ids[1]]
    try:
        db.add_journal("2026-02-15", "x", [{"account_id": bank, "debit": 1}, {"account_id": st, "credit": 1}])
        raise AssertionError("closed")
    except ValueError as e:
        assert "已結帳" in str(e)
    db.close()
    assert Database(path).conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = '系統升級'").fetchone()[0] == 1


def _her_ledger():
    """回報案例：3715 定穎投控（股票，證交稅 0.3%）以複式分錄買進 1,000 股 @98，手續費 139 併入成本。"""
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "t.db"))
    bank = db.add_account("銀行存款-華南-活存 NT", "asset", "銀行存款", opening_balance=500000,
                          opening_date="2025-08-01", code="1115")
    st = db.add_account("短期投資-股票", "asset", "短期投資", opening_date="2025-08-01", code="1201")
    inv = Investments(db)
    sid = inv.add_security(st, "3715", "定穎投控")
    db.add_journal("2025-09-04", "買入 定穎投控", [
        {"account_id": st, "debit": 98139, "security_id": sid, "shares": 1000, "price": 98},
        {"account_id": bank, "credit": 98139}])
    return db, inv, bank, st, sid


def test_trade_costs_round_down():
    from app.investments import trade_costs
    stock = {"fee_rate": 0.001425, "fee_min": 20, "tax_rate": 0.003}
    assert trade_costs(stock, "buy", 1000, 98) == (139, 0)          # 139.65 → 139
    assert trade_costs(stock, "sell", 1000, 130.5) == (185, 391)    # 185.96 → 185，391.5 → 391
    assert trade_costs(dict(stock, tax_rate=0.001), "sell", 1000, 130.5) == (185, 130)
    assert trade_costs(stock, "buy", 10, 50) == (20, 0)              # 最低手續費
    assert trade_costs(dict(stock, fee_rate=0.000855), "buy", 1000, 98) == (83, 0)  # 6 折
    assert Investments.suggest_fees("sell", 1000, 50, "0056") == (71, 50)


def test_unrealized_includes_trade_costs():
    db, inv, bank, st, sid = _her_ledger()
    ev = inv.events(sid)[0]
    # 分錄記錄成交單價：交易紀錄顯示 98，差額 139 為手續費
    assert ev["kind"] == "jbuy" and ev["price"] == 98 and ev["fee"] == 139, ev
    inv.set_prices([(sid, 130.5)], "2026-11-12")
    h = inv.holdings()[0]
    # 回報的算法：預估淨售價 129,924（130,500 − 手續費 185 − 證交稅 391）− 成本 98,139 ＝ 31,785
    assert h["cost"] == 98139 and h["market_value"] == 129924 and h["unrealized"] == 31785, h
    assert abs(db.adjust_totals("2025-01-01", "2026-12-31") - 31785) < 0.01
    assert db.account_summaries()[1]["balance"] == 129924
    assert investment_accounts_match(db)
    # 分錄賣出 400 股 @135：實收 54,000 − 76 − 162 ＝ 53,762；已實現損益含買賣手續費與稅
    db.add_journal("2026-11-20", "賣出 定穎投控", [
        {"account_id": bank, "debit": 53762},
        {"account_id": st, "credit": 53762, "security_id": sid, "shares": 400, "price": 135}])
    sell = [e for e in inv.events(sid) if e["kind"] == "jsell"][0]
    assert sell["price"] == 135 and sell["tax"] == 162 and sell["fee"] == 76, sell
    ps = inv.period_summary("2026-01-01", "2026-12-31")
    assert abs(ps["realized"] - (53762 - 98139 * 0.4)) < 0.01, ps
    assert investment_accounts_match(db)
    assert balanced(db.trial_balance("2025-01-01", "2026-12-31"))
    # 迴轉時單價一併保留
    j = db.query_transactions(keyword="賣出 定穎投控")[0]["id"]
    rid = db.reverse_transaction(j, "2026-11-21")
    assert [ln["price"] for ln in db.get_lines(rid) if ln["security_id"]] == [135]


def test_security_rates():
    db, inv, bank, st, sid = _her_ledger()
    etf = inv.add_security(st, "0056", "元大高股息")
    assert inv.get_security(etf)["tax_rate"] == 0.001 and inv.get_security(sid)["tax_rate"] == 0.003
    inv.set_prices([(sid, 130.5)], "2026-11-12")
    # 改為 6 折手續費後，評價分錄依新費率重編：手續費 111
    inv.update_security(sid, "3715", "定穎投控", "", fee_rate=0.000855)
    h = next(x for x in inv.holdings() if x["id"] == sid)
    assert h["market_value"] == 130500 - 111 - 391, h
    assert investment_accounts_match(db)
    try:
        inv.update_security(sid, "3715", "定穎投控", "", tax_rate=3)
        raise AssertionError("rate")
    except ValueError:
        pass
    # 已結帳期間有評價時不可改費率，且不留下未完成的變更
    db.set_setting("closed_until", "2026-11-30")
    try:
        inv.update_security(sid, "3715", "定穎投控", "", fee_rate=0.001425)
        raise AssertionError("closed")
    except ValueError as e:
        assert "已結帳" in str(e)
    db.conn.commit()
    assert inv.get_security(sid)["fee_rate"] == 0.000855
    inv.update_security(sid, "3715", "定穎投控新名", "")   # 只改名稱不受影響
    assert inv.get_security(sid)["name"] == "定穎投控新名"


def test_migration_v4_to_v5():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v4.db")
    db = Database(path)
    bank = db.add_account("銀行", "asset", "銀行存款", opening_balance=500000, opening_date="2026-01-01")
    st = db.add_account("短期投資", "asset", "短期投資", opening_date="2026-01-01")
    inv = Investments(db)
    s1 = inv.add_security(st, "3715", "定穎投控")
    s2 = inv.add_security(st, "0050", "元大台灣50")
    db.add_journal("2026-02-01", "買入", [
        {"account_id": st, "debit": 98139, "security_id": s1, "shares": 1000},
        {"account_id": bank, "credit": 98139}])
    inv.add_event(s2, "buy", "2026-02-02", shares=100, price=100, fee=20, cash_account_id=bank)
    inv.set_prices([(s1, 130.5), (s2, 120)], "2026-03-31")
    db.set_json("journal_templates", [["我的範本", [["debit", "account:%d" % st, "", None],
                                                     ["credit", "account:%d" % bank, "", None]]]])
    db.set_setting("closed_until", "2026-03-31")
    cash = db.signed_balances()[bank]
    manual = db.conn.execute("SELECT COUNT(*) FROM transactions WHERE source = ''").fetchone()[0]
    db.close()
    c = sqlite3.connect(path)
    # 模擬第 4 版資料庫：沒有成交單價與費率欄位，評價為市價（未扣除賣出費用）
    c.executescript("""
        ALTER TABLE txn_lines DROP COLUMN price;
        ALTER TABLE securities DROP COLUMN fee_rate; ALTER TABLE securities DROP COLUMN fee_min;
        ALTER TABLE securities DROP COLUMN tax_rate;
        PRAGMA user_version = 4;""")
    c.commit()
    c.close()
    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert os.path.exists(os.path.join(d, "v4_升級前備份_v4.db"))
    inv = Investments(db)
    assert inv.get_security(s1)["tax_rate"] == 0.003 and inv.get_security(s2)["tax_rate"] == 0.001
    hs = {h["code"]: h for h in inv.holdings()}
    assert hs["3715"]["unrealized"] == 31785 and hs["0050"]["market_value"] == 12000 - 20 - 12, hs
    assert investment_accounts_match(db)
    assert db.signed_balances()[bank] == cash
    assert db.conn.execute("SELECT COUNT(*) FROM transactions WHERE source = ''").fetchone()[0] == manual
    assert db.closed_until == "2026-03-31"
    assert db.get_json("journal_templates")[0][0] == "我的範本"
    assert db.get_lines(db.query_transactions(keyword="買入")[0]["id"])[0]["price"] == 0
    assert balanced(db.trial_balance("2026-01-01", "2026-12-31"))


def test_export_sheet_selection_and_ledger():
    from openpyxl import load_workbook
    from app.exporter import SHEET_INFO, export_workbook
    db = make()
    lo, hi = db.date_range()
    d = tempfile.mkdtemp()
    full = export_workbook(db, os.path.join(d, "all.xlsx"), lo, hi)
    wb = load_workbook(full)
    assert wb.sheetnames.index("分類帳") == wb.sheetnames.index("日記簿") + 1
    assert set(wb.sheetnames) == {n for n, _ in SHEET_INFO}
    assert all(ws.sheet_state == "visible" for ws in wb.worksheets)
    # 分類帳：以公式重算每段餘額，必須與帳上期末餘額相符
    ws = wb["分類帳"]
    bal, blocks = {}, 0
    for row in ws.iter_rows(min_row=1):
        r = row[0].row
        g = ws.cell(r, 7).value
        if isinstance(g, (int, float)):
            bal[r] = g
        elif isinstance(g, str) and g.startswith("=G"):
            if "+" in g:
                prev = bal[r - 1]
                e, f = ws.cell(r, 5).value or 0, ws.cell(r, 6).value or 0
                bal[r] = prev + (e - f if "+E" in g else f - e)
            else:
                bal[r] = bal[int(g[2:])]
                closing = float(ws.cell(r, 8).value.split("-")[1].split(",")[0])
                assert abs(bal[r] - closing) < 0.01, (r, bal[r], closing)
                blocks += 1
    assert blocks == len([a for a in db.account_summaries(include_archived=True)
                          if db.ledger(a["id"], lo, hi)["rows"] or a["balance"]])
    # 只選部分報表：被引用的收支明細隱藏保留，其餘移除
    part = export_workbook(db, os.path.join(d, "part.xlsx"), lo, hi, ["收支損益表", "分類帳"])
    wb = load_workbook(part)
    assert wb.sheetnames == ["收支損益表", "收支明細", "分類帳"], wb.sheetnames
    assert wb["收支明細"].sheet_state == "hidden" and wb.active.title == "收支損益表"
    try:
        export_workbook(db, os.path.join(d, "none.xlsx"), lo, hi, [])
        raise AssertionError("empty")
    except ValueError:
        pass


def check_books(db, where=""):
    lo, hi = db.date_range()
    assert balanced(db.trial_balance(lo, hi)), where
    for e in db.journal(lo, hi):
        assert balanced(e["lines"]), (where, e["voucher"])
    assert investment_accounts_match(db), where
    for a in db.account_summaries(include_archived=True):
        assert abs(db.ledger(a["id"], "1900-01-01", "2999-12-31")["closing"] - a["balance"]) < 0.01, (where, a["name"])
    assert abs(db.balance_sheet("2999-12-31")["net"] - db.net_worth()["net"]) < 0.01, where
    assert abs(cash_flow(db, lo, hi)["check"]) < 0.05, where


def random_operations(seed, steps=60):
    """隨機操作帳本（收支、分錄買賣含單價、交易、評價、作廢、迴轉、修改、改費率、結帳），每步檢查帳務。"""
    import random
    rnd = random.Random(seed)
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "r.db"))
    inv = Investments(db)
    bank = db.add_account("銀行", "asset", "銀行存款", opening_balance=5_000_000, opening_date="2026-01-01")
    card = db.add_account("信用卡", "liability", "信用卡", opening_date="2026-01-01")
    st = db.add_account("短期投資-股票", "asset", "短期投資", opening_date="2026-01-01")
    etf = db.add_account("短期投資-ETF", "asset", "短期投資", opening_date="2026-01-01")
    secs = [inv.add_security(st, "2330", "台積電"), inv.add_security(st, "3715", "定穎投控"),
            inv.add_security(etf, "0050", "元大台灣50")]
    acc_of = {secs[0]: st, secs[1]: st, secs[2]: etf}
    cat_e = db.list_categories("expense")[0]["id"]
    cat_i = db.list_categories("income")[0]["id"]
    journals = []

    def day():
        lo = db.closed_until or "2026-01-01"
        base = _dt.date.fromisoformat(max(lo, "2026-01-01")) + _dt.timedelta(days=1)
        return (base + _dt.timedelta(days=rnd.randint(0, 200))).isoformat()

    for step in range(steps):
        op = rnd.choice(["exp", "inc", "jbuy", "jbuy", "jsell", "buy", "sell", "div", "sdiv", "price",
                         "price", "void", "reverse", "edit", "rate", "close"])
        try:
            sid = rnd.choice(secs)
            q = rnd.choice([100, 500, 1000, 1500])
            p = round(rnd.uniform(20, 900), 2)
            if op in ("exp", "inc"):
                db.add_transaction(type="expense" if op == "exp" else "income",
                                   account_id=rnd.choice([bank, card]), amount=rnd.randint(1, 50000),
                                   date=day(), category_id=cat_e if op == "exp" else cat_i, note=op)
            elif op == "jbuy":
                fee, _ = inv.fees_for(sid, "buy", q, p)
                amt = money_round(q * p + fee)
                journals.append(db.add_journal(day(), "分錄買進", [
                    {"account_id": acc_of[sid], "debit": amt, "security_id": sid, "shares": q,
                     "price": p if rnd.random() < .7 else 0},
                    {"account_id": bank, "credit": amt}]))
            elif op == "jsell":
                held = inv.replay(sid)["shares"]
                if held:
                    q = min(q, held)
                    fee, tax = inv.fees_for(sid, "sell", q, p)
                    amt = money_round(q * p - fee - tax)
                    journals.append(db.add_journal(day(), "分錄賣出", [
                        {"account_id": bank, "debit": amt},
                        {"account_id": acc_of[sid], "credit": amt, "security_id": sid, "shares": q, "price": p}]))
            elif op in ("buy", "sell"):
                fee, tax = inv.fees_for(sid, op, q, p)
                if op == "sell":
                    q = min(q, inv.replay(sid)["shares"]) or 0
                if q:
                    inv.add_event(sid, op, day(), shares=q, price=p, fee=fee, tax=tax, cash_account_id=bank)
            elif op == "div":
                inv.add_event(sid, "cash_div", day(), amount=rnd.randint(100, 30000), cash_account_id=bank)
            elif op == "sdiv":
                inv.add_event(sid, "stock_div", day(), shares=rnd.choice([10, 50]))
            elif op == "price":
                inv.set_prices([(sid, p)], day())
            elif op in ("void", "reverse", "edit") and journals:
                j = rnd.choice(journals)
                t = db.get_transaction(j)
                if op == "void":
                    if t["void"]:
                        db.unvoid_transaction(j)
                    else:
                        db.void_transactions([j], "隨機")
                elif op == "reverse" and not t["void"]:
                    db.reverse_transaction(j, day())
                elif op == "edit" and not t["void"]:
                    lines = [dict(ln) for ln in db.get_lines(j)]
                    db.update_journal(j, day(), "修改", lines)
            elif op == "rate":
                inv.update_security(sid, inv.get_security(sid)["code"], inv.get_security(sid)["name"], "",
                                    fee_rate=rnd.choice([0.001425, 0.000855, 0.0005]))
            elif op == "close" and rnd.random() < .3:
                db.set_setting("closed_until", (_dt.date.fromisoformat(day()) - _dt.timedelta(days=30)).isoformat())
        except ValueError:
            db.conn.rollback()   # 超賣、已結帳等：拒絕操作，帳務不應改變
        check_books(db, f"seed {seed} step {step} {op}")
    return db


def test_random_operations_keep_books_balanced():
    for seed in range(4):
        random_operations(seed, 45)


def test_random_operations_keep_codes():
    db = random_operations(7, 30)
    assert {s["code"] for s in Investments(db).list_securities()} == {"2330", "3715", "0050"}


def test_year_end_closing():
    db = make()
    lo, hi = db.date_range()
    y = int(lo[:4])
    start, end = f"{y}-01-01", f"{y}-12-31"
    before = {k: db.trial_balance(start, end) for k in ("tb",)}["tb"]
    inc = db.income_statement(start, end)
    eq = db.equity_statement(start, end)
    # 權益變動表：期初淨值＋各項變動＝期末淨值
    assert abs(sum(v for _, v in eq["rows"]) - eq["closing"]) < 0.01, eq
    assert abs(eq["closing"] - db.net_worth(end)["net"]) < 0.01
    made = db.close_year(y)
    assert len(made) == 1 and db.year_closings() == {y: made[0]} and db.closed_until == end
    # 結帳分錄：借貸平衡、本期損益＝綜合損益，且不改變任何報表金額
    lines = db.txn_lines_of(db.get_transaction(made[0]))
    assert balanced(lines)
    closing_line = next(ln for ln in lines if ln["code"] == "3201")
    assert abs((closing_line["credit"] - closing_line["debit"]) - inc["comprehensive"]) < 0.01
    assert db.trial_balance(start, end) == before
    assert db.income_statement(start, end) == inc
    assert any(e["id"] == made[0] for e in db.journal(start, end))
    assert not any(t["id"] == made[0] and (t["inc"] or t["exp"]) for t in db.query_transactions(start=end, end=end))
    check_books(db, "after closing")
    # 系統分錄不可修改、作廢、迴轉
    for fn in (lambda: db.void_transactions([made[0]]), lambda: db.reverse_transaction(made[0], hi)):
        try:
            fn()
            raise AssertionError("closing voucher changed")
        except ValueError as e:
            assert "結帳" in str(e)
    # 年度尚未結束不可結帳；重複結帳不再產生
    try:
        db.close_year(_dt.date.today().year)
        raise AssertionError("current year")
    except ValueError:
        pass
    assert db.close_year(y) == []
    # 解除結帳：結帳分錄作廢，可重新結帳
    db.set_closed_until("")
    assert db.year_closings() == {} and db.get_transaction(made[0])["void"]
    again = db.close_year(y)
    assert len(again) == 1 and again[0] != made[0]
    # 系統重編改變已結帳年度的損益時，結帳分錄依新金額重新結轉
    db.conn.execute("UPDATE txn_lines SET credit = credit + 100 WHERE txn_id = ? AND special = 'closing'",
                    (again[0],))
    db.refresh_year_closings()
    cur = db.year_closings()[y]
    assert cur != again[0] and db.closed_until == end
    assert balanced(db.txn_lines_of(db.get_transaction(cur)))


def test_six_column_trial_balance():
    db = make()
    lo, hi = db.date_range()
    mid = (_dt.date.fromisoformat(lo) + _dt.timedelta(days=100)).isoformat()
    for start, end in ranges(db) + [(mid, hi)]:
        rows = db.trial_balance(start, end)
        for a, b in (("open_debit", "open_credit"), ("period_debit", "period_credit"), ("debit", "credit")):
            assert abs(sum(r[a] for r in rows) - sum(r[b] for r in rows)) < 0.05, (start, end, a)
        for r in rows:
            net = r["open_debit"] - r["open_credit"] + r["period_debit"] - r["period_credit"]
            assert abs(net - (r["debit"] - r["credit"])) < 0.05, (start, end, r)
        nw = sum(r["debit"] - r["credit"] for r in rows if r["group"] in ("資產", "負債"))
        assert abs(nw - db.net_worth(end)["net"]) < 0.05


def test_rebuild_keeps_voucher_numbers_and_reconciliation():
    db, inv, bank, st, sid = _plain_ledger()
    e1 = inv.add_event(sid, "buy", "2026-02-01", shares=100, price=100, fee=20, cash_account_id=bank)
    inv.add_event(sid, "buy", "2026-03-01", shares=100, price=110, fee=20, cash_account_id=bank)
    inv.set_prices([(sid, 120)], "2026-03-31")
    ids = {t["date"]: t["id"] for t in db._q("SELECT id, date FROM transactions WHERE source = ?",
                                              (f"inv:{sid}",))}
    rid = db.conn.execute("INSERT INTO reconciliations(account_id, statement_date, statement_balance, created_at)"
                          " VALUES (?, '2026-03-31', 0, 'x')", (bank,)).lastrowid
    db.conn.execute("INSERT INTO recon_items VALUES (?, ?, ?)", (rid, ids["2026-03-01"], bank))
    db.conn.commit()
    # 在最前面補一筆交易、並改評價市價：之後的傳票號碼與對帳勾選都不變
    inv.add_event(sid, "buy", "2026-01-15", shares=50, price=90, fee=20, cash_account_id=bank)
    inv.set_prices([(sid, 125)], "2026-03-31")
    now = {t["date"]: t["id"] for t in db._q("SELECT id, date FROM transactions WHERE source = ?",
                                              (f"inv:{sid}",))}
    for d in ("2026-02-01", "2026-03-01", "2026-03-31"):
        assert now[d] == ids[d], (d, now[d], ids[d])
    assert "2026-01-15" in now and now["2026-01-15"] > max(ids.values())
    assert [r["txn_id"] for r in db._q("SELECT txn_id FROM recon_items")] == [ids["2026-03-01"]]
    # 刪除交易：該傳票消失，其餘號碼不變
    inv.delete_event(e1)
    left = {t["date"]: t["id"] for t in db._q("SELECT id, date FROM transactions WHERE source = ?",
                                               (f"inv:{sid}",))}
    assert "2026-02-01" not in left and left["2026-03-01"] == ids["2026-03-01"]
    assert investment_accounts_match(db)


def test_journal_linked_void_and_reverse():
    db, inv, bank, st, sid = _plain_ledger()
    j = db.add_journal("2026-02-01", "買進", [
        {"account_id": st, "debit": 10000, "security_id": sid, "shares": 100},
        {"account_id": bank, "credit": 10000}])
    inv.set_prices([(sid, 110)], "2026-02-28")
    db.void_transactions([j], "輸入錯誤")
    assert not inv.holdings()
    assert db.account_summaries()[1]["balance"] == 0
    db.unvoid_transaction(j)
    assert inv.holdings()[0]["market_value"] == 10969
    assert investment_accounts_match(db)
    db.reverse_transaction(j, "2026-03-15")
    assert not inv.holdings()
    assert investment_accounts_match(db)
    assert balanced(db.trial_balance("2026-01-01", "2026-12-31"))


def test_migration_v2_codes():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v2.db")
    db = Database(path)
    a1 = db.add_account("郵局", "asset", "銀行存款", opening_date="2026-01-01")
    a2 = db.add_account("房貸", "liability", "房屋貸款", opening_date="2026-01-01")
    db.close()
    c = sqlite3.connect(path)
    # 模擬第 2 版資料庫（沒有代號與投資連結欄位）
    c.executescript("""
        DROP INDEX IF EXISTS idx_lines_security;
        ALTER TABLE accounts DROP COLUMN code; ALTER TABLE categories DROP COLUMN code;
        ALTER TABLE txn_lines DROP COLUMN security_id; ALTER TABLE txn_lines DROP COLUMN shares;
        PRAGMA user_version = 2;""")
    c.commit()
    c.close()
    db = Database(path)
    assert db.account_codes() == {a1: "1101", a2: "2201"}
    assert db.find_category("expense", "餐飲")["code"] == "5101"
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    bak = os.path.join(d, "v2_升級前備份_v2.db")
    assert os.path.exists(bak) and Database.is_valid_ledger(bak)


def test_cash_flow_reconciles():
    db = make()
    for start, end in ranges(db):
        cf = cash_flow(db, start, end)
        assert abs(cf["check"]) < 0.05, (start, end, cf["check"])


def test_rate_change_keeps_balance():
    db = make()
    usd = next(a for a in db.list_accounts() if a["currency"] == "USD")
    bank = next(a for a in db.list_accounts() if a["name"] == "台銀活存")
    db.add_journal("2026-10-01", "換匯", [
        {"account_id": usd["id"], "debit": 32000}, {"account_id": bank["id"], "credit": 32000}])
    db.update_account(usd["id"], rate=33.5)
    for start, end in ranges(db):
        assert balanced(db.trial_balance(start, end)), (start, end)
        assert abs(cash_flow(db, start, end)["check"]) < 0.05


def test_void_and_reverse():
    db = make()
    acc = db.list_accounts()[0]["id"]
    cat = db.list_categories("expense")[0]["id"]
    before = db.account_summaries()[0]["balance"]
    tid = db.add_transaction(date="2026-10-01", type="expense", account_id=acc, amount=500, category_id=cat)
    assert db.account_summaries()[0]["balance"] == before - 500
    db.void_transactions([tid], "輸入錯誤")
    assert db.account_summaries()[0]["balance"] == before
    db.unvoid_transaction(tid)
    rid = db.reverse_transaction(tid, "2026-10-02")
    assert db.account_summaries()[0]["balance"] == before
    assert db.get_transaction(rid)["type"] == "journal"
    actions = [a["action"] for a in db.list_audit(tid)]
    assert "作廢" in actions and "取消作廢" in actions and "被迴轉" in actions


def test_closing_lock():
    db = make()
    acc = db.list_accounts()[0]["id"]
    cat = db.list_categories("expense")[0]["id"]
    tid = db.add_transaction(date="2026-01-10", type="expense", account_id=acc, amount=10, category_id=cat)
    db.set_setting("closed_until", "2026-06-30")
    for fn in (lambda: db.add_transaction(date="2026-01-01", type="expense", account_id=acc,
                                          amount=10, category_id=cat),
               lambda: db.void_transactions([tid])):
        try:
            fn()
            assert False
        except ValueError:
            pass
    db.reverse_transaction(tid, "2026-07-01")


def test_journal_validation():
    db = make()
    a = db.list_accounts()[0]["id"]
    c = db.list_categories("expense")[0]["id"]
    for bad in ([{"account_id": a, "debit": 100}, {"category_id": c, "credit": 90}],
                [{"category_id": c, "debit": 100}, {"category_id": c, "credit": 100}],
                [{"account_id": a, "debit": 100}]):
        try:
            db.add_journal("2026-10-01", "x", bad)
            assert False, bad
        except ValueError:
            pass


def test_recurring():
    db = make()
    acc = db.list_accounts()[0]["id"]
    cat = db.list_categories("expense")[0]["id"]
    rid = db.save_recurring(None, "房租", {"type": "expense", "account_id": acc, "amount": 100,
                                          "category_id": cat}, "monthly", 31, "2026-01-01")
    rec = next(r for r in db.list_recurring() if r["id"] == rid)
    dates = db.recurring_dates(rec, "2026-04-30")
    assert dates == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"], dates
    db.post_recurring(rec, dates[0])
    rec = next(r for r in db.list_recurring() if r["id"] == rid)
    assert db.recurring_dates(rec, "2026-04-30")[0] == "2026-02-28"


def test_reconciliation():
    db = make()
    post = next(a for a in db.list_accounts() if a["name"] == "郵局活儲")
    items = db.recon_candidates(post["id"], "2026-03-31")
    cleared = db.cleared_balance(post["id"]) + sum(i["effect"] for i in items)
    db.save_reconciliation(post["id"], "2026-03-31", cleared, [i["txn_id"] for i in items])
    assert abs(db.cleared_balance(post["id"]) - cleared) < 0.01
    assert db.recon_candidates(post["id"], "2026-03-31") == []


def test_tax_summary():
    db = make()
    ts = tax_summary(db, int(db.date_range()[1][:4]))
    tags = {t["tag"] for t in ts["incomes"]}
    assert {"interest", "dividend", "pension"} <= tags, tags


def test_import_template():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        return
    from app.importer import build_rows, do_import, find_header, guess_mapping, read_table, write_template
    db = make()
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.xlsx")
    write_template(p)
    rows = read_table(p)
    h = find_header(rows)
    m = guess_mapping(rows[h])
    items = build_rows(db, rows, h, m, db.list_accounts()[0]["id"])
    assert len(items) == 3 and not any(i["error"] for i in items), items
    n = len(db.query_transactions())
    ok, skipped = do_import(db, items)
    assert ok == 3 and len(db.query_transactions()) == n + 3


def test_migration_from_v1():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "old.db")
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL,
      category TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'TWD', rate REAL NOT NULL DEFAULT 1,
      opening_balance REAL NOT NULL DEFAULT 0, opening_date TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
      archived INTEGER NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, kind TEXT NOT NULL,
      budget REAL NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
      type TEXT NOT NULL CHECK (type IN ('income', 'expense', 'transfer', 'adjust')),
      account_id INTEGER NOT NULL REFERENCES accounts(id), to_account_id INTEGER REFERENCES accounts(id),
      amount REAL NOT NULL, to_amount REAL, category_id INTEGER REFERENCES categories(id),
      note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    INSERT INTO accounts(name, kind, category, opening_balance, opening_date) VALUES ('郵局', 'asset', '銀行存款', 1000, '2026-01-01');
    INSERT INTO categories(name, kind) VALUES ('利息', 'income');
    INSERT INTO categories(name, kind) VALUES ('餐飲', 'expense');
    INSERT INTO transactions(date, type, account_id, amount, category_id, note, created_at, updated_at)
      VALUES ('2026-02-01', 'expense', 1, 200, 2, '舊資料', 'x', 'x');
    PRAGMA user_version = 1;
    """)
    c.commit()
    c.close()
    db = Database(path)
    assert db.account_summaries()[0]["balance"] == 800
    assert db.query_transactions()[0]["note"] == "舊資料"
    db.add_journal("2026-03-01", "x", [{"account_id": 1, "debit": 50},
                                       {"category_id": 1, "credit": 50}])
    assert db.account_summaries()[0]["balance"] == 850
    assert db.find_category("expense", "健保補充保費")
    assert db.find_category("income", "利息")["tax_tag"] == "interest"


def test_data_persists_after_reopen():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "t.db")
    db = Database(path)
    acc = db.add_account("郵局", "asset", "銀行存款", opening_balance=1000, opening_date="2026-01-01")
    cat = db.list_categories("expense")[0]["id"]
    db.add_transaction(date="2026-02-01", type="expense", account_id=acc, amount=250, category_id=cat, note="測試")
    db.set_setting("owner_name", "媽媽")
    db.close()
    db2 = Database(path)
    assert db2.get_setting("owner_name") == "媽媽"
    assert db2.account_summaries()[0]["balance"] == 750
    assert db2.query_transactions()[0]["note"] == "測試"


def test_backup_restore():
    db = make()
    d = tempfile.mkdtemp()
    bk = os.path.join(d, "b.db")
    db.backup_to(bk)
    n = len(db.query_transactions())
    db.reset_all()
    assert len(db.query_transactions()) == 0
    db.restore_from(bk)
    assert len(db.query_transactions()) == n


def test_fresh_start_clears_sample():
    db = make()
    assert db.get_setting("sample_data") == "1"
    db.start_fresh()
    assert db.get_setting("sample_data") == "0"
    assert len(db.query_transactions()) == 0
    assert [a["name"] for a in db.list_accounts()] == ["現金", "銀行存款"]
    assert db.net_worth()["net"] == 0


def test_new_ledger_is_empty():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "n.db"))
    assert db.list_accounts(include_archived=True) == []
    assert db.query_transactions() == []


def test_month_keys():
    assert month_keys("2025-11-15", "2026-02-01") == ["2025-11", "2025-12", "2026-01", "2026-02"]


if __name__ == "__main__":
    failed = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            try:
                f()
                print("PASS", k)
            except Exception as e:  # noqa: BLE001
                import traceback
                failed += 1
                print("FAIL", k, e)
                traceback.print_exc()
    print("FAILED" if failed else "ALL PASSED", failed)
