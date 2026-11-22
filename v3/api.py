"""v3 試作：畫面（HTML/JS）透過 pywebview 呼叫的 Python 介面。

帳務計算全部沿用 v2 的 app/ 模組（database、statements…），這裡只把資料整理成畫面需要的格式。
傳回的金額都是數字，格式化（千分位、幣別符號、正負號）在畫面上做。
"""

from __future__ import annotations

import datetime as dt
import functools
from concurrent.futures import ThreadPoolExecutor

from app.database import (CURRENCIES, TYPE_LABELS, ZERO_DECIMAL_CURRENCIES, Database, last_n_months,
                          month_end, month_start, voucher_no)


class DbThread:
    """SQLite 連線只能在建立它的執行緒使用；pywebview 卻會在不同的執行緒呼叫 API。
    所以帳本的開啟與所有讀寫都交給同一個專用執行緒，一次一件、依序執行（v2 的 Database 不需修改）。"""

    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ledger-db")

    def run(self, fn, *args, **kwargs):
        return self._pool.submit(fn, *args, **kwargs).result()

    def close(self) -> None:
        self._pool.shutdown(wait=True)


def on_db_thread(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        return self._dbt.run(method, self, *args, **kwargs)
    return wrapper


class Api:
    def __init__(self, dbt: DbThread, db: Database, demo: bool):
        self._dbt = dbt
        self._db = db
        self._demo = demo

    @on_db_thread
    def meta(self) -> dict:
        db = self._db
        return {
            "base": db.base_currency,
            "currencies": {k: {"name": v[0], "symbol": v[1], "decimals": 0 if k in ZERO_DECIMAL_CURRENCIES else 2}
                           for k, v in CURRENCIES.items()},
            "owner": db.get_setting("owner_name"),
            "demo": self._demo,
            "sample": db.get_setting("sample_data") == "1",
            "theme": db.get_setting("theme_mode", "light"),
            "font_scale": db.get_setting("font_scale", "large"),
        }

    @on_db_thread
    def set_pref(self, key: str, value: str) -> bool:
        """外觀偏好（深色模式、字型大小）：與 v2 共用同一個設定鍵，切換立即生效、不用重開。"""
        if key not in ("theme_mode", "font_scale"):
            return False
        self._db.set_setting(key, value)
        return True

    @on_db_thread
    def dashboard(self) -> dict:
        db = self._db
        today = dt.date.today()
        ym = today.strftime("%Y-%m")
        prev_ym = last_n_months(2)[0]
        nw = db.net_worth()
        m = db.income_expense_totals(month_start(ym), month_end(ym))
        pm = db.income_expense_totals(month_start(prev_ym), month_end(prev_ym))
        r = db.ratios(today.isoformat())
        months = last_n_months(12)
        mt = db.monthly_totals(month_start(months[0]), month_end(months[-1]))
        series = db.net_worth_series(months)
        spent = {c["id"]: c["total"] for c in db.category_totals(month_start(ym), month_end(ym), "expense")}
        budgets = [{"name": c["name"], "budget": c["budget"], "used": spent.get(c["id"], 0.0)}
                   for c in db.list_categories("expense") if c["budget"] > 0][:7]
        due = db.due_recurring()
        reminders = []
        if due:
            names = "、".join(dict.fromkeys(rec["name"] for rec, _ in due))
            reminders.append({"kind": "due", "text": f"有 {len(due)} 筆定期交易已到期：{names}", "action": "確認入帳"})
        for a in db.upcoming_maturities(60)[:5]:
            d = a["days_left"]
            when = "今天到期" if d == 0 else (f"已到期 {-d} 天" if d < 0 else f"剩 {d} 天")
            reminders.append({"kind": "maturity", "urgent": d <= 7, "name": a["name"], "date": a["maturity_date"],
                              "when": when, "amount": a["balance"], "currency": a["currency"],
                              "interest": a["est_interest"]})
        recent = []
        for t in db.query_transactions(limit=8):
            signed = -t["amount"] if t["type"] == "expense" else t["amount"]
            cat = t["category_name"] or ("→ " + (t["to_account_name"] or "") if t["type"] == "transfer" else "評價調整")
            recent.append({"id": t["id"], "voucher": voucher_no(t["id"]), "date": t["date"], "type": t["type"],
                           "type_label": TYPE_LABELS[t["type"]], "category": cat, "account": t["account_name"] or "",
                           "note": t["note"], "amount": signed, "currency": t["currency"],
                           "signed": t["type"] != "transfer", "tags": t.get("tags", [])})
        return {
            "today": today.isoformat(),
            "net": nw["net"], "assets": nw["assets"], "liabilities": nw["liabilities"],
            "month": {"income": m["income"], "expense": m["expense"], "net": m["net"]},
            "prev_month": {"income": pm["income"], "expense": pm["expense"]},
            "ratios": {k: r[k] for k in ("debt_ratio", "current_ratio", "emergency_months", "savings_rate")},
            "allocation": [{"name": n, "value": v} for n, v in db.allocation_by_category()],
            "months": months,
            "monthly": [{"income": mt[k]["income"], "expense": mt[k]["expense"]} for k in months],
            "net_series": [s["net"] for s in series],
            "budgets": budgets,
            "reminders": reminders,
            "recent": recent,
        }
