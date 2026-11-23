"""月結小幫手、到期提醒中心、資料健康檢查、月報與智慧對帳。帳務計算都在 core/。"""

from __future__ import annotations

import datetime as dt

from core import bankmatch, health, monthclose, reminders
from core.database import month_keys

from desktop.rpc import exposed


class ToolsApi:
    # ------------------------------------------------------------------ 到期提醒中心
    @exposed
    def reminders_upcoming(self, days: int = 90) -> dict:
        return {"events": reminders.upcoming(self._db, int(days)), "custom": reminders.list_custom(self._db),
                "kinds": list(reminders.KINDS.items()), "freqs": list(reminders.FREQS.items())}

    @exposed
    def reminder_save(self, item: dict) -> dict:
        return reminders.save_custom(self._db, item)

    @exposed
    def reminder_delete(self, rid: str) -> None:
        reminders.delete_custom(self._db, rid)

    # ------------------------------------------------------------------ 月結小幫手
    @exposed
    def month_close(self, ym: str | None = None) -> dict:
        db = self._db
        ym = ym or monthclose.previous_month()
        st = monthclose.status(db, ym)
        lo, _ = db.date_range()
        this = dt.date.today().strftime("%Y-%m")
        st["months"] = [k for k in month_keys(lo[:7] + "-01", dt.date.today().isoformat()) if k <= this][::-1][:24]
        return st

    @exposed
    def month_close_check(self, ym: str, key: str, on: bool = True) -> None:
        monthclose.check(self._db, ym, key, on)

    @exposed
    def month_close_finish(self, ym: str) -> None:
        monthclose.finish(self._db, ym)

    @exposed
    def month_close_prompt(self) -> str:
        """開啟程式時：月初還沒完成上個月的月結就提醒一次（之後只在總覽顯示）。"""
        ym = monthclose.should_prompt(self._db)
        if ym:
            monthclose.mark_prompted(self._db, ym)
        return ym

    # ------------------------------------------------------------------ 健康檢查與月報
    @exposed
    def health_run(self) -> dict:
        self._health = health.run(self._db, self._folder)
        return self._health

    @exposed
    def health_html(self) -> str:
        from core.printing import Report
        res = getattr(self, "_health", None) or health.run(self._db, self._folder)
        return Report(self._db).health(res)

    @exposed
    def monthly_html(self, ym: str) -> str:
        from core.printing import Report
        return Report(self._db).monthly(ym)

    # ------------------------------------------------------------------ 智慧對帳
    @exposed
    def recon_match(self, aid: int, date: str, path: str) -> dict:
        db = self._db
        st = bankmatch.read_statement(path)
        book = [{"txn_id": c["txn_id"], "date": c["date"], "effect": c["effect"]} for c in db.recon_candidates(aid, date)]
        m = bankmatch.match(book, st["rows"], date)
        return {**m, "rows": len(st["rows"]), "last_date": st["last_date"], "last_balance": st["last_balance"],
                "later": sum(1 for r in st["rows"] if r["date"] > date)}
