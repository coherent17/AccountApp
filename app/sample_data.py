"""範例資料：讓使用者第一次開啟時可以先試用各項功能。"""

from __future__ import annotations

import datetime as dt
import random

from .database import Database, last_n_months
from .investments import Investments


def _cat(db: Database, kind: str) -> dict[str, int]:
    return {c["name"]: c["id"] for c in db.list_categories(kind)}


def load_sample_data(db: Database) -> None:
    rnd = random.Random(20261019)
    today = dt.date.today()
    months = last_n_months(12, today)
    start = dt.date.fromisoformat(months[0] + "-01")
    s = start.isoformat()

    cash = db.add_account("隨身現金", "asset", "現金", opening_balance=8000, opening_date=s)
    post = db.add_account("郵局活儲", "asset", "銀行存款", opening_balance=380000, opening_date=s)
    bank2 = db.add_account("台銀活存", "asset", "銀行存款", opening_balance=1480000, opening_date=s,
                           note="證券交割帳戶")
    fixed = db.add_account("台銀定存", "asset", "定期存款", opening_balance=1500000, opening_date=s,
                           note="一年期", interest_rate=1.7,
                           maturity_date=(today + dt.timedelta(days=24)).isoformat())
    db.add_account("美元定存", "asset", "外幣存款", currency="USD", rate=32.0,
                   opening_balance=20000, opening_date=s, interest_rate=4.0,
                   maturity_date=(today + dt.timedelta(days=150)).isoformat())
    broker = db.add_account("短期投資－元大證券", "asset", "短期投資", opening_balance=0, opening_date=s,
                            note="上市櫃股票、ETF")
    long_inv = db.add_account("長期投資－台積電", "asset", "長期投資", opening_balance=0, opening_date=s,
                              note="長期持有")
    fund = db.add_account("全球債券基金", "asset", "基金", opening_balance=300000, opening_date=s)
    policy = db.add_account("國泰人壽儲蓄保單", "asset", "保險", opening_balance=600000,
                            opening_date=s, note="保單價值準備金", interest_rate=2.25,
                            maturity_date=dt.date(today.year + 6, 3, 1).isoformat())
    card = db.add_account("國泰信用卡", "liability", "信用卡", opening_balance=12000,
                          opening_date=s)

    inc = _cat(db, "income")
    exp = _cat(db, "expense")

    def add(day: dt.date, ttype: str, acc: int, amount: float, cat: str | None = None,
            note: str = "", to: int | None = None) -> None:
        if day > today:
            return
        cid = None
        if ttype == "income":
            cid = inc[cat]
        elif ttype == "expense":
            cid = exp[cat]
        db.add_transaction(date=day.isoformat(), type=ttype, account_id=acc, amount=amount,
                           category_id=cid, note=note, to_account_id=to, log="範例資料")

    last_posted: dict[str, str] = {}
    for ym in months:
        y, m = map(int, ym.split("-"))
        d = lambda n: dt.date(y, m, min(n, 28))  # noqa: E731
        add(d(5), "income", post, 42000, "退休金", "月退休金")
        if d(5) <= today:
            last_posted["pension"] = d(5).isoformat()
        add(d(10), "expense", post, rnd.choice([1150, 1280, 1420, 1630]), "居家水電", "電費＋水費")
        add(d(12), "expense", post, 999, "通訊網路", "手機及網路")
        if d(12) <= today:
            last_posted["phone"] = d(12).isoformat()
        add(d(15), "expense", bank2, 10000, "孝親家用", "家用補貼")
        if d(15) <= today:
            last_posted["family"] = d(15).isoformat()
        add(d(20), "transfer", post, 6000, note="提領現金", to=cash)
        for day in (2, 6, 9, 13, 17, 21, 24, 27):
            add(d(day), "expense", cash, rnd.randrange(80, 450, 10), "餐飲",
                rnd.choice(["早餐", "午餐", "市場買菜", "晚餐", "咖啡下午茶"]))
        for day in (3, 11, 19, 26):
            add(d(day), "expense", card, rnd.randrange(300, 2600, 10), "日常用品",
                rnd.choice(["全聯採買", "好市多", "藥妝店", "家樂福"]))
        add(d(8), "expense", cash, rnd.randrange(200, 900, 10), "交通", "捷運悠遊卡加值")
        if m % 3 == 0:
            add(d(14), "expense", card, rnd.randrange(800, 3000, 100), "醫療保健", "健檢／看診")
            add(d(25), "income", fixed, 6375, "利息", "定存利息")
        if m in (1, 2):
            add(d(18), "expense", cash, 12000, "人情交際", "過年紅包")
        if m == 5:
            add(d(30), "expense", post, 8600, "稅金規費", "綜合所得稅")
        if m == 10:
            add(d(22), "expense", card, 26800, "旅遊", "花東三日遊")
        if m == 3 and d(10) <= today:
            # 複式分錄：年繳保費，部分為保單價值、部分為保險費用
            db.add_journal(d(10).isoformat(), "國泰人壽年繳保費", [
                {"account_id": policy, "debit": 48000, "memo": "保單價值增加"},
                {"category_id": exp["保險費"], "debit": 12000, "memo": "危險保費"},
                {"account_id": post, "credit": 60000},
            ], log="範例資料")
        add(d(22), "transfer", post, rnd.randrange(4000, 9000, 10), note="繳信用卡費", to=card)
        add(d(28), "adjust", fund, rnd.randrange(-4000, 5000, 100), note="月底淨值更新")

    # 投資明細帳
    inv = Investments(db)
    s0050 = inv.add_security(broker, "0050", "元大台灣50")
    s2330 = inv.add_security(long_inv, "2330", "台積電")
    s0056 = inv.add_security(broker, "0056", "元大高股息")
    first = start + dt.timedelta(days=2)
    for sid, sh, pr in ((s0050, 3000, 92.0), (s2330, 200, 1850.0), (s0056, 8000, 36.0)):
        fee, _ = inv.suggest_fees("buy", sh, pr)
        inv.add_event(sid, "buy", first.isoformat(), shares=sh, price=pr, fee=fee,
                      cash_account_id=bank2, note="建立部位")
    prices = {s0050: 92.0, s2330: 1850.0, s0056: 36.0}
    for i, ym in enumerate(months):
        y, m = map(int, ym.split("-"))
        eom = dt.date(y, m, 27)
        if eom > today:
            continue
        for sid, drift in ((s0050, 0.012), (s2330, 0.02), (s0056, 0.004)):
            prices[sid] = round(prices[sid] * (1 + drift + rnd.uniform(-0.04, 0.04)), 2)
        inv.set_prices([(sid, p) for sid, p in prices.items()], eom.isoformat())
        if i == 7:
            fee, tax = inv.suggest_fees("sell", 100, prices[s2330], "2330")
            inv.add_event(s2330, "sell", dt.date(y, m, 18).isoformat(), shares=100,
                          price=prices[s2330], fee=fee, tax=tax, cash_account_id=bank2,
                          note="部分獲利了結")
        if i == 9:
            # 以複式分錄直接買進（借 短期投資／貸 銀行存款），不產生評價分錄
            fee, _ = inv.suggest_fees("buy", 1000, prices[s0056])
            cost = round(1000 * prices[s0056]) + fee
            db.add_journal(dt.date(y, m, 12).isoformat(), "加碼買進 元大高股息 1,000 股", [
                {"account_id": broker, "debit": cost, "security_id": s0056, "shares": 1000,
                 "memo": "含手續費"},
                {"account_id": bank2, "credit": cost},
            ], log="範例資料")
        if m in (1, 4, 7, 10):
            div = 8000 * 0.75
            inv.add_event(s0056, "cash_div", dt.date(y, m, 16).isoformat(), amount=div,
                          nhi=inv.suggest_nhi(div), cash_account_id=bank2)
        if m == 7:
            div = 3000 * 7.2
            inv.add_event(s0050, "cash_div", dt.date(y, m, 21).isoformat(), amount=div,
                          nhi=inv.suggest_nhi(div), cash_account_id=bank2)

    # 定期交易範本
    def rec(name, data, day, key):
        rid = db.save_recurring(None, name, data, "monthly", day, s)
        if key in last_posted:
            db.conn.execute("UPDATE recurring SET last_date = ? WHERE id = ?", (last_posted[key], rid))
    rec("月退休金", {"type": "income", "account_id": post, "amount": 42000,
                   "category_id": inc["退休金"], "note": "月退休金"}, 5, "pension")
    rec("手機及網路", {"type": "expense", "account_id": post, "amount": 999,
                    "category_id": exp["通訊網路"], "note": "手機及網路"}, 12, "phone")
    rec("家用補貼", {"type": "expense", "account_id": bank2, "amount": 10000,
                  "category_id": exp["孝親家用"], "note": "家用補貼"}, 15, "family")
    db.conn.commit()

    for name, budget in (("餐飲", 6000), ("日常用品", 5000), ("交通", 1500), ("醫療保健", 3000),
                         ("居家水電", 1600)):
        db.update_category(exp[name], budget=budget)

    db.set_setting("first_run_done", "1")
    db.set_setting("sample_data", "1")
    db.set_setting("last_account_id", cash)
