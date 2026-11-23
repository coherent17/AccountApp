"""比較財務報表與財務比率（畫面與列印共用）。

比較方式：
* 與上一期比較：資產負債表比較「本期期初」（期間開始的前一天）；收支損益表比較長度相同的前一期
  （整月的期間往前推相同月數，例如本月 ↔ 上月、今年 ↔ 去年；其他期間往前推相同天數）。
* 與去年同期比較：日期都往前推一年。
"""

from __future__ import annotations

import datetime as _dt

from .database import ADJUST_ACCOUNT, FX_ACCOUNT, REALIZED_ACCOUNT, money_round

COMPARE_MODES = [("none", "不比較"), ("prior_period", "與上一期比較"), ("prior_year", "與去年同期比較")]


def _d(s: str) -> _dt.date:
    return _dt.date.fromisoformat(s)


def shift_year(iso: str, years: int = 1) -> str:
    y, m, d = int(iso[:4]) - years, int(iso[5:7]), int(iso[8:10])
    if m == 2 and d == 29:
        d = 28
    return f"{y:04d}-{m:02d}-{d:02d}"


def _add_months(d: _dt.date, n: int) -> _dt.date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return _dt.date(y, m + 1, 1)


def previous_period(start: str, end: str) -> tuple[str, str]:
    """長度相同、緊接在前的一期。"""
    s, e = _d(start), _d(end)
    nxt = e + _dt.timedelta(days=1)
    if s.day == 1 and nxt.day == 1:     # 整月：往前推相同月數
        months = (nxt.year - s.year) * 12 + nxt.month - s.month
        return _add_months(s, -months).isoformat(), (s - _dt.timedelta(days=1)).isoformat()
    days = (e - s).days + 1
    pe = s - _dt.timedelta(days=1)
    return (pe - _dt.timedelta(days=days - 1)).isoformat(), pe.isoformat()


def compare_range(mode: str, start: str, end: str) -> tuple[str, str] | None:
    if mode == "prior_period":
        return previous_period(start, end)
    if mode == "prior_year":
        return shift_year(start), shift_year(end)
    return None


def compare_date(mode: str, start: str, end: str) -> str | None:
    """資產負債表的比較基準日。"""
    if mode == "prior_period":
        return (_d(start) - _dt.timedelta(days=1)).isoformat()
    if mode == "prior_year":
        return shift_year(end)
    return None


def change(cur: float | None, prev: float | None) -> tuple[float | None, float | None]:
    """增減金額與增減率（前期為 0 時沒有增減率）。"""
    if cur is None or prev is None:
        return None, None
    d = money_round(cur - prev)
    return d, (d / abs(prev) if abs(prev) >= 0.005 else None)


# ---------------------------------------------------------------------- 資產負債表
def balance_sheet(db, end: str, cend: str | None = None) -> dict:
    """比較資產負債表。rows：name、code、level、style（""/subtotal/total/grand/section/blank）、
    cur、prev（不比較時為 None）、orig（外幣原幣金額）、currency、share（占總資產）。"""
    b = db.balance_sheet(end)
    p = db.balance_sheet(cend) if cend else None
    base = db.base_currency
    total = b["assets"] or 1
    rows: list[dict] = []

    def row(name, cur, prev=None, level=1, style="", **kw):
        rows.append({"name": name, "cur": cur, "prev": prev if p else None, "level": level, "style": style,
                     "share": (cur / total) if cur is not None and style != "section" else None,
                     "orig": kw.get("orig"), "currency": kw.get("currency", base), "code": kw.get("code", "")})

    def group(name: str, sign: int):
        cur = {a["id"]: a for a in b["groups"][name]}
        prev = {a["id"]: a for a in p["groups"][name]} if p else {}
        rows.append({"name": name, "cur": None, "prev": None, "level": 1, "style": "subtotal",
                     "share": None, "orig": None, "currency": base, "code": ""})
        for aid in sorted(set(cur) | set(prev), key=lambda i: (cur.get(i) or prev.get(i))["code"]):
            a = cur.get(aid) or prev[aid]
            v = cur[aid]["base_value"] * sign if aid in cur else 0.0
            pv = prev[aid]["base_value"] * sign if aid in prev else 0.0
            orig = cur[aid]["balance"] if aid in cur and a["currency"] != base else None
            row(f"{a['code']}　{a['name']}（{a['category']}）", v, pv, 2, orig=orig, currency=a["currency"],
                code=a["code"])
        row(f"{name}合計", b["totals"][name], p["totals"][name] if p else None, 1, "subtotal")

    rows.append({"name": "資產", "level": 0, "style": "section", "cur": None, "prev": None, "share": None,
                 "orig": None, "currency": base, "code": ""})
    group("流動資產", 1)
    group("非流動資產", 1)
    row("資產總計", b["assets"], p["assets"] if p else None, 0, "total")
    rows.append({"name": "", "level": 0, "style": "blank", "cur": None, "prev": None, "share": None,
                 "orig": None, "currency": base, "code": ""})
    rows.append({"name": "負債及淨值", "level": 0, "style": "section", "cur": None, "prev": None, "share": None,
                 "orig": None, "currency": base, "code": ""})
    group("流動負債", -1)
    group("非流動負債", -1)
    row("負債總計", b["liabilities"], p["liabilities"] if p else None, 0, "total")
    row("淨資產（業主權益）", b["net"], p["net"] if p else None, 0, "total")
    row("負債及淨值總計", money_round(b["liabilities"] + b["net"]),
        money_round(p["liabilities"] + p["net"]) if p else None, 0, "grand")
    rows[-1]["share"] = None
    return {"date": end, "cdate": cend, "rows": rows, "bs": b, "prev": p}


# ---------------------------------------------------------------------- 收支損益表
def income_statement(db, start: str, end: str, crange: tuple[str, str] | None = None) -> dict:
    """比較收支損益表。rows：name、code、count、level、style、cur、prev、share（占收入比）、kind。"""
    s = db.income_statement(start, end)
    p = db.income_statement(*crange) if crange else None
    codes = db.category_codes()
    ti = s["total_income"] or None
    rows: list[dict] = []

    def row(name, cur, prev, level=2, style="", count="", code="", kind=""):
        rows.append({"name": name, "cur": cur, "prev": prev if p else None, "level": level, "style": style,
                     "count": count, "code": code, "kind": kind,
                     "share": cur / ti if ti and cur is not None else None})

    def section(name):
        rows.append({"name": name, "cur": None, "prev": None, "level": 0, "style": "section", "count": "",
                     "code": "", "kind": "", "share": None})

    for title, key, total_key, kind in (("收入", "income", "total_income", "income"),
                                        ("支出（費用）", "expense", "total_expense", "expense")):
        section(title)
        cur = {c["id"]: c for c in s[key]}
        prev = {c["id"]: c for c in p[key]} if p else {}
        order = [c["id"] for c in s[key]] + [i for i in prev if i not in cur]
        for cid in order:
            c = cur.get(cid) or prev[cid]
            row(c["name"], cur[cid]["total"] if cid in cur else 0.0, prev[cid]["total"] if cid in prev else 0.0,
                count=str(cur[cid]["count"]) if cid in cur else "0", code=codes.get(cid, ""), kind=kind)
        row(f"{title[:2]}合計", s[total_key], p[total_key] if p else None, 1, "subtotal", kind=kind)
    row("本期收支結餘", s["operating"], p["operating"] if p else None, 0, "total")
    section("業外損益")
    row(f"{REALIZED_ACCOUNT}（證券買賣）", s["realized"], p["realized"] if p else None)
    row(f"{ADJUST_ACCOUNT}（市值變動）", s["adjust"], p["adjust"] if p else None)
    row(f"{FX_ACCOUNT}（匯率變動）", s["fx"], p["fx"] if p else None)
    row("本期綜合損益（淨資產增減）", s["comprehensive"], p["comprehensive"] if p else None, 0, "grand")
    return {"start": start, "end": end, "crange": crange, "rows": rows, "is": s, "prev": p}


# ---------------------------------------------------------------------- 財務比率
RATIO_HELP = {
    "負債比率": "負債 ÷ 資產，越低表示財務越穩健",
    "流動比率": "流動資產 ÷ 流動負債，大於 1 倍表示短期內有足夠資金償還短期負債",
    "流動資產占比": "流動資產 ÷ 資產",
    "緊急預備金": "現金及約當現金 ÷ 近 12 個月平均月支出，一般建議 6 個月以上",
    "近 12 個月儲蓄率": "（收入－支出）÷ 收入，以基準日前 12 個月計算",
    "本期儲蓄率": "報表期間的（收入－支出）÷ 收入",
    "投資組合總報酬率": "（已實現損益＋股利＋未實現損益）÷ 投入金額，自開始投資起累計",
    "投資組合年化報酬率": "XIRR（內部報酬率），考慮每筆投入、收回與股利的時間；持有未滿一年不年化",
}


def _period_ratios(db, start: str, end: str) -> dict:
    from .investments import Investments
    from .performance import portfolio_performance
    r = db.ratios(end)
    ie = db.income_expense_totals(start, end)
    # 投資績效算到報表期末或今天（較早者），不把尚未發生的持有期間算進去
    perf = portfolio_performance(Investments(db), min(end, _dt.date.today().isoformat()))["total"]
    return {
        "負債比率": (r["debt_ratio"], "pct"),
        "流動比率": (r["current_ratio"], "times"),
        "流動資產占比": (r["liquid_ratio"], "pct"),
        "緊急預備金": (r["emergency_months"], "months"),
        "近 12 個月儲蓄率": (r["savings_rate"], "pct"),
        "本期儲蓄率": (ie["net"] / ie["income"] if ie["income"] else None, "pct"),
        "投資組合總報酬率": (perf["total_return"], "pct"),
        "投資組合年化報酬率": (perf["xirr"], "pct"),
        "_years": perf["years"],
    }


def ratios(db, start: str, end: str, crange: tuple[str, str] | None = None) -> list[dict]:
    """財務比率（本期與比較期）。每列：name、kind（pct/times/months）、cur、prev、help、note。"""
    cur = _period_ratios(db, start, end)
    prev = _period_ratios(db, *crange) if crange else None
    out = []
    for name, help_ in RATIO_HELP.items():
        v, kind = cur[name]
        note = ""
        if name == "投資組合年化報酬率" and v is None:
            note = "未滿一年" if 0 < cur["_years"] < 1 else ""
        out.append({"name": name, "kind": kind, "cur": v, "prev": prev[name][0] if prev else None,
                    "help": help_, "note": note})
    return out


def fmt_ratio(v: float | None, kind: str, note: str = "") -> str:
    if v is None:
        return note or "—"
    if kind == "pct":
        return f"{v:.1%}"
    if kind == "times":
        return f"{v:.2f} 倍"
    return f"{v:.1f} 個月"


def fmt_ratio_change(cur: float | None, prev: float | None, kind: str) -> str:
    if cur is None or prev is None:
        return "—"
    d = cur - prev
    if kind == "pct":
        return f"{d * 100:+.1f} 個百分點"
    if kind == "times":
        return f"{d:+.2f} 倍"
    return f"{d:+.1f} 個月"
