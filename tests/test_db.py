import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.analytics import cash_flow, retirement_projection, tax_summary  # noqa: E402
from app.database import SCHEMA_VERSION, Database, month_keys  # noqa: E402
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
    inv.set_prices([(sid, 120)], "2026-03-31")
    h = inv.holdings()[0]
    assert h["market_value"] == 12000 and h["unrealized"] == 2000
    assert investment_accounts_match(db)
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 2000) < 0.01
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
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 1000) < 0.01
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
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 3000) < 0.01
    h = inv.holdings()[0]
    assert h["price"] == 130 and abs(h["market_value"] - 28000) < 0.01 and h["unrealized"] == 3000
    assert inv.holdings("2026-03-31")[0]["shares"] == 100
    assert investment_accounts_match(db)
    # 同一天重新評價取代先前市價
    inv.set_prices([(sid, 120)], "2026-03-31")
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 2000) < 0.01
    # 賣出迴轉所售股份的評價，剩餘持股不重新評價
    inv.add_event(sid, "sell", "2026-06-01", shares=100, price=200, cash_account_id=bank)
    assert abs(inv.holdings()[0]["unrealized"] - 1000) < 0.01
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
    assert abs(db.adjust_totals("2026-01-01", "2026-12-31") - 4000) < 0.01
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
    assert inv.holdings()[0]["market_value"] == 11000
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


def test_tax_and_retirement():
    db = make()
    ts = tax_summary(db, int(db.date_range()[1][:4]))
    tags = {t["tag"] for t in ts["incomes"]}
    assert {"interest", "dividend", "pension"} <= tags, tags
    p = retirement_projection(66, 95, 5_000_000, 50000, 42000, 3, 2)
    assert p["rows"][0]["age"] == 66 and p["sustainable_monthly"] > 0


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
