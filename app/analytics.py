"""分析報表：現金流量表、報稅彙總、退休規劃、資產配置。"""

from __future__ import annotations

import datetime as _dt

from .database import (CASH_EQUIVALENT_CATEGORIES, CURRENT_LIABILITY_CATEGORIES, TAX_TAGS,
                       Database, last_n_months, money_round, month_start)


# ====================================================================== 現金流量表
def cash_flow(db: Database, start: str, end: str) -> dict:
    """個人現金流量表（直接法）。

    現金及約當現金：現金、銀行存款、定期存款、外幣存款。
    生活（營業）活動：收入與支出科目、信用卡等流動負債。
    投資活動：股票、基金、債券、保險、不動產等非現金資產。
    籌資活動：貸款等非流動負債及淨值調整。
    """
    accs = {a["id"]: a for a in db._q("SELECT * FROM accounts")}
    db._acc_cache = accs
    db._codes_cache = db.account_codes()

    def is_cash(aid):
        return accs[aid]["kind"] == "asset" and accs[aid]["category"] in CASH_EQUIVALENT_CATEGORIES

    prev = (_dt.date.fromisoformat(start) - _dt.timedelta(days=1)).isoformat()

    def cash_total(as_of):
        return sum(a["base_value"] for a in db.account_summaries(as_of, include_archived=True)
                   if a["kind"] == "asset" and a["category"] in CASH_EQUIVALENT_CATEGORIES)

    opening = money_round(cash_total(prev))
    closing = money_round(cash_total(end))
    buckets = {"op_in": {}, "op_out": {}, "inv": {}, "fin": {}, "other": {}}

    def add(bucket, label, v):
        buckets[bucket][label] = buckets[bucket].get(label, 0.0) + v

    try:
        for t in db._q("SELECT * FROM transactions WHERE void = 0 AND date BETWEEN ? AND ?"
                       " ORDER BY date, id", (start, end)):
            lines = db.txn_lines_of(t)
            cash_lines = [ln for ln in lines if ln["kind"] == "account" and is_cash(ln["id"])]
            if not cash_lines:
                continue
            for ln in lines:
                if ln in cash_lines:
                    continue
                flow = ln["credit"] - ln["debit"]   # 對方科目貸方 = 現金流入
                if abs(flow) < 0.005:
                    continue
                if ln["kind"] == "category":
                    add("op_in" if ln["group"] == "收入" else "op_out", ln["name"], flow)
                elif ln["kind"] == "special":
                    if ln["id"] == "fx":
                        add("other", "匯率影響數", flow)
                    elif ln["id"] == "equity":
                        add("fin", "淨值調整", flow)
                    elif ln["id"] == "realized":
                        add("inv", "處分投資損益", flow)
                    else:
                        add("other", "現金帳戶餘額調整", flow)
                else:
                    a = accs[ln["id"]]
                    if a["kind"] == "liability":
                        if a["category"] in CURRENT_LIABILITY_CATEGORIES:
                            add("op_out", f"{a['category']}（{a['name']}）", flow)
                        else:
                            add("fin", f"{a['name']}", flow)
                    else:
                        add("inv", f"{a['name']}", flow)
    finally:
        db._acc_cache = None
        db._codes_cache = None
    # 期中新開立之現金帳戶
    new_cash = 0.0
    for a in accs.values():
        if start <= a["opening_date"] <= end and a["kind"] == "asset" and \
                a["category"] in CASH_EQUIVALENT_CATEGORIES and a["opening_balance"]:
            new_cash += a["opening_balance"] * a["rate"]
    if new_cash:
        add("other", "期中新增帳戶之期初金額", new_cash)

    def rows(bucket):
        return sorted(({"name": k, "amount": money_round(v)} for k, v in buckets[bucket].items()
                       if abs(v) >= 0.005), key=lambda r: -abs(r["amount"]))

    op = rows("op_in") + rows("op_out")
    inv = rows("inv")
    fin = rows("fin")
    other = rows("other")
    op_total = money_round(sum(r["amount"] for r in op))
    inv_total = money_round(sum(r["amount"] for r in inv))
    fin_total = money_round(sum(r["amount"] for r in fin))
    other_total = money_round(sum(r["amount"] for r in other))
    net = money_round(op_total + inv_total + fin_total + other_total)
    return {"opening": opening, "closing": closing, "operating": op, "investing": inv,
            "financing": fin, "other": other, "op_total": op_total, "inv_total": inv_total,
            "fin_total": fin_total, "other_total": other_total, "net": net,
            "check": money_round(opening + net - closing),
            "op_in": rows("op_in"), "op_out": rows("op_out")}


# ====================================================================== 報稅彙總
TAX_NOTES = {
    "interest": "利息所得與股利（合併計稅者）合計享有「儲蓄投資特別扣除額」每戶 27 萬元；郵政存簿儲金利息依規定免稅。",
    "dividend": "股利可選擇「合併計稅」（股利 × 8.5% 可抵減稅額，每戶上限 8 萬元）或「分開計稅」（28% 單一稅率）。",
    "rental": "租賃所得可減除必要損耗及費用（一般為租金收入的 43%）。",
    "pension": "一次領取或分期領取之退職所得，依當年度定額免稅標準計算。",
    "salary": "薪資所得可減除薪資所得特別扣除額。",
    "other_income": "",
    "insurance": "人身保險費（不含全民健保）每人每年上限 24,000 元；全民健保費不受金額限制。",
    "medical": "醫藥及生育費需為公立醫院、健保特約醫療院所之收據，核實認列，無上限。",
    "donation": "對教育、文化、公益、慈善機構之捐贈，以綜合所得總額 20% 為上限；對政府捐獻無上限。",
    "mortgage_interest": "自用住宅購屋借款利息每戶上限 30 萬元，須先減除儲蓄投資特別扣除額。",
    "house_rent": "房屋租金支出扣除額每戶上限 18 萬元，適用條件請以財政部最新規定為準。",
    "nhi_supplement": "二代健保補充保費：單筆股利、利息達 2 萬元時扣繳 2.11%，可列入保險費扣除（健保部分）。",
}


def tax_summary(db: Database, year: int) -> dict:
    start, end = f"{year}-01-01", f"{year}-12-31"
    incomes, deductions = [], []
    for kind, dest in (("income", incomes), ("expense", deductions)):
        totals: dict[str, dict] = {}
        for c in db.category_totals(start, end, kind):
            tag = c.get("tax_tag") or ""
            if not tag:
                continue
            t = totals.setdefault(tag, {"tag": tag, "label": TAX_TAGS[tag], "amount": 0.0,
                                        "categories": [], "note": TAX_NOTES.get(tag, "")})
            t["amount"] += c["total"]
            t["categories"].append(f"{c['name']} {c['total']:,.0f}")
        for t in totals.values():
            t["amount"] = money_round(t["amount"])
            dest.append(t)
    realized = db.realized_totals(start, end)
    return {"year": year, "incomes": incomes, "deductions": deductions, "realized": realized,
            "realized_note": "證券交易所得目前停徵所得稅（僅賣出時課徵證券交易稅），此金額僅供參考。"}


# ====================================================================== 退休規劃
def retirement_defaults(db: Database) -> dict:
    today = _dt.date.today()
    mk = last_n_months(12, today)
    start = month_start(mk[0])
    exp = db.income_expense_totals(start, today.isoformat())["expense"]
    pension = 0.0
    for c in db.category_totals(start, today.isoformat(), "income"):
        if c.get("tax_tag") in ("pension",) or c["name"] in ("退休金", "年金"):
            pension += c["total"]
    nw = db.net_worth()
    real_estate = sum(a["base_value"] for a in db.account_summaries(include_archived=True)
                      if a["category"] == "不動產")
    saved = db.get_json("retire_params", {}) or {}
    by = db.get_setting("birth_year")
    params = {
        "age": (today.year - int(by)) if by.isdigit() else 65,
        "life": 95,
        "monthly_expense": round(exp / 12) if exp else 30000,
        "monthly_income": round(pension / 12) if pension else 0,
        "return_rate": 3.0,
        "inflation": 2.0,
        "assets": round(nw["net"] - real_estate),
        "exclude_real_estate": True,
        "net_worth": nw["net"],
        "real_estate": real_estate,
    }
    params["pension_growth"] = 1.0
    for k in ("life", "return_rate", "inflation", "exclude_real_estate", "pension_growth"):
        if k in saved:
            params[k] = saved[k]
    for k in ("monthly_expense", "monthly_income"):
        if saved.get(k + "_manual"):
            params[k] = saved[k]
            params[k + "_manual"] = True
    return params


def retirement_projection(age: int, life: int, assets: float, monthly_expense: float,
                          monthly_income: float, return_rate: float, inflation: float,
                          pension_growth: float | None = None) -> dict:
    """pension_growth：退休金每年調幅（%），未指定時為通膨率的一半。"""
    pg = inflation / 2 if pension_growth is None else pension_growth
    rows = []
    bal = float(assets)
    exp = monthly_expense * 12
    inc = monthly_income * 12
    depleted_age = None
    for i, a in enumerate(range(age, life + 1)):
        start = bal
        ret = max(start, 0) * return_rate / 100
        bal = start + ret + inc - exp
        deflator = (1 + inflation / 100) ** (i + 1)
        rows.append({"age": a, "start": money_round(start), "income": money_round(inc),
                     "expense": money_round(exp), "return": money_round(ret), "end": money_round(bal),
                     "real_end": money_round(bal / deflator)})
        if bal < 0 and depleted_age is None:
            depleted_age = a
        exp *= 1 + inflation / 100
        inc *= 1 + pg / 100
    gap = monthly_expense - monthly_income
    sustainable = None
    # 以二分法估算「可安心支用的每月金額」（資產用到預估壽命）
    lo, hi = 0.0, max(monthly_expense * 5, 100000.0)
    for _ in range(40):
        mid = (lo + hi) / 2
        b = float(assets)
        e = mid * 12
        n = monthly_income * 12
        ok = True
        for _a in range(age, life + 1):
            b = b + max(b, 0) * return_rate / 100 + n - e
            if b < 0:
                ok = False
                break
            e *= 1 + inflation / 100
            n *= 1 + pg / 100
        lo, hi = (mid, hi) if ok else (lo, mid)
    sustainable = money_round(lo)
    return {"rows": rows, "depleted_age": depleted_age, "monthly_gap": money_round(gap),
            "sustainable_monthly": sustainable, "final": rows[-1]["end"] if rows else 0,
            "final_real": rows[-1]["real_end"] if rows else 0,
            "real_return": (1 + return_rate / 100) / (1 + inflation / 100) - 1}


DEFAULT_TARGETS = {"現金": 5, "銀行存款": 15, "定期存款": 25, "外幣存款": 10, "短期投資": 15,
                   "長期投資": 10, "基金": 10, "債券": 10}


def allocation_vs_target(db: Database) -> list[dict]:
    targets = db.get_json("allocation_targets", None) or DEFAULT_TARGETS
    actual = dict(db.allocation_by_category())
    total = sum(v for v in actual.values() if v > 0) or 1
    rows = []
    for cat in sorted(set(targets) | set(actual), key=lambda k: -(actual.get(k, 0))):
        a = actual.get(cat, 0.0)
        t = float(targets.get(cat, 0))
        rows.append({"category": cat, "amount": money_round(a), "actual_pct": a / total * 100,
                     "target_pct": t, "diff_pct": a / total * 100 - t,
                     "rebalance": money_round(t / 100 * total - a)})
    return rows
