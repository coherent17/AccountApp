"""總覽頁的資料。"""

from __future__ import annotations

import datetime as dt

from app.database import TYPE_LABELS, last_n_months, month_end, month_start, voucher_no

from v3.rpc import exposed


class DashboardApi:
    @exposed
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
        from app import backup
        bk = backup.status(db)
        if bk["remind"]:
            when = f"上次成功是 {bk['days']} 天前" if bk["days"] is not None else "還沒有成功備份過"
            reminders.append({"kind": "backup", "text": f"第二份備份（隨身碟／OneDrive）{when}，請插上隨身碟後按「立即備份」。",
                              "action": "立即備份"})
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
            "sample": db.get_setting("sample_data") == "1",
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
