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
    # 賣出不迴轉已認列的評價（v2.5.0）：評價仍為 1,968，留待下次市價評價調整
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 1968) < 0.01
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


def _feedback_1151115_ledger():
    """回饋 1151115 的強茂（2481）買賣：買 1,000 股 @65（手續費 92），賣 1,000 股 @85。"""
    db, inv, bank, st, _ = _plain_ledger()
    sid = inv.add_security(st, "2481", "強茂")
    db.add_journal("2025-09-03", "買入 強茂", [
        {"account_id": st, "debit": 65092, "security_id": sid, "shares": 1000, "price": 65},
        {"account_id": bank, "credit": 65092}])
    return db, inv, bank, st, sid


def test_journal_sell_fee_and_tax_from_net_proceeds():
    """Q1：分錄賣出的手續費／稅＝成交金額－淨價款（貸記投資科目＋處分投資損益），不是成交金額－成本。"""
    db, inv, bank, st, sid = _feedback_1151115_ledger()
    db.add_journal("2026-01-15", "賣出 強茂", [
        {"account_id": bank, "debit": 84624},
        {"account_id": st, "credit": 65092, "security_id": sid, "shares": 1000, "price": 85},
        {"special": "realized", "credit": 19532}])
    sell = next(e for e in inv.events(sid) if e["kind"] == "jsell")
    assert (sell["fee"], sell["tax"]) == (121, 255), sell
    buy = next(e for e in inv.events(sid) if e["kind"] == "jbuy")
    assert (buy["fee"], buy["tax"]) == (92, 0), buy
    # Q2：已實現損益含股數
    row = inv.period_summary("2026-01-01", "2026-12-31")["realized_rows"][0]
    assert row["shares"] == 1000 and abs(row["proceeds"] - 84624) < 0.01 and abs(row["gain"] - 19532) < 0.01
    assert abs(row["cost"] - 65092) < 0.01
    # 分錄已依成本貸記，系統不需要任何調整傳票
    assert not db._q("SELECT id FROM transactions WHERE source LIKE 'inv:%'")
    # 只貸記投資科目淨價款（不另列處分損益）的寫法，手續費／稅一樣是 121＋255
    db2, inv2, bank2, st2, sid2 = _feedback_1151115_ledger()
    db2.add_journal("2026-01-15", "賣出 強茂", [
        {"account_id": bank2, "debit": 84624},
        {"account_id": st2, "credit": 84624, "security_id": sid2, "shares": 1000, "price": 85}])
    sell = next(e for e in inv2.events(sid2) if e["kind"] == "jsell")
    assert (sell["fee"], sell["tax"]) == (121, 255), sell
    assert abs(inv2.period_summary("2026-01-01", "2026-12-31")["realized"] - 19532) < 0.01
    assert investment_accounts_match(db2)


def test_sale_keeps_valuation_until_next_valuation():
    """Q3：賣出不產生迴轉未實現評價損益的傳票；下次市價評價時再一併調整，全數賣出的評價歸零。"""
    db, inv, bank, st, sid = _feedback_1151115_ledger()
    db.add_journal("2025-09-04", "買入 強茂", [
        {"account_id": st, "debit": 65092, "security_id": sid, "shares": 1000, "price": 65},
        {"account_id": bank, "credit": 65092}])
    inv.set_prices([(sid, 70)], "2025-12-31")
    # 2,000 股 × 70 ＝ 140,000 − 手續費 199 − 證交稅 420 − 成本 130,184 ＝ 9,197
    assert abs(db.adjust_totals("2025-01-01", "2025-12-31") - 9197) < 0.01
    db.add_journal("2026-01-15", "賣出 強茂", [
        {"account_id": bank, "debit": 84624},
        {"account_id": st, "credit": 65092, "security_id": sid, "shares": 1000, "price": 85},
        {"special": "realized", "credit": 19532}])
    assert not db._q("SELECT id FROM transactions WHERE source LIKE 'inv:%' AND date >= '2026-01-01'")
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31")) < 0.01
    h = inv.holdings()[0]
    assert h["shares"] == 1000 and abs(h["unrealized"] - 9197) < 0.01   # 尚未重新評價
    assert investment_accounts_match(db)
    assert abs(db.realized_totals("2026-01-01", "2026-12-31") - 19532) < 0.01
    # 下次評價：剩餘 1,000 股 × 80 − 手續費 114 − 證交稅 240 − 成本 65,092 ＝ 14,554，差額 5,357 記入評價損益
    inv.set_prices([(sid, 80)], "2026-03-31")
    assert abs(inv.holdings()[0]["unrealized"] - 14554) < 0.01
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - (14554 - 9197)) < 0.01
    # 全數賣出後仍保留評價調整，持股表與投資科目一致；市價評價時歸零
    db.add_journal("2026-04-15", "賣出 強茂", [
        {"account_id": bank, "debit": 90000},
        {"account_id": st, "credit": 65092, "security_id": sid, "shares": 1000},
        {"special": "realized", "credit": 24908}])
    h = inv.holdings()
    assert len(h) == 1 and h[0]["shares"] == 0 and abs(h[0]["market_value"] - 14554) < 0.01
    assert investment_accounts_match(db)
    inv.add_event(sid, "price", "2026-06-30", price=inv.last_price(sid), note="已全數賣出，剩餘評價歸零")
    assert not inv.holdings() and investment_accounts_match(db)
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") + 9197) < 0.01
    assert abs(next(a for a in db.account_summaries() if a["id"] == st)["balance"]) < 0.01
    check_books(db)


def test_dividend_journal_linked_to_security():
    """Q4：複式分錄的股利科目可連結標的、股數與每股股利，計入該標的股利。"""
    db, inv, bank, st, sid = _plain_ledger()
    sid56 = inv.add_security(st, "0056", "元大高股息")
    fee = db.find_category("expense", "郵電費") or db.list_categories("expense")[0]
    div = db.find_category("income", "股利")
    j = db.add_journal("2025-11-14", "0056 配息", [
        {"account_id": bank, "debit": 4320},
        {"category_id": fee["id"], "debit": 10},
        {"category_id": div["id"], "credit": 4330, "security_id": sid56, "shares": 2165, "price": 2}])
    ev = [e for e in inv.events(sid56) if e["kind"] == "jdiv"]
    assert len(ev) == 1 and ev[0]["amount"] == 4330 and ev[0]["shares"] == 2165 and ev[0]["price"] == 2, ev
    assert inv.period_summary("2025-01-01", "2025-12-31")["dividends"] == 4330
    assert db.income_expense_totals("2025-01-01", "2025-12-31")["income"] == 4330   # 不重複入帳
    assert not db._q("SELECT id FROM transactions WHERE source LIKE 'inv:%'")
    assert not inv.holdings()                                   # 股利不影響持股
    t = db.get_transaction(j)
    assert any(ln.get("security_id") == sid56 and ln["shares"] == 2165 for ln in db.txn_lines_of(t))
    # 作廢後不計入；迴轉產生反向股利
    db.void_transactions([j], "test")
    assert inv.period_summary("2025-01-01", "2025-12-31")["dividends"] == 0
    db.unvoid_transaction(j)
    db.reverse_transaction(j, "2025-12-01")
    assert inv.period_summary("2025-01-01", "2025-12-31")["dividends"] == 0
    # 費用科目不可連結標的
    try:
        db.add_journal("2025-11-20", "x", [
            {"account_id": bank, "credit": 10},
            {"category_id": fee["id"], "debit": 10, "security_id": sid56, "shares": 1}])
        raise AssertionError("expense link")
    except ValueError as e:
        assert "不符" in str(e)
    check_books(db)


def test_migration_v5_drops_sale_reversals():
    """v6 升級：舊版在賣出時產生的「迴轉未實現評價損益」傳票被移除，帳與明細一致。"""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v5.db")
    db = Database(path)
    bank = db.add_account("銀行", "asset", "銀行存款", opening_balance=200000, opening_date="2025-01-01")
    st = db.add_account("短期投資", "asset", "短期投資", opening_date="2025-01-01")
    inv = Investments(db)
    sid = inv.add_security(st, "1717", "長興")
    db.add_journal("2025-09-03", "買入 長興", [
        {"account_id": st, "debit": 92000, "security_id": sid, "shares": 2000},
        {"account_id": bank, "credit": 92000}])
    inv.set_prices([(sid, 47)], "2025-12-31")
    sale = db.add_journal("2026-01-15", "賣出 長興", [
        {"account_id": bank, "debit": 59237},
        {"account_id": st, "credit": 46000, "security_id": sid, "shares": 1000},
        {"special": "realized", "credit": 13237}])
    adj = db.adjust_totals("2025-01-01", "2025-12-31")
    # 舊版（v5）會在賣出日產生的迴轉傳票
    rid = db.add_journal("2026-01-15", f"長興 分錄賣出：迴轉未實現評價損益，並依平均成本調整處分投資損益（V{sale:06d}）",
                         [{"account_id": st, "credit": adj / 2}, {"special": "adjust", "debit": adj / 2}],
                         source=f"inv:{sid}")
    db.conn.execute("INSERT INTO attachments(txn_id, name, path, added_at) VALUES (?, 'a', 'a', 'x')", (sale,))
    db.set_setting("closed_until", "2025-12-31")
    db.conn.execute("PRAGMA user_version = 5")
    db.conn.commit()
    db.close()
    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert os.path.exists(os.path.join(d, "v5_升級前備份_v5.db"))
    assert not db.get_transaction(rid)
    assert not db._q("SELECT id FROM transactions WHERE source LIKE 'inv:%' AND date >= '2026-01-01'")
    assert abs(db.adjust_totals("2025-01-01", "2025-12-31") - adj) < 0.01      # 已結帳年度的評價不變
    assert db.get_transaction(sale) and db._q("SELECT 1 FROM attachments WHERE txn_id = ?", (sale,))
    assert db.get_setting("closed_until") == "2025-12-31"
    check_books(db)


def _feedback2_ledger():
    """回饋 1151115-2 的長興（1717）：兩次各買 1,000 股（46,065、46,716），賣出時依她自己的成本 46,065 貸記。"""
    db, inv, bank, st, _ = _plain_ledger()
    sid = inv.add_security(st, "1717", "長興")
    db.add_journal("2025-09-03", "買入 長興", [
        {"account_id": st, "debit": 46065, "security_id": sid, "shares": 1000},
        {"account_id": bank, "credit": 46065}])
    db.add_journal("2025-09-04", "買入 長興", [
        {"account_id": st, "debit": 46716, "security_id": sid, "shares": 1000},
        {"account_id": bank, "credit": 46716}])
    return db, inv, bank, st, sid


def _her_sale(db, bank, st, sid, date="2026-01-15", credit=46065, gain=13172):
    return db.add_journal(date, "賣出 長興", [
        {"account_id": bank, "debit": credit + gain},
        {"account_id": st, "credit": credit, "security_id": sid, "shares": 1000},
        {"special": "realized", "credit": gain}])


def test_journal_sell_with_booked_gain_creates_no_voucher():
    """Q6：分錄已列處分投資損益時，賣出不產生任何系統傳票（V000094）；出售成本以她貸記的金額為準。"""
    db, inv, bank, st, sid = _feedback2_ledger()
    _her_sale(db, bank, st, sid)
    assert not db._q("SELECT id FROM transactions WHERE source LIKE 'inv:%'")
    h = inv.holdings()[0]
    assert h["shares"] == 1000 and h["cost"] == 46716 and h["market_value"] == 46716, h
    assert investment_accounts_match(db)
    assert abs(db.realized_totals("2026-01-01", "2026-12-31") - 13172) < 0.01
    row = inv.period_summary("2026-01-01", "2026-12-31")["realized_rows"][0]
    assert row["cost"] == 46065 and row["shares"] == 1000 and abs(row["gain"] - 13172) < 0.01
    # 第二次賣出時她多扣了成本：全數賣出後剩 -284 的成本差額，持股表保留這一列，市價評價時轉列處分損益
    _her_sale(db, bank, st, sid, "2026-02-10", credit=47000, gain=10000)
    assert not db._q("SELECT id FROM transactions WHERE source LIKE 'inv:%'")
    h = inv.holdings()
    assert len(h) == 1 and h[0]["shares"] == 0 and abs(h[0]["market_value"] + 284) < 0.01, h
    assert investment_accounts_match(db)
    inv.add_event(sid, "price", "2026-03-31", price=50, note="已全數賣出，剩餘評價歸零")
    assert not inv.holdings() and investment_accounts_match(db)
    assert abs(db.realized_totals("2026-01-01", "2026-12-31") - (13172 + 10000 + 284)) < 0.01
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31")) < 0.01
    check_books(db)


def test_journal_sell_without_gain_line_still_splits_cost():
    """只貸記淨價款、未列處分損益的舊寫法：仍依平均成本拆出處分損益，投資科目才會正確。"""
    db, inv, bank, st, sid = _feedback2_ledger()
    db.add_journal("2026-01-15", "賣出 長興", [
        {"account_id": bank, "debit": 59237},
        {"account_id": st, "credit": 59237, "security_id": sid, "shares": 1000}])
    h = inv.holdings()[0]
    assert abs(h["cost"] - 46390.5) < 0.01 and investment_accounts_match(db)
    assert abs(db.realized_totals("2026-01-01", "2026-12-31") - (59237 - 46390.5)) < 0.01
    # 這種傳票無法單獨刪除，訊息說明如何改寫分錄
    tid = db._q1("SELECT id FROM transactions WHERE source LIKE 'inv:%'")["id"]
    try:
        inv.delete_vouchers([tid])
        raise AssertionError("delete")
    except ValueError as e:
        assert "處分投資損益" in str(e)
    assert db.get_transaction(tid)


def test_delete_system_vouchers():
    """Q6：收支明細可刪除投資管理自動產生的傳票（一併刪除產生它的交易，之後的分錄自動重算）。"""
    db, inv, bank, st, sid = _feedback2_ledger()
    inv.set_prices([(sid, 47)], "2025-12-31")
    inv.set_prices([(sid, 50)], "2026-03-31")
    v = adjust_vouchers(db)
    assert len(v) == 2
    n_events = len(db._q("SELECT id FROM sec_events"))
    assert [e["date"] for e in inv.voucher_events(v[0]["id"])] == ["2025-12-31"]
    assert inv.delete_vouchers([v[0]["id"]]) == 1
    assert len(db._q("SELECT id FROM sec_events")) == n_events - 1
    left = adjust_vouchers(db)
    assert [x["date"] for x in left] == ["2026-03-31"] and left[0]["id"] == v[1]["id"]   # 傳票號碼不變
    assert investment_accounts_match(db)
    assert any(a["action"] == "刪除投資交易" for a in db._q("SELECT action FROM audit_log"))
    # 投資管理的買進：刪除傳票會造成之後賣出超賣 → 拒絕，資料不變
    inv.add_event(sid, "buy", "2026-04-01", shares=100, price=50, cash_account_id=bank)
    db.add_journal("2026-05-01", "賣出", [
        {"account_id": bank, "debit": 100000},
        {"account_id": st, "credit": 97000, "security_id": sid, "shares": 2100},
        {"special": "realized", "credit": 3000}])
    buy = db._q1("SELECT id FROM transactions WHERE source LIKE 'inv:%' AND date = '2026-04-01'")["id"]
    try:
        inv.delete_vouchers([buy])
        raise AssertionError("oversell")
    except ValueError as e:
        assert "超過持股" in str(e)
    assert db.get_transaction(buy) and len(db._q("SELECT id FROM sec_events")) == n_events
    # 已結帳期間不可刪除
    db.set_setting("closed_until", "2026-03-31")
    try:
        inv.delete_vouchers([left[0]["id"]])
        raise AssertionError("closed")
    except ValueError:
        pass
    check_books(db)


def test_migration_v6_drops_journal_sell_adjustments():
    """v7 升級：舊版在分錄賣出時產生的「依平均成本調整處分投資損益」傳票（V000094）被移除。"""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v6.db")
    db = Database(path)
    bank = db.add_account("銀行", "asset", "銀行存款", opening_balance=200000, opening_date="2025-01-01")
    st = db.add_account("短期投資", "asset", "短期投資", opening_date="2025-01-01")
    inv = Investments(db)
    sid = inv.add_security(st, "1717", "長興")
    for date, amt in (("2025-09-03", 46065), ("2025-09-04", 46716)):
        db.add_journal(date, "買入 長興", [
            {"account_id": st, "debit": amt, "security_id": sid, "shares": 1000},
            {"account_id": bank, "credit": amt}])
    sale = _her_sale(db, bank, st, sid)
    # 舊版（v6）產生的調整傳票：借 處分投資損益 325.50／貸 短期投資 325.50
    rid = db.add_journal("2026-01-15", f"長興 分錄賣出：依平均成本調整處分投資損益（V{sale:06d}）",
                         [{"account_id": st, "credit": 325.5}, {"special": "realized", "debit": 325.5}],
                         source=f"inv:{sid}")
    db.conn.execute("PRAGMA user_version = 6")
    db.conn.commit()
    db.close()
    db = Database(path)
    inv = Investments(db)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert os.path.exists(os.path.join(d, "v6_升級前備份_v6.db"))
    assert not db.get_transaction(rid) and db.get_transaction(sale)
    assert not db._q("SELECT id FROM transactions WHERE source LIKE 'inv:%'")
    assert inv.holdings()[0]["cost"] == 46716 and investment_accounts_match(db)
    assert abs(db.realized_totals("2026-01-01", "2026-12-31") - 13172) < 0.01
    check_books(db)


def test_valuations_share_one_voucher_per_day():
    """1151121 Q8：同一天的市價評價，所有標的合併在同一張傳票（每行備註為標的與市價）。"""
    db, inv, bank, st, sid = _plain_ledger()
    s2 = inv.add_security(st, "2330", "台積電")
    s3 = inv.add_security(st, "0056", "元大高股息")
    for x, price in ((sid, 50), (s2, 900), (s3, 35)):
        inv.add_event(x, "buy", "2026-02-01", shares=1000, price=price, cash_account_id=bank)
    inv.set_prices([(sid, 55), (s2, 1000), (s3, 36)], "2026-03-31")
    vals = db._q("SELECT * FROM transactions WHERE source = 'inv:val'")
    assert len(vals) == 1 and vals[0]["date"] == "2026-03-31" and "3 檔" in vals[0]["note"], vals
    memos = {ln["memo"] for ln in db.get_lines(vals[0]["id"])}
    assert any("台積電" in m for m in memos) and any("元大高股息" in m for m in memos), memos
    assert investment_accounts_match(db) and balanced(db.get_lines(vals[0]["id"]))
    unreal = sum(h["unrealized"] for h in inv.holdings())
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - unreal) < 0.01
    # 之後只改一檔的市價：同一張傳票、號碼不變
    inv.set_prices([(s2, 1010)], "2026-03-31")
    again = db._q("SELECT * FROM transactions WHERE source = 'inv:val'")
    assert [v["id"] for v in again] == [vals[0]["id"]] and investment_accounts_match(db)
    # 另一天的評價是另一張傳票
    inv.set_prices([(sid, 60)], "2026-04-30")
    assert len(db._q("SELECT id FROM transactions WHERE source = 'inv:val'")) == 2
    # 刪除合併傳票＝刪除當天所有標的的市價評價
    assert inv.delete_vouchers([vals[0]["id"]]) == 3
    assert not db._q("SELECT id FROM sec_events WHERE kind = 'price' AND date = '2026-03-31'")
    assert investment_accounts_match(db)
    check_books(db)


def test_migration_v7_combines_valuations_and_types():
    """v8 升級：v2.6.0 帳本中各標的分開的評價傳票合併為一張；既有標的依費率歸入類型。"""
    import shutil
    d = tempfile.mkdtemp()
    path = os.path.join(d, "理財帳本.db")
    shutil.copy(os.path.join(FIXTURES, "ledger_v2.6.0.db"), path)
    old = sqlite3.connect(path)
    before = old.execute("SELECT id FROM transactions WHERE source LIKE 'inv:%' AND date = '2025-11-28'").fetchall()
    old.close()
    assert len(before) == 3, before
    db = Database(path)
    inv = Investments(db)
    vals = db._q("SELECT id, source FROM transactions WHERE source LIKE 'inv:%' AND date = '2025-11-28'")
    assert len(vals) == 1 and vals[0]["source"] == "inv:val" and vals[0]["id"] == min(r[0] for r in before)
    types = {s["code"]: s["type_name"] for s in inv.list_securities(include_archived=True)}
    assert types["3715"] == "股票" and types["0050"] == "ETF", types
    assert investment_accounts_match(db)
    check_books(db)


def test_security_types_editable():
    """1151121 Q3／Q4：類型可新增、修改；屬於該類型的標的改用新費率，評價依新費率重算。"""
    db, inv, bank, st, sid = _plain_ledger()
    s2 = inv.add_security(st, "2330", "台積電", type_name="股票")
    inv.add_event(s2, "buy", "2026-02-01", shares=1000, price=100, cash_account_id=bank)
    inv.set_prices([(s2, 130.5)], "2026-03-31")
    assert [t["name"] for t in inv.security_types()] == ["股票", "ETF", "債券 ETF"]
    rows = [dict(t, old=t["name"]) for t in inv.security_types()]
    rows[0].update(name="股票（6 折）", fee_rate=0.000855)
    rows.append({"name": "美股", "old": "", "fee_rate": 0.001, "fee_min": 0, "tax_rate": 0})
    assert inv.save_security_types(rows) == []
    sec = inv.get_security(s2)
    assert sec["type_name"] == "股票（6 折）" and sec["fee_rate"] == 0.000855, dict(sec)
    # 130,500 − 手續費 111（6 折）− 證交稅 391
    assert inv.holdings()[0]["market_value"] == 130500 - 111 - 391
    assert investment_accounts_match(db)
    assert [t["name"] for t in inv.security_types()][-1] == "美股"
    # 刪除類型：標的改為自訂，費率保留
    inv.save_security_types([dict(t, old=t["name"]) for t in inv.security_types() if t["name"] != "股票（6 折）"])
    sec = inv.get_security(s2)
    assert sec["type_name"] == "" and sec["fee_rate"] == 0.000855
    for bad in ([{"name": "", "old": "", "fee_rate": 0, "fee_min": 0, "tax_rate": 0}],
                [{"name": "A", "old": "", "fee_rate": 0, "fee_min": 0, "tax_rate": 0}] * 2,
                [{"name": "A", "old": "", "fee_rate": 0.5, "fee_min": 0, "tax_rate": 0}]):
        try:
            inv.save_security_types(bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_journal_foreign_currency_original_amount():
    """1151121 Q7：複式分錄的外幣科目可輸入原幣金額（匯率＝本位幣÷原幣），原幣累計到科目原幣餘額。"""
    db, inv, bank, st, sid = _plain_ledger()
    jpy = db.add_account("台銀活存 JPY", "asset", "外幣存款", currency="JPY", rate=0.21,
                         opening_balance=10000, opening_date="2026-01-01")
    interest = db.find_category("income", "利息") or db.list_categories("income")[0]
    db.add_journal("2026-02-22", "JPY 活存利息", [
        {"account_id": jpy, "debit": 105.5, "orig": 500},
        {"category_id": interest["id"], "credit": 105.5}])
    acc = next(a for a in db.account_summaries() if a["id"] == jpy)
    assert abs(acc["balance"] - 10500) < 0.01, acc
    check_books(db)


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
    # 賣出不迴轉評價（v2.5.0）：已認列的 1,968 留在帳上，下次市價評價時一併調整
    inv.add_event(sid, "sell", "2026-06-01", shares=100, price=200, cash_account_id=bank)
    assert abs(inv.holdings()[0]["unrealized"] - 1968) < 0.01
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 1968) < 0.01
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
    cat_div = db.find_category("income", "股利")["id"]
    journals = []

    def day():
        lo = db.closed_until or "2026-01-01"
        base = _dt.date.fromisoformat(max(lo, "2026-01-01")) + _dt.timedelta(days=1)
        return (base + _dt.timedelta(days=rnd.randint(0, 200))).isoformat()

    for step in range(steps):
        op = rnd.choice(["exp", "inc", "jbuy", "jbuy", "jsell", "jsell", "buy", "sell", "div", "jdiv", "sdiv",
                         "price", "price", "void", "reverse", "edit", "rate", "close"])
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
                    q = held if rnd.random() < .3 else min(q, held)   # 有時全數賣出
                    fee, tax = inv.fees_for(sid, "sell", q, p)
                    amt = money_round(q * p - fee - tax)
                    journals.append(db.add_journal(day(), "分錄賣出", [
                        {"account_id": bank, "debit": amt},
                        {"account_id": acc_of[sid], "credit": amt, "security_id": sid, "shares": q, "price": p}]))
            elif op == "jdiv":
                unit = rnd.choice([0.5, 1.2, 2.0])
                journals.append(db.add_journal(day(), "分錄股利", [
                    {"account_id": bank, "debit": money_round(q * unit)},
                    {"category_id": cat_div, "credit": money_round(q * unit), "security_id": sid, "shares": q,
                     "price": unit}]))
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
    ids = {t["date"]: t["id"] for t in db._q("SELECT id, date FROM transactions WHERE source LIKE 'inv:%'")}
    rid = db.conn.execute("INSERT INTO reconciliations(account_id, statement_date, statement_balance, created_at)"
                          " VALUES (?, '2026-03-31', 0, 'x')", (bank,)).lastrowid
    db.conn.execute("INSERT INTO recon_items VALUES (?, ?, ?)", (rid, ids["2026-03-01"], bank))
    db.conn.commit()
    # 在最前面補一筆交易、並改評價市價：之後的傳票號碼與對帳勾選都不變
    inv.add_event(sid, "buy", "2026-01-15", shares=50, price=90, fee=20, cash_account_id=bank)
    inv.set_prices([(sid, 125)], "2026-03-31")
    now = {t["date"]: t["id"] for t in db._q("SELECT id, date FROM transactions WHERE source LIKE 'inv:%'")}
    for d in ("2026-02-01", "2026-03-01", "2026-03-31"):
        assert now[d] == ids[d], (d, now[d], ids[d])
    assert "2026-01-15" in now and now["2026-01-15"] > max(ids.values())
    assert [r["txn_id"] for r in db._q("SELECT txn_id FROM recon_items")] == [ids["2026-03-01"]]
    # 刪除交易：該傳票消失，其餘號碼不變
    inv.delete_event(e1)
    left = {t["date"]: t["id"] for t in db._q("SELECT id, date FROM transactions WHERE source LIKE 'inv:%'")}
    assert "2026-02-01" not in left and left["2026-03-01"] == ids["2026-03-01"]
    assert investment_accounts_match(db)


FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
# 經她要求、可以讓投資科目餘額改變的升級（其他帳務都必須完全相同）
APPROVED_INVESTMENT_CHANGES = {3: "v4 買賣不再自動評價", 4: "v5 評價改以預估淨售價",
                               5: "v6 賣出不再迴轉未實現評價損益",
                               6: "v7 分錄已列處分損益時賣出不產生系統分錄"}


def old_ledgers():
    return sorted(f for f in os.listdir(FIXTURES) if f.startswith("ledger_v") and f.endswith(".db"))


def test_old_version_ledgers_load():
    """每個已發行版本建立的帳本，用目前程式開啟後帳務都不可遺失（tools/make_fixtures.py 產生）。"""
    import json
    import shutil
    sys.path.insert(0, FIXTURES)
    import ledger_tools
    files = old_ledgers()
    assert len(files) >= 3, files
    for name in files:
        old = json.load(open(os.path.join(FIXTURES, name[:-3] + ".json"), encoding="utf-8"))
        d = tempfile.mkdtemp()
        path = os.path.join(d, "理財帳本.db")
        shutil.copy(os.path.join(FIXTURES, name), path)
        db = Database(path)
        inv = Investments(db)
        new = ledger_tools.snapshot(db, inv)
        where = f"{name}（第 {old['schema']} 版）"
        assert new["schema"] == SCHEMA_VERSION, where
        if old["schema"] < SCHEMA_VERSION:
            assert os.path.exists(os.path.join(d, f"理財帳本_升級前備份_v{old['schema']}.db")), where
        for key in ("user_vouchers", "user_lines", "income", "expense", "categories", "realized", "holdings",
                    "events", "recon", "attachments", "recurring", "settings"):
            assert json.loads(json.dumps(new[key])) == old[key], (where, key)
        assert new["audit_rows"] >= old["audit_rows"], where
        assert new["accounts"].keys() == old["accounts"].keys(), where
        for acc, o in old["accounts"].items():
            n = new["accounts"][acc]
            if o["investment"] and old["schema"] in APPROVED_INVESTMENT_CHANGES:
                continue   # 只允許經同意的評價規則改變；下方再檢查投資科目＝持股帳面價值
            assert n["balance"] == o["balance"], (where, acc, o["balance"], n["balance"])
        check_books(db, where)
        db.close()
        # 再開一次不會重複升級或改變帳務
        db = Database(path)
        again = ledger_tools.snapshot(db, Investments(db))
        assert again["accounts"] == new["accounts"] and again["user_vouchers"] == new["user_vouchers"], where
        db.close()


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
    # 迴轉買進＝全數賣出：評價 969 留待下次市價評價歸零（v2.5.0 起賣出不迴轉評價）
    h = inv.holdings()
    assert len(h) == 1 and h[0]["shares"] == 0 and h[0]["market_value"] == 969, h
    assert investment_accounts_match(db)
    inv.add_event(sid, "price", "2026-03-31", price=110)
    assert not inv.holdings() and db.account_summaries()[1]["balance"] == 0
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


def test_global_search():
    """全域搜尋：文字、金額、傳票號碼、日期（含民國）、科目代號、標的、附件與定期交易，多個關鍵字為 AND。"""
    from app.search import search
    db, inv, bank, st, sid = _plain_ledger()
    food = db.find_category("expense", "餐飲")
    t1 = db.add_transaction(date="2026-03-05", type="expense", account_id=bank, amount=1500, category_id=food["id"], note="全聯採買")
    t2 = db.add_transaction(date="2026-04-10", type="expense", account_id=bank, amount=320, category_id=food["id"], note="早餐")
    db.add_journal("2026-03-20", "買進元大", [
        {"account_id": st, "debit": 50000, "security_id": sid, "shares": 400, "price": 0.866},
        {"account_id": bank, "credit": 50000}])
    folder = tempfile.mkdtemp()
    src = os.path.join(folder, "發票掃描.pdf")
    with open(src, "wb") as fh:
        fh.write(b"x")
    db.add_attachment(t2, src, os.path.join(folder, "att"))
    db.save_recurring(None, "月退休金", {"type": "income", "account_id": bank, "amount": 42000,
                                      "category_id": db.list_categories("income")[0]["id"], "note": ""},
                      "monthly", 5, "2026-01-01")
    db.void_transactions([t2], "打錯")

    def refs(q, group="傳票"):
        return [r["ref"] if group != "傳票" else r["id"] for r in search(db, q)["rows"] if r["group"] == group]

    assert refs("全聯") == [t1]
    assert refs("1,500") == [t1] and refs("1500") == [t1]
    assert refs(f"V{t1:06d}") == [t1] and refs(f"v{t1}") == [t1]
    assert set(refs("2026-03")) == {t1, t1 + 2} and set(refs("115/3")) == set(refs("2026-03"))
    assert refs("2026/03/05") == [t1]
    assert refs("全聯 2026-04") == []                        # AND
    assert refs("餐飲 2026-03") == [t1]
    assert refs("0.866") and refs("0050") and refs("元大")    # 單價、標的代號、名稱
    assert refs("發票掃描") == [t2] and refs("打錯") == [t2]    # 附件檔名、作廢原因
    assert next(r for r in search(db, "早餐")["rows"])["void"]
    code = db.account_codes()[st]
    assert code in refs(code, "科目") and t1 + 2 in refs(code)
    assert refs("0050", "投資標的") == ["0050"]
    assert len(refs("退休金", "定期交易")) == 1 and len(refs("42000", "定期交易")) == 1
    assert search(db, "  ")["rows"] == []
    assert not search(db, "不存在的東西")["rows"]
    # 只讀取：搜尋不改變任何資料
    before = db._q1("SELECT COUNT(*) n FROM audit_log")["n"]
    search(db, "全聯 1500 V1 2026-03")
    assert db._q1("SELECT COUNT(*) n FROM audit_log")["n"] == before


# ---------------------------------------------------------------------- v2.11.0：標籤、復原、第二份備份
def _books(db):
    """帳務指紋：各帳戶餘額、未作廢傳票、持股與試算表是否平衡。"""
    lo, hi = db.date_range()
    return ({a["id"]: round(a["balance"], 2) for a in db.account_summaries(include_archived=True)},
            db._q1("SELECT COUNT(*) n FROM transactions WHERE void = 0")["n"],
            [(h["id"], round(h["shares"], 4), round(h["cost"], 2)) for h in Investments(db).holdings(include_zero=True)],
            balanced(db.trial_balance(lo, hi)))


def test_tags():
    db, inv, bank, st, sid = _plain_ledger()
    food = db.find_category("expense", "餐飲")["id"]
    hotel = db.find_category("expense", "旅遊")["id"]
    assert Database.parse_tags(" #日本旅遊 2026、房屋修繕，日本旅遊 2026; ") == ["日本旅遊 2026", "房屋修繕"]
    t1 = db.add_transaction(date="2026-03-02", type="expense", account_id=bank, amount=1200, category_id=food,
                            note="京都晚餐", tags="日本旅遊 2026")
    t2 = db.add_journal("2026-03-03", "京都住宿", [
        {"category_id": hotel, "debit": 8000}, {"category_id": food, "debit": 500},
        {"account_id": bank, "credit": 8500}], tags=["日本旅遊 2026", "住宿"])
    t3 = db.add_transaction(date="2026-03-04", type="expense", account_id=bank, amount=99, category_id=food)
    assert db.get_tags(t2) == ["日本旅遊 2026", "住宿"]
    assert [r["id"] for r in db.query_transactions(tag="日本旅遊 2026")] == [t2, t1]
    assert {r["id"] for r in db.query_transactions(keyword="住宿")} == {t2}       # 關鍵字也找得到標籤
    s = {r["name"]: r for r in db.tag_summary("2026-01-01", "2026-12-31")}
    assert s["日本旅遊 2026"]["expense"] == 9700 and s["日本旅遊 2026"]["count"] == 2
    assert s["住宿"]["expense"] == 8500 and s["住宿"]["net"] == -8500
    cats = {c["name"]: c["total"] for c in db.tag_categories("日本旅遊 2026", "2026-01-01", "2026-12-31")}
    assert cats == {"旅遊": 8000, "餐飲": 1700}
    # 批次加標籤、改名（合併）、移除
    assert db.add_tag([t1, t3], "三月") == 2 and db.add_tag([t1], "三月") == 0
    assert db.rename_tag("三月", "住宿") == 2
    assert db.get_tags(t1) == ["日本旅遊 2026", "住宿"] and db.get_tags(t3) == ["住宿"]
    assert db.delete_tag("住宿") == 3 and not db.get_tags(t3)
    # 修改傳票時保留／更新標籤；作廢的傳票不計入合計
    db.update_transaction(t1, date="2026-03-02", type="expense", account_id=bank, amount=1300, category_id=food,
                          note="京都晚餐")
    assert db.get_tags(t1) == ["日本旅遊 2026"]
    db.void_transactions([t1], "重複")
    assert {r["name"]: r for r in db.tag_summary("2026-01-01", "2026-12-31")}["日本旅遊 2026"]["expense"] == 8500
    # 已結帳期間也可以加標籤（不影響金額）；系統傳票不行
    db.set_closed_until("2026-03-31")
    db.set_tags(t2, ["日本旅遊 2026", "回顧"])
    assert db.get_tags(t2) == ["日本旅遊 2026", "回顧"]
    db.set_closed_until("")
    inv.add_event(sid, "buy", "2026-04-01", shares=100, price=100, fee=20, cash_account_id=bank)
    sys_id = db._q1("SELECT id FROM transactions WHERE source LIKE 'inv:%'")["id"]
    try:
        db.set_tags(sys_id, ["x"])
        raise AssertionError("系統傳票不應能加標籤")
    except ValueError:
        pass
    # 投資分錄重編不會弄丟使用者分錄的標籤
    jb = db.add_journal("2026-04-02", "買進 0050", [
        {"account_id": st, "debit": 10000, "security_id": sid, "shares": 100, "price": 100},
        {"account_id": bank, "credit": 10000}], tags=["退休投資"])
    inv.add_event(sid, "price", "2026-04-30", price=120)
    inv.rebuild(sid, "2026-01-01")
    assert db.get_tags(jb) == ["退休投資"]
    # 匯出 Excel 的收支明細可以看到標籤
    assert any(r["tags"] == ["退休投資"] for r in db.query_transactions())


def test_undo():
    from app import undo
    db, inv, bank, st, sid = _plain_ledger()
    food = db.find_category("expense", "餐飲")["id"]
    salary = db.find_category("income", "薪資")["id"]
    db.clear_undo()
    b0 = _books(db)
    # 新增 → 復原＝作廢（傳票保留）
    t1 = db.add_transaction(date="2026-02-01", type="expense", account_id=bank, amount=300, category_id=food,
                            note="午餐")
    assert undo.next_label(db).startswith("新增 V") and "午餐" in undo.next_label(db)
    undo.undo_last(db)
    t = db.get_transaction(t1)
    assert t["void"] == 1 and "復原" in t["void_reason"] and _books(db) == b0
    assert not undo.can_undo(db)
    try:
        undo.undo_last(db)
        raise AssertionError
    except ValueError:
        pass
    # 修改 → 復原＝改回原內容（含標籤、類型）
    t2 = db.add_transaction(date="2026-02-02", type="income", account_id=bank, amount=40000, category_id=salary,
                            note="退休金", tags=["固定收入"])
    b1 = _books(db)
    db.update_transaction(t2, date="2026-02-05", type="expense", account_id=bank, amount=99, category_id=food,
                          note="改錯了", tags=[])
    undo.undo_last(db)
    t = db.get_transaction(t2)
    assert (t["type"], t["amount"], t["date"], t["note"], t["category_id"]) == ("income", 40000, "2026-02-02",
                                                                             "退休金", salary)
    assert db.get_tags(t2) == ["固定收入"] and _books(db) == b1
    # 分錄（連結投資標的）修改 → 復原：股數、單價、持股都回來
    j = db.add_journal("2026-03-01", "買進 0050", [
        {"account_id": st, "debit": 15000, "security_id": sid, "shares": 100, "price": 150},
        {"account_id": bank, "credit": 15000}])
    b2 = _books(db)
    lines_before = [(x["account_id"], x["debit"], x["credit"], x["shares"], x["price"]) for x in db.get_lines(j)]
    db.update_journal(j, "2026-03-01", "買進 0050", [
        {"account_id": st, "debit": 30000, "security_id": sid, "shares": 200, "price": 150},
        {"account_id": bank, "credit": 30000}])
    assert _books(db) != b2
    undo.undo_last(db)
    assert [(x["account_id"], x["debit"], x["credit"], x["shares"], x["price"]) for x in db.get_lines(j)] == lines_before
    assert _books(db) == b2 and investment_accounts_match(db)
    # 作廢多筆（含銀行對帳勾選）→ 一步復原
    t3 = db.add_transaction(date="2026-03-05", type="expense", account_id=bank, amount=500, category_id=food)
    t4 = db.add_transaction(date="2026-03-06", type="expense", account_id=bank, amount=600, category_id=food)
    db.save_reconciliation(bank, "2026-03-31", 0, [t3, t4])
    b3 = _books(db)
    db.void_transactions([t3, t4], "整理")
    assert undo.next_label(db) == "作廢 2 筆傳票"
    undo.undo_last(db)
    assert _books(db) == b3
    assert {r["txn_id"] for r in db._q("SELECT txn_id FROM recon_items")} >= {t3, t4}
    # 取消作廢 → 復原＝再次作廢（原因不變）
    db.void_transactions([t4], "原因甲")
    db.unvoid_transaction(t4)
    undo.undo_last(db)
    assert db.get_transaction(t4)["void"] == 1 and db.get_transaction(t4)["void_reason"] == "原因甲"
    undo.undo_last(db)                      # 再復原上一步（作廢）→ 恢復
    assert db.get_transaction(t4)["void"] == 0
    # 投資管理：新增交易 → 復原＝刪除；刪除交易 → 復原＝加回（同一編號）
    b4 = _books(db)
    eid = inv.add_event(sid, "buy", "2026-04-01", shares=50, price=160, fee=20, cash_account_id=bank)
    assert _books(db) != b4
    undo.undo_last(db)
    assert _books(db) == b4 and not db._q1("SELECT 1 FROM sec_events WHERE id = ?", (eid,))
    eid = inv.add_event(sid, "buy", "2026-04-01", shares=50, price=160, fee=20, cash_account_id=bank)
    b5 = _books(db)
    inv.delete_event(eid)
    undo.undo_last(db)
    assert _books(db) == b5 and db._q1("SELECT 1 FROM sec_events WHERE id = ?", (eid,)) and investment_accounts_match(db)
    # 同一天重新輸入市價（取代舊價格）→ 復原＝舊價格回來
    inv.add_event(sid, "price", "2026-04-30", price=170)
    b6 = _books(db)
    inv.add_event(sid, "price", "2026-04-30", price=200)
    undo.undo_last(db)
    assert _books(db) == b6 and inv.last_price(sid) == 170 and investment_accounts_match(db)
    # 定期交易入帳 → 復原：傳票作廢、下次仍會提醒
    rid = db.save_recurring(None, "月退休金", {"type": "income", "account_id": bank, "amount": 42000,
                                               "category_id": salary}, "monthly", 5, "2026-05-01")
    rec = db.list_recurring()[0]
    due = db.due_recurring("2026-05-31")
    tid = db.post_recurring(rec, due[0][1])
    assert not db.due_recurring("2026-05-31")
    undo.undo_last(db)
    assert db.get_transaction(tid)["void"] == 1 and len(db.due_recurring("2026-05-31")) == 1
    assert rid
    # 匯入多筆 → 一步復原
    from app.importer import do_import
    b7 = _books(db)
    items = [{"error": "", "category_id": food, "category_name": "", "date": f"2026-06-0{i}", "type": "expense",
              "account_id": bank, "amount": 10 * i, "note": "匯入"} for i in range(1, 4)]
    assert do_import(db, items) == (3, 0)
    assert undo.next_label(db) == "匯入 3 筆紀錄"
    undo.undo_last(db)
    assert _books(db) == b7
    # 已結帳期間不能復原：顯示原因，這一步留在清單上
    t5 = db.add_transaction(date="2026-06-10", type="expense", account_id=bank, amount=77, category_id=food)
    db.set_closed_until("2026-06-30")
    try:
        undo.undo_last(db)
        raise AssertionError("已結帳期間不應能復原")
    except ValueError as e:
        assert "無法復原" in str(e)
    assert undo.can_undo(db) and db.get_transaction(t5)["void"] == 0
    db.set_closed_until("")
    undo.undo_last(db)
    assert db.get_transaction(t5)["void"] == 1
    # 每一步都留有修改紀錄
    assert db._q1("SELECT COUNT(*) n FROM audit_log WHERE action = '復原'")["n"] >= 12
    # 系統內部動作（投資重編、範例資料）不會進入復原清單；清除資料時清單一併清空
    db.clear_undo()
    inv.rebuild(sid, "2026-01-01")
    assert not undo.can_undo(db)
    db.add_transaction(date="2026-07-01", type="expense", account_id=bank, amount=1, category_id=food)
    db.reset_all()
    assert not undo.can_undo(db)


def test_migration_v8_tags():
    """第 8 版（v2.9.0／v2.10.0）帳本升級到第 9 版：新增標籤資料表，帳務不變、不重編投資分錄。"""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "v8.db")
    db = Database(path)
    load_sample_data(db)
    before = _books(db)
    ids = [r["id"] for r in db._q("SELECT id FROM transactions ORDER BY id")]
    n_audit = db._q1("SELECT COUNT(*) n FROM audit_log")["n"]
    db.close()
    c = sqlite3.connect(path)
    c.executescript("DROP INDEX IF EXISTS idx_txn_tags_tag; DROP TABLE txn_tags; PRAGMA user_version = 8;")
    c.commit()
    c.close()
    db = Database(path)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 9
    assert _books(db) == before
    assert [r["id"] for r in db._q("SELECT id FROM transactions ORDER BY id")] == ids
    assert db._q1("SELECT COUNT(*) n FROM audit_log")["n"] == n_audit       # 沒有「系統升級」重編
    assert os.path.exists(os.path.join(d, "v8_升級前備份_v8.db"))
    db.set_tags(ids[0], ["測試"]) if not db.get_transaction(ids[0])["source"] else None
    assert db.all_tags() is not None


def test_extra_backup():
    from app import backup
    db = make()
    data = tempfile.mkdtemp()
    os.makedirs(os.path.join(data, "憑證附件", "2026"))
    with open(os.path.join(data, "憑證附件", "2026", "發票.pdf"), "wb") as fh:
        fh.write(b"pdf")
    usb = tempfile.mkdtemp()
    assert not backup.due_today(db) and not backup.status(db)["remind"]
    try:
        backup.run(db, data)
        raise AssertionError("未設定位置時應失敗")
    except OSError:
        pass
    db.set_setting(backup.DIR_KEY, usb)
    assert backup.due_today(db) and backup.status(db)["remind"]
    path = backup.run(db, data)
    assert os.path.dirname(path) == os.path.join(usb, backup.SUBFOLDER)
    assert Database.is_valid_ledger(path)
    copy = Database(path)
    assert _books(copy) == _books(db)
    copy.close()
    assert os.path.exists(os.path.join(usb, backup.SUBFOLDER, "憑證附件", "2026", "發票.pdf"))
    assert not backup.due_today(db)
    st = backup.status(db)
    assert st["days"] == 0 and not st["remind"] and not st["error"]
    # 同一天再備份：覆蓋同一個檔；保留最近 30 天
    assert backup.run(db, data) == path
    for i in range(35):
        backup.run(db, data, today=_dt.date(2025, 1, 1) + _dt.timedelta(days=i))
    files = [f for f in os.listdir(os.path.join(usb, backup.SUBFOLDER)) if f.endswith(".db")]
    assert len(files) == backup.KEEP and f"帳本備份_{_dt.date.today():%Y%m%d}.db" in files
    # 隨身碟沒插上：不影響帳本，只記錄原因
    db.set_setting(backup.DIR_KEY, os.path.join(usb, "不存在的隨身碟"))
    assert not backup.try_run(db, data)
    assert "找不到資料夾" in backup.status(db)["error"]
    db.set_setting(backup.LAST_KEY, (_dt.datetime.now() - _dt.timedelta(days=10)).isoformat(timespec="seconds"))
    assert backup.status(db)["remind"] and backup.status(db)["days"] == 10


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


def _perf_ledger():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "t.db"))
    bank = db.add_account("台銀活存", "asset", "銀行存款", opening_balance=500000, opening_date="2024-01-01")
    st = db.add_account("短期投資", "asset", "短期投資", opening_date="2024-01-01")
    inv = Investments(db)
    sid = inv.add_security(st, "0050", "元大台灣50")
    inv.add_event(sid, "buy", "2024-01-02", shares=1000, price=50, fee=71, cash_account_id=bank)
    inv.add_event(sid, "cash_div", "2024-07-01", amount=2000, cash_account_id=bank)
    inv.add_event(sid, "stock_div", "2024-08-01", shares=50)
    inv.add_event(sid, "sell", "2025-01-02", shares=500, price=60, fee=42, tax=90, cash_account_id=bank)
    inv.add_event(sid, "price", "2025-06-30", price=55)
    return db, inv, bank, st, sid


def test_xirr():
    from app.performance import xirr
    assert abs(xirr([("2023-01-01", -1000), ("2024-01-01", 1100)]) - 0.10) < 1e-6
    assert abs(xirr([("2023-01-01", -1000), ("2025-01-01", 1210)]) - 0.10) < 1e-3
    r = xirr([("2023-01-01", -1000), ("2023-07-01", -500), ("2024-03-01", 300), ("2025-01-01", 1400)])
    t0 = _dt.date(2023, 1, 1)
    npv = sum(a / (1 + r) ** ((_dt.date.fromisoformat(d) - t0).days / 365)
              for d, a in [("2023-01-01", -1000), ("2023-07-01", -500), ("2024-03-01", 300), ("2025-01-01", 1400)])
    assert abs(npv) < 1e-3, npv
    assert xirr([("2023-01-01", -1000)]) is None and xirr([]) is None
    assert xirr([("2023-01-01", -1000), ("2024-01-01", 500)]) < 0      # 虧損


def test_investment_performance():
    from app.performance import portfolio_performance, security_performance
    db, inv, bank, st, sid = _perf_ledger()
    sec = inv.get_security(sid)
    p = security_performance(inv, sec, "2025-12-31")
    stt = inv.replay(sid, "2025-12-31")
    assert p["invested"] == 50071 and p["value"] == stt["market_value"]
    assert p["returned"] == 2000 + 500 * 60 - 42 - 90
    # 總損益＝已實現＋股利＋未實現
    assert abs(p["gain"] - (p["realized"] + p["dividends"] + p["unrealized"])) < 0.01, p
    assert abs(p["total_return"] - p["gain"] / 50071) < 1e-12
    assert p["years"] > 1.9 and p["xirr"] is not None
    from app.performance import xirr
    assert abs(p["xirr"] - xirr(p["flows"] + [("2025-12-31", p["value"])])) < 1e-9
    # 未滿一年不年化
    q = security_performance(inv, sec, "2024-12-01")
    assert q["xirr"] is None and q["total_return"] is not None and q["years"] < 1
    # 投資組合（單一標的）與該標的一致
    pp = portfolio_performance(inv, "2025-12-31")
    assert abs(pp["total"]["gain"] - p["gain"]) < 0.01 and abs(pp["total"]["xirr"] - p["xirr"]) < 1e-9
    # 計算績效不改變帳務
    investment_accounts_match(db)
    # 分錄買進（含手續費）：投入金額＝借記投資科目的金額
    db2, inv2, *_ , sid2 = _her_ledger()
    assert security_performance(inv2, inv2.get_security(sid2), "2025-12-31")["invested"] == 98139
    # 範例資料：每個標的與合計都符合總損益恆等式
    db3 = make()
    pp = portfolio_performance(Investments(db3))
    assert pp["rows"]
    for r in pp["rows"] + [pp["total"]]:
        assert abs(r["gain"] - (r["realized"] + r["dividends"] + r["unrealized"])) < 0.05, r


def test_comparative_statements():
    from app import statements as S
    assert S.previous_period("2026-01-01", "2026-12-31") == ("2025-01-01", "2025-12-31")
    assert S.previous_period("2026-03-01", "2026-03-31") == ("2026-02-01", "2026-02-28")
    assert S.previous_period("2026-01-01", "2026-03-31") == ("2025-10-01", "2025-12-31")
    assert S.previous_period("2026-03-05", "2026-03-14") == ("2026-02-23", "2026-03-04")
    assert S.shift_year("2024-02-29") == "2023-02-28"
    assert S.compare_date("prior_period", "2026-01-01", "2026-06-30") == "2025-12-31"
    assert S.compare_date("prior_year", "2026-01-01", "2026-06-30") == "2025-06-30"
    assert S.compare_range("none", "2026-01-01", "2026-06-30") is None
    db = make()
    lo, hi = db.date_range()
    mid = "2026-06-30"
    b = S.balance_sheet(db, hi, mid)
    rows = {r["name"]: r for r in b["rows"]}
    cur, prev = db.balance_sheet(hi), db.balance_sheet(mid)
    assert rows["資產總計"]["cur"] == cur["assets"] and rows["資產總計"]["prev"] == prev["assets"]
    assert rows["淨資產（業主權益）"]["prev"] == prev["net"]
    # 各科目加總等於合計（本期與比較期）
    for g in ("流動資產", "非流動資產", "流動負債", "非流動負債"):
        names = [a for a in b["rows"]]
        i = next(k for k, r in enumerate(names) if r["name"] == g)
        j = next(k for k, r in enumerate(names) if r["name"] == f"{g}合計")
        for key in ("cur", "prev"):
            assert abs(sum(r[key] for r in names[i + 1:j]) - names[j][key]) < 0.05, (g, key)
    i = S.income_statement(db, "2026-07-01", hi, S.compare_range("prior_period", "2026-07-01", hi))
    s, p = i["is"], i["prev"]
    last = i["rows"][-1]
    assert last["cur"] == s["comprehensive"] and last["prev"] == p["comprehensive"]
    inc = [r for r in i["rows"] if r["kind"] == "income" and not r["style"]]
    assert abs(sum(r["cur"] for r in inc) - s["total_income"]) < 0.05
    assert abs(sum(r["prev"] for r in inc) - p["total_income"]) < 0.05
    assert S.change(110, 100) == (10, 0.1) and S.change(5, 0) == (5, None)
    r = {x["name"]: x for x in S.ratios(db, "2026-01-01", hi, ("2025-01-01", "2025-12-31"))}
    assert abs(r["負債比率"]["cur"] - cur["liabilities"] / cur["assets"]) < 1e-12
    assert S.fmt_ratio_change(0.25, 0.2, "pct") == "+5.0 個百分點"
    assert S.fmt_ratio(None, "pct", "未滿一年") == "未滿一年"
