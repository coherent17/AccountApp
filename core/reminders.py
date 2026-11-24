"""到期提醒中心：把接下來會發生的事排成一條時間軸。

來源：
* 她自己設定的提醒（保單繳費、信用卡繳款、除息日…），存在設定 reminders（JSON 清單，不需要改資料表）；
* 定存到期（帳戶的到期日）；
* 定期交易的下一次入帳日；
* 每年 5 月的綜合所得稅申報。
"""

from __future__ import annotations

import calendar
import datetime as _dt
import uuid

from .database import Database

KINDS = {"insurance": "保單繳費", "card": "信用卡繳款", "tax": "稅費", "dividend": "除息／配息", "other": "其他"}
FREQS = {"once": "一次", "monthly": "每月", "yearly": "每年"}
KEY = "reminders"


def _clamp(y: int, m: int, d: int) -> _dt.date:
    return _dt.date(y, m, min(d, calendar.monthrange(y, m)[1]))


def list_custom(db: Database) -> list[dict]:
    items = db.get_json(KEY, [])
    return [i for i in items if isinstance(i, dict) and i.get("id") and i.get("date")] if isinstance(items, list) else []


def save_custom(db: Database, item: dict) -> dict:
    title = (item.get("title") or "").strip()
    if not title:
        raise ValueError("請輸入提醒的名稱，例如：國泰人壽保費")
    try:
        _dt.date.fromisoformat(item.get("date") or "")
    except ValueError:
        raise ValueError("請選擇日期") from None
    kind = item.get("kind") if item.get("kind") in KINDS else "other"
    freq = item.get("freq") if item.get("freq") in FREQS else "once"
    amount = item.get("amount")
    lead = item.get("lead")
    clean = {"id": item.get("id") or uuid.uuid4().hex[:10], "title": title, "kind": kind, "freq": freq,
             "date": item["date"], "amount": float(amount) if amount not in (None, "") else None,
             "lead": int(lead) if lead not in (None, "") else 7, "note": (item.get("note") or "").strip(),
             "account_id": int(item["account_id"]) if item.get("account_id") else None}   # 付款（或入帳）帳戶：納入現金流預測
    if not 0 <= clean["lead"] <= 60:
        raise ValueError("提前提醒的天數請設定在 0～60 天")
    items = [i for i in list_custom(db) if i["id"] != clean["id"]]
    items.append(clean)
    items.sort(key=lambda i: i["date"])
    db.set_json(KEY, items)
    return clean


def delete_custom(db: Database, rid: str) -> None:
    db.set_json(KEY, [i for i in list_custom(db) if i["id"] != rid])


def occurrences(item: dict, start: _dt.date, end: _dt.date) -> list[_dt.date]:
    """這個提醒在 start～end 之間的日期。"""
    first = _dt.date.fromisoformat(item["date"])
    if item["freq"] == "once":
        return [first] if start <= first <= end else []
    out = []
    if item["freq"] == "monthly":
        y, m = start.year, start.month
        while True:
            d = _clamp(y, m, first.day)
            if d > end:
                break
            if d >= start and d >= first:
                out.append(d)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    else:   # yearly
        for y in range(start.year, end.year + 1):
            d = _clamp(y, first.month, first.day)
            if start <= d <= end and d >= first:
                out.append(d)
    return out


def _when(days: int) -> str:
    if days == 0:
        return "今天"
    if days == 1:
        return "明天"
    return f"已過 {-days} 天" if days < 0 else f"{days} 天後"


def upcoming(db: Database, days: int = 60, today: _dt.date | None = None) -> list[dict]:
    """接下來 days 天內的事（含剛過期 7 天內的定存），依日期排序。"""
    today = today or _dt.date.today()
    end = today + _dt.timedelta(days=days)
    out: list[dict] = []

    def add(date: _dt.date, kind: str, title: str, sub: str = "", amount=None, currency=None, lead: int = 7, **extra):
        d = (date - today).days
        out.append({"date": date.isoformat(), "days_left": d, "when": _when(d), "kind": kind, "title": title,
                    "sub": sub, "amount": amount, "currency": currency or db.base_currency,
                    "urgent": d <= lead, **extra})

    for item in list_custom(db):
        for d in occurrences(item, today, end):
            add(d, item["kind"], item["title"], item["note"] or KINDS[item["kind"]], item["amount"], lead=item["lead"],
                source="custom", id=item["id"], lead_days=item["lead"])
    for a in db.upcoming_maturities(days, today.isoformat()):
        if a["days_left"] >= -7:
            add(_dt.date.fromisoformat(a["maturity_date"]), "maturity", f"{a['name']} 到期", "到期後記得續存或轉入活存",
                a["balance"], a["currency"], source="account", account_id=a["id"], interest=a.get("est_interest") or 0)
    for rec in db.list_recurring():
        if not rec["active"]:
            continue
        for ds in db.recurring_dates(rec, end.isoformat()):
            dd = _dt.date.fromisoformat(ds)
            if dd >= today:
                add(dd, "recurring", rec["name"], "定期交易", rec["data"].get("amount"), lead=3,
                    source="recurring", rec_id=rec["id"])
                break       # 每一筆只列下一次
    for y in (today.year, today.year + 1):
        s, e = _dt.date(y, 5, 1), _dt.date(y, 5, 31)
        if today <= s <= end:
            add(s, "tax", f"{y} 年綜合所得稅申報開始", f"申報 {y - 1} 年度所得；可先到「財務報表 → 報稅彙總」整理", lead=14,
                source="tax", year=y - 1)
        if today <= e <= end:
            add(e, "tax", f"{y} 年綜合所得稅申報截止", f"申報 {y - 1} 年度所得", lead=10, source="tax", year=y - 1)
    out.sort(key=lambda x: (x["date"], x["title"]))
    return out
