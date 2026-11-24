"""現金流預測：依定期交易與「指定付款帳戶」的提醒，推算各個存款帳戶未來幾個月的餘額。

只讀取資料，不產生傳票。計算以帶號餘額進行（資產為正、負債為負），顯示時負債改為欠款正數。
* 定期交易：每一次預定入帳（已到期還沒入帳的視為今天入帳）。
* 自己設定的提醒：有金額、也指定了帳戶的才納入（除息／配息為收入，其餘為支出）。
* 定存到期只列在事件裡，不改變餘額（續存或轉入哪個帳戶由她決定）。
"""

from __future__ import annotations

import calendar
import datetime as _dt

from . import reminders
from .database import Database, money_round

LIQUID = {"現金", "銀行存款", "外幣存款", "信用卡"}
LOW_KEY = "forecast_low"


def _add_months(d: _dt.date, n: int) -> _dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    return _dt.date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def low_line(db: Database) -> float:
    try:
        return float(db.get_setting(LOW_KEY) or 10000)
    except ValueError:
        return 10000.0


def forecast(db: Database, months: int = 6, today: _dt.date | None = None) -> dict:
    today = today or _dt.date.today()
    end = _add_months(today, months)
    accs = {a["id"]: a for a in db.account_summaries()}
    moves: list[dict] = []      # {date, title, account_id, delta（帶號、帳戶幣別）, kind}

    def move(date: _dt.date, title: str, aid, delta: float, kind: str):
        if aid in accs and abs(delta) >= 0.005:
            moves.append({"date": max(date, today).isoformat(), "title": title, "account_id": aid,
                          "delta": delta, "kind": kind, "overdue": date < today})

    for rec in db.list_recurring():
        if not rec["active"]:
            continue
        d = rec["data"]
        amt = float(d.get("amount") or 0)
        for ds in db.recurring_dates(rec, end.isoformat()):
            day = _dt.date.fromisoformat(ds)
            if d["type"] == "income":
                move(day, rec["name"], d.get("account_id"), amt, "recurring")
            elif d["type"] == "expense":
                move(day, rec["name"], d.get("account_id"), -amt, "recurring")
            elif d["type"] == "transfer":
                src, dst = accs.get(d.get("account_id")), accs.get(d.get("to_account_id"))
                move(day, rec["name"], d.get("account_id"), -amt, "recurring")
                if src and dst:
                    move(day, rec["name"], dst["id"], amt * src["rate"] / (dst["rate"] or 1), "recurring")
    for item in reminders.list_custom(db):
        if item.get("amount") and item.get("account_id"):
            sign = 1 if item["kind"] == "dividend" else -1
            for day in reminders.occurrences(item, today, end):
                move(day, item["title"], item["account_id"], sign * item["amount"], item["kind"])

    used = {m["account_id"] for m in moves}
    shown = [a for a in accs.values() if not a["archived"] and (a["category"] in LIQUID or a["id"] in used)
             and a["category"] not in ("短期投資", "長期投資", "股票", "基金", "債券")]
    low = low_line(db)
    moves.sort(key=lambda m: (m["date"], -m["delta"]))
    signed = {a["id"]: a["signed"] for a in shown}
    events = []
    for m in moves:
        if m["account_id"] not in signed:
            continue
        a = accs[m["account_id"]]
        signed[a["id"]] += m["delta"]
        view = 1 if a["kind"] == "asset" else -1
        events.append({"date": m["date"], "title": m["title"], "account_id": a["id"], "account": a["name"],
                       "currency": a["currency"], "kind": m["kind"], "overdue": m["overdue"],
                       "amount": money_round(m["delta"] * view), "balance": money_round(signed[a["id"]] * view),
                       "inflow": m["delta"] > 0})

    weeks = []
    d = today
    while d <= end:
        weeks.append(d.isoformat())
        d += _dt.timedelta(days=7)
    if weeks[-1] != end.isoformat():
        weeks.append(end.isoformat())
    out = []
    for a in sorted(shown, key=lambda x: (x["kind"] != "asset", x["code"] or "", x["name"])):
        view = 1 if a["kind"] == "asset" else -1
        evs = [e for e in events if e["account_id"] == a["id"]]
        start = money_round(a["signed"] * view)
        series, bal, i = [], start, 0
        for w in weeks:
            while i < len(evs) and evs[i]["date"] <= w:
                bal = evs[i]["balance"]
                i += 1
            series.append(bal)
        low_pt = min([(start, today.isoformat())] + [(e["balance"], e["date"]) for e in evs])
        thr = low * (1 / (a["rate"] or 1))          # 低水位以本位幣設定，換成帳戶幣別
        warn = a["kind"] == "asset" and low_pt[0] < thr
        reason = ""
        if warn:
            hit = next((e for e in evs if e["balance"] == low_pt[0] and e["date"] == low_pt[1]), None)
            reason = f"{hit['title']}之後" if hit else ""
        out.append({"id": a["id"], "name": a["name"], "kind": a["kind"], "currency": a["currency"],
                    "start": start, "end": bal, "min": low_pt[0], "min_date": low_pt[1], "warn": warn,
                    "negative": a["kind"] == "asset" and low_pt[0] < 0, "reason": reason, "series": series,
                    "events": len(evs)})
    maturities = [{"date": x["maturity_date"], "title": f"{x['name']} 到期", "amount": x["balance"], "currency": x["currency"]}
                  for x in db.upcoming_maturities((end - today).days, today.isoformat()) if x["days_left"] >= 0]
    return {"today": today.isoformat(), "end": end.isoformat(), "months": months, "low": low, "weeks": weeks,
            "accounts": out, "events": events, "maturities": maturities,
            "warnings": [a for a in out if a["warn"]]}
