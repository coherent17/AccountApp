"""投資績效：總報酬率與年化報酬率（XIRR，內部報酬率）。不需要 Qt。

現金流量（以投資人角度，投入為負、收回為正）：
* 買進（含分錄買進）：－成本（含手續費）
* 賣出（含分錄賣出）：＋實收淨價款
* 現金股利：＋股利（扣除二代健保補充保費後的淨額）；分錄股利以分錄金額計
* 期末：＋帳面價值（成本＋已認列評價，即投資帳戶餘額）
股票股利沒有現金流量（只增加股數）。

總損益＝收回＋期末帳面價值－投入＝已實現損益＋股利＋未實現損益。
年化報酬率以 XIRR 計算；持有未滿一年時不年化（避免短期漲跌被放大成誤導的年報酬），只顯示總報酬率。
外幣標的以帳戶目前匯率換算為本位幣後合併計算投資組合。
"""

from __future__ import annotations

import datetime as _dt

MIN_YEARS = 1.0       # 持有滿一年才計算年化報酬率


def _d(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def xirr(flows: list[tuple[str, float]]) -> float | None:
    """內部報酬率（年化）。flows：[(日期, 金額)]，至少要有一筆負數與一筆正數。"""
    flows = [(d, a) for d, a in flows if abs(a) >= 0.005]
    if not flows or not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    t0 = min(_d(d) for d, _ in flows)
    pts = [((_d(d) - t0).days / 365.0, a) for d, a in flows]

    def npv(r: float) -> float:
        return sum(a / (1 + r) ** t for t, a in pts)

    # 二分法：NPV 對 r 單調遞減（先投入後收回的一般情形），在 (-99.99%, 1000000%) 間找根
    lo, hi = -0.9999, 10000.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7 or hi - lo < 1e-10:
            return mid
        if (f_mid > 0) == (f_lo > 0):
            lo, f_lo = mid, f_mid
        else:
            hi = mid
    return (lo + hi) / 2


def _summarize(flows: list[tuple[str, float]], value: float, as_of: str) -> dict:
    invested = -sum(a for _, a in flows if a < 0)
    returned = sum(a for _, a in flows if a > 0)
    gain = returned + value - invested
    first = min((d for d, _ in flows), default="")
    years = (_d(as_of) - _d(first)).days / 365.0 if first else 0.0
    rate = None
    if first and years >= MIN_YEARS:
        rate = xirr(flows + ([(as_of, value)] if abs(value) >= 0.005 else []))
    return {"invested": round(invested, 2), "returned": round(returned, 2), "value": round(value, 2),
            "gain": round(gain, 2), "total_return": gain / invested if invested > 0.005 else None,
            "first_date": first, "years": years, "xirr": rate}


def security_performance(inv, sec: dict, as_of: str | None = None) -> dict:
    """單一標的的績效（原幣）。"""
    as_of = as_of or _dt.date.today().isoformat()
    st = inv.replay(sec["id"], as_of)
    out = _summarize(st["flows"], st["market_value"], as_of)
    out.update({"id": sec["id"], "code": sec["code"], "name": sec["name"], "currency": sec["currency"],
                "shares": st["shares"], "cost": st["cost"],
                "realized": round(sum(r["gain"] for r in st["realized"]), 2),
                "dividends": round(sum(d["amount"] - d["nhi"] for d in st["dividends"]), 2),
                "unrealized": st["unrealized"], "flows": st["flows"]})
    return out


def portfolio_performance(inv, as_of: str | None = None) -> dict:
    """每個標的的績效，加上以本位幣合併的投資組合績效。"""
    as_of = as_of or _dt.date.today().isoformat()
    rates = {r["id"]: r["rate"] or 1.0 for r in inv.db._q("SELECT id, rate FROM accounts")}
    rows, flows, value = [], [], 0.0
    tot = {"realized": 0.0, "dividends": 0.0, "unrealized": 0.0}
    for sec in inv.list_securities(include_archived=True):
        p = security_performance(inv, sec, as_of)
        if not p["first_date"]:
            continue          # 截至此日尚無任何交易
        rate = rates.get(sec["account_id"], 1.0)
        flows += [(d, a * rate) for d, a in p["flows"]]
        value += p["value"] * rate
        for k in tot:
            tot[k] += p[k] * rate
        p["rate"] = rate
        rows.append(p)
    total = _summarize(flows, value, as_of)
    total.update({k: round(v, 2) for k, v in tot.items()})
    return {"as_of": as_of, "rows": rows, "total": total}
