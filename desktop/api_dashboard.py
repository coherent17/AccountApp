"""總覽頁的資料。"""

from __future__ import annotations

import datetime as dt

from core.database import TYPE_LABELS, last_n_months, month_end, month_start, voucher_no

from desktop.rpc import exposed


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
        from core import backup
        bk = backup.status(db)
        if bk["remind"]:
            when = f"上次成功是 {bk['days']} 天前" if bk["days"] is not None else "還沒有成功備份過"
            reminders.append({"kind": "backup", "text": f"第二份備份（隨身碟／OneDrive）{when}，請插上隨身碟後按「立即備份」。",
                              "action": "立即備份"})
        if due:
            names = "、".join(dict.fromkeys(rec["name"] for rec, _ in due))
            reminders.append({"kind": "due", "text": f"有 {len(due)} 筆定期交易已到期：{names}", "action": "確認入帳"})
        from core import monthclose, reminders as rem
        calendar = rem.upcoming(db, 60)
        for e in calendar:      # 快到的事（定存到期、保費、繳款、報稅）也放進提醒事項；定期交易由「確認入帳」處理
            if e["urgent"] and e["kind"] != "recurring" and e["days_left"] >= -7:
                reminders.append({"kind": "event", "event": e})
        from core import forecast as fc     # 現金流預測：未來 60 天內有帳戶會低於低水位
        fcst = fc.forecast(db, 3, today)
        for w in fcst["warnings"]:
            if w["min_date"] <= (today + dt.timedelta(days=60)).isoformat():
                reminders.append({"kind": "forecast", "name": w["name"], "date": w["min_date"], "min": w["min"],
                                  "currency": w["currency"], "reason": w["reason"], "negative": w["negative"],
                                  "low": fcst["low"], "action": "查看預測"})
        close_ym = monthclose.previous_month(today)
        if today.day <= 20 and not db.get_json("month_close", {}).get(close_ym, {}).get("finished") and db._q1(
                "SELECT COUNT(*) n FROM transactions WHERE void = 0 AND source = '' AND date BETWEEN ? AND ?",
                (month_start(close_ym), month_end(close_ym)))["n"]:
            reminders.append({"kind": "monthclose", "ym": close_ym,
                              "text": f"{monthclose.label(close_ym)}的月結還沒完成：對帳、評價、檢視預算，一步一步帶您完成。",
                              "action": "開始月結"})
        from core import yearclose
        yc = yearclose.reminder(db, today)
        if yc:
            reminders.append({"kind": "yearclose", "year": yc, "action": "開啟年度結帳小幫手",
                              "text": f"{yc} 年的帳還沒有結：對帳、年底評價、年度財務報告，一步一步帶您完成。"})
        recent = []
        for t in db.query_transactions(limit=8):
            signed = -t["amount"] if t["type"] == "expense" else t["amount"]
            cat = t["category_name"] or ("→ " + (t["to_account_name"] or "") if t["type"] == "transfer" else "評價調整")
            recent.append({"id": t["id"], "voucher": voucher_no(t["id"]), "date": t["date"], "type": t["type"],
                           "type_label": TYPE_LABELS[t["type"]], "category": cat, "account": t["account_name"] or "",
                           "note": t["note"], "amount": signed, "currency": t["currency"],
                           "signed": t["type"] != "transfer", "tags": t.get("tags", [])})
        # 今天記了幾筆、連續記帳天數（只算她自己記的、未作廢的傳票）
        days = {r["date"] for r in db._q("SELECT DISTINCT date FROM transactions WHERE void = 0 AND source = ''"
                                         " AND date >= ?", ((today - dt.timedelta(days=400)).isoformat(),))}
        today_count = db._q1("SELECT COUNT(*) n FROM transactions WHERE void = 0 AND source = '' AND date = ?",
                             (today.isoformat(),))["n"]
        streak, day = 0, today if today.isoformat() in days else today - dt.timedelta(days=1)
        while day.isoformat() in days:
            streak += 1
            day -= dt.timedelta(days=1)
        # 本月支出排行與上月比較
        prev_spent = {c["id"]: c["total"] for c in db.category_totals(month_start(prev_ym), month_end(prev_ym), "expense")}
        cats = db.category_totals(month_start(ym), month_end(ym), "expense")
        total_exp = sum(c["total"] for c in cats) or 1
        ranking = [{"id": c["id"], "name": c["name"], "total": c["total"], "share": c["total"] / total_exp,
                    "count": c["count"], "prev": prev_spent.get(c["id"], 0.0)} for c in cats[:6]]
        budgets_all = {c["id"]: c for c in db.list_categories("expense") if c["budget"] > 0}
        over = [budgets_all[i]["name"] for i, v in spent.items() if i in budgets_all and v > budgets_all[i]["budget"]]
        insights = self._insights(m, pm, ranking, over, db.upcoming_maturities(60), today, r)
        return {
            "today": today.isoformat(), "today_count": today_count, "streak": streak,
            "ranking": ranking, "insights": insights,
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
            "calendar": calendar[:10],
            "recent": recent,
        }

    @staticmethod
    def _insights(m, pm, ranking, over, mats, today, r) -> list[dict]:
        """本月洞察：用一句白話說出值得注意的事（最多 5 則）。tone：good／warn／info。"""
        out = []
        if pm["expense"] and m["expense"]:
            d = (m["expense"] - pm["expense"]) / pm["expense"]
            if abs(d) >= 0.05:
                word = "少" if d < 0 else "多"
                out.append({"icon": "trend_down" if d < 0 else "trend_up", "tone": "good" if d < 0 else "warn",
                            "text": f"本月支出比上個月{word} {abs(d):.0%}", "sub": "到目前為止的金額，月底前還會變動" if d < 0 else ""})
        if ranking:
            top = ranking[0]
            out.append({"icon": "pie", "tone": "info", "category": top["name"],
                        "text": f"「{top['name']}」是本月最大的支出，占 {top['share']:.0%}",
                        "sub": f"共 {top['count']} 筆"})
        for name in over[:2]:
            out.append({"icon": "alert", "tone": "warn", "category": name, "text": f"「{name}」本月已超出預算",
                        "sub": "可到「財務報表 → 分類與預算」查看"})
        if m["income"] and m["net"] > 0 and m["net"] / m["income"] >= 0.2:
            out.append({"icon": "heart", "tone": "good", "text": f"本月儲蓄率 {m['net'] / m['income']:.0%}，表現很好", "sub": "20% 以上就是健康的水準"})
        for a in mats[:1]:
            d = a["days_left"]
            when = "今天到期" if d == 0 else (f"已到期 {-d} 天" if d < 0 else f"{d} 天後到期")
            out.append({"icon": "calendar", "tone": "warn" if d <= 7 else "info", "text": f"{a['name']} {when}",
                        "sub": f"到期日 {a['maturity_date'].replace('-', '/')}"})
        if r.get("emergency_months") is not None and r["emergency_months"] < 3:
            out.append({"icon": "alert", "tone": "warn", "text": "緊急預備金不到 3 個月的支出", "sub": "建議保留 6 個月以上的生活費"})
        return out[:5]
