"""舊版帳本測試資料：建立帳本與擷取帳務快照。

這個檔案必須能在「每一個已發行版本」的程式下執行（tools/make_fixtures.py 會用舊版程式呼叫它），
所以只能使用各版本都有的 Database／Investments 方法，也不可匯入 Qt。
"""

from __future__ import annotations

import json

INVESTMENT_CATEGORIES = {"短期投資", "長期投資", "股票", "基金", "債券"}


def build(db, inv) -> None:
    """建立一份接近實際使用情形的帳本（日期固定在 2025 年，結果可重現）。"""
    def acc(name, kind, cat, code, ob=0.0, cur="TWD", rate=1.0):
        return db.add_account(name, kind, cat, currency=cur, rate=rate, opening_balance=ob,
                              opening_date="2025-01-01", code=code)

    cash = acc("現金", "asset", "現金", "1101", 20000)
    tw = acc("銀行存款-台銀-活存 NT", "asset", "銀行存款", "1110", 900000)
    hn = acc("銀行存款-華南-活存 NT", "asset", "銀行存款", "1115", 600000)
    usd = acc("美元定存", "asset", "外幣存款", "1120", 10000, "USD", 32.0)
    st = acc("短期投資-股票", "asset", "短期投資", "1201")
    etf = acc("短期投資-ETF", "asset", "短期投資", "1202")
    card = acc("信用卡", "liability", "信用卡", "2101", 5000)
    loan = acc("房屋貸款", "liability", "房屋貸款", "2201", 800000)
    cat = {(c["kind"], c["name"]): c["id"] for c in db.list_categories(include_archived=True)}
    food, pension = cat[("expense", "餐飲")], cat[("income", "退休金")]
    interest = cat.get(("expense", "房貸利息")) or cat[("expense", "餐飲")]

    s3715 = inv.add_security(st, "3715", "定穎投控")
    s2330 = inv.add_security(st, "2330", "台積電")
    s0050 = inv.add_security(etf, "0050", "元大台灣50")
    s0056 = inv.add_security(etf, "0056", "元大高股息")

    ids = {}
    for m in range(1, 13):
        ids[f"pension{m}"] = db.add_transaction(type="income", account_id=tw, amount=42000,
                                                date=f"2025-{m:02d}-05", category_id=pension, note="月退休金")
        ids[f"food{m}"] = db.add_transaction(type="expense", account_id=card if m % 2 else cash,
                                             amount=1500 + m * 37, date=f"2025-{m:02d}-15",
                                             category_id=food, note="餐費")
        db.add_journal(f"2025-{m:02d}-20", "房貸繳款", [
            {"account_id": loan, "debit": 10000, "memo": "本金"},
            {"category_id": interest, "debit": 1500, "memo": "利息"},
            {"account_id": tw, "credit": 11500}])
    ids["card_pay"] = db.add_transaction(type="transfer", account_id=hn, to_account_id=card, amount=9000,
                                         to_amount=9000, date="2025-07-01", note="繳信用卡費")
    # 複式分錄買賣（手續費併入成本；新版的成交單價欄位舊版會忽略）
    db.add_journal("2025-02-04", "買入 定穎投控", [
        {"account_id": st, "debit": 98139, "security_id": s3715, "shares": 1000, "price": 98, "memo": "@98"},
        {"account_id": hn, "credit": 98139}])
    db.add_journal("2025-03-10", "買入 0050", [
        {"account_id": etf, "debit": 51323, "security_id": s0050, "shares": 1000, "price": 51.25},
        {"account_id": hn, "credit": 51323}])
    db.add_journal("2025-09-15", "賣出 定穎投控 400 股", [
        {"account_id": hn, "debit": 53762},
        {"account_id": st, "credit": 53762, "security_id": s3715, "shares": 400, "price": 135}])
    # 投資管理交易：買進、賣出、股利、配股、評價
    inv.add_event(s2330, "buy", "2025-04-01", shares=100, price=900, fee=128, cash_account_id=tw)
    inv.add_event(s2330, "sell", "2025-10-01", shares=40, price=1100, fee=62, tax=132, cash_account_id=tw)
    inv.add_event(s0056, "buy", "2025-05-02", shares=2000, price=35, fee=99, cash_account_id=tw)
    inv.add_event(s0056, "cash_div", "2025-07-16", amount=2000, cash_account_id=tw)
    inv.add_event(s0056, "stock_div", "2025-08-20", shares=100)
    inv.set_prices([(s3715, 130.5), (s0050, 70.2), (s2330, 1200)], "2025-11-28")
    # 外幣匯率差、作廢、迴轉
    db.add_transaction(type="transfer", account_id=tw, to_account_id=usd, amount=32500, to_amount=1000,
                       date="2025-06-03", note="買美元")
    void_id = db.add_transaction(type="expense", account_id=cash, amount=999, date="2025-03-03",
                                 category_id=food, note="輸入錯誤")
    db.void_transactions([void_id], "輸入錯誤")
    rev = db.add_transaction(type="expense", account_id=cash, amount=500, date="2025-04-08",
                             category_id=food, note="重複輸入")
    db.reverse_transaction(rev, "2025-04-09")
    # 定期交易、範本、對帳、附件、稱呼、結帳
    db.save_recurring(None, "月退休金", {"type": "income", "account_id": tw, "amount": 42000,
                                      "category_id": pension, "note": "月退休金"}, "monthly", 5, "2025-01-05")
    db.set_setting("journal_templates", json.dumps(
        [["每月早餐", [["debit", f"category:{food}", "", 250], ["credit", f"account:{cash}", "", None]]]],
        ensure_ascii=False))
    trade = db._q1("SELECT id FROM transactions WHERE source = ? AND date = '2025-04-01'", (f"inv:{s2330}",))
    db.save_reconciliation(tw, "2025-04-30", 0, [ids["pension1"], ids["pension2"], trade["id"]])
    db.conn.execute("INSERT INTO attachments(txn_id, name, path, added_at) VALUES (?, '收據.jpg', 'x/收據.jpg',"
                    " '2025-01-15T10:00:00')", (ids["food1"],))
    db.set_setting("owner_name", "游媽媽")
    db.set_setting("closed_until", "2025-06-30")
    db.conn.commit()


def snapshot(db, inv) -> dict:
    """帳務快照：升級前後必須相同的資料（投資科目餘額另以「等於持股帳面價值」檢查）。"""
    q = lambda sql, p=(): [tuple(r) for r in db.conn.execute(sql, p).fetchall()]  # noqa: E731
    accounts = {}
    for a in db.account_summaries(include_archived=True):
        accounts[f'{a["code"]} {a["name"]}'] = {"kind": a["kind"], "category": a["category"],
                                                "currency": a["currency"],
                                                "balance": round(a["balance"], 2),
                                                "investment": a["category"] in INVESTMENT_CATEGORIES}
    lo, hi = "2025-01-01", "2025-12-31"
    totals = db.income_expense_totals(lo, hi)
    cats = {}
    for kind in ("income", "expense"):
        for c in db.category_totals(lo, hi, kind):
            if c["total"]:
                cats[f'{kind}:{c["name"]}'] = round(c["total"], 2)
    return {
        "schema": db.conn.execute("PRAGMA user_version").fetchone()[0],
        "accounts": accounts,
        "user_vouchers": q("SELECT id, date, type, amount, note, void FROM transactions"
                           " WHERE source NOT LIKE 'inv:%' AND source NOT LIKE 'close:%' ORDER BY id"),
        "user_lines": q("SELECT l.txn_id, l.account_id, l.category_id, l.special, l.debit, l.credit, l.memo,"
                        " l.security_id, l.shares FROM txn_lines l JOIN transactions t ON t.id = l.txn_id"
                        " WHERE t.source NOT LIKE 'inv:%' AND t.source NOT LIKE 'close:%' ORDER BY l.id"),
        "income": round(totals["income"], 2), "expense": round(totals["expense"], 2), "categories": cats,
        "realized": round(db.realized_totals(lo, hi), 2),
        "holdings": {h["code"]: [round(h["shares"], 4), round(h["cost"], 2)]
                     for h in inv.holdings(include_zero=True)},
        "events": q("SELECT id, security_id, date, kind, shares, price, fee, tax, amount FROM sec_events ORDER BY id"),
        "recon": sorted(q("SELECT txn_id, account_id FROM recon_items")),
        "attachments": q("SELECT txn_id, name, path FROM attachments ORDER BY id"),
        "recurring": q("SELECT name, data, freq, day, start_date, active FROM recurring ORDER BY id"),
        "settings": {k: db.get_setting(k) for k in ("owner_name", "closed_until", "journal_templates",
                                                     "base_currency")},
        "audit_rows": db.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
    }
