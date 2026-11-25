"""年度結帳小幫手：年底到隔年初，一步一步把一整年的帳收好。

能從帳上判斷的步驟自動打勾；健康檢查與年度財務報告由她確認。進度存在設定 year_close_progress（JSON）。
真正的結帳仍由「年度結帳」完成（只有過完年才能結）。
"""

from __future__ import annotations

import datetime as _dt

from . import monthclose
from .database import Database

KEY = "year_close_progress"
STEPS = [("recurring", "定期交易都已入帳"), ("reconcile", "銀行帳戶已對帳到年底"), ("valuation", "持股依年底市價評價"),
         ("health", "帳務健康檢查"), ("report", "年度財務報告"), ("close", "年度結帳")]
MANUAL = {"recurring", "reconcile", "valuation", "health", "report"}


def default_year(today: _dt.date | None = None) -> int:
    """12 月起準備今年，其他月份處理去年。"""
    today = today or _dt.date.today()
    return today.year if today.month == 12 else today.year - 1


def _saved(db: Database) -> dict:
    v = db.get_json(KEY, {})
    return v if isinstance(v, dict) else {}


def has_data(db: Database, year: int) -> bool:
    return bool(db._q1("SELECT COUNT(*) AS n FROM transactions WHERE void = 0 AND date BETWEEN ? AND ?",
                       (f"{year}-01-01", f"{year}-12-31"))["n"])


def status(db: Database, year: int, today: _dt.date | None = None) -> dict:
    from .investments import Investments
    today = today or _dt.date.today()
    end, dec = f"{year}-12-31", f"{year}-12-01"
    manual = set(_saved(db).get(str(year), {}).get("checked", []))
    steps = []

    def add(key, ok, detail, auto=True, **extra):
        steps.append({"key": key, "title": dict(STEPS)[key], "ok": bool(ok or key in manual), "auto": auto and bool(ok),
                      "manual": key in manual, "can_mark": key in MANUAL, "detail": detail, **extra})

    due = db.due_recurring(end)
    now = [x for x in due if x[1] <= today.isoformat()]          # 已到期（現在就能入帳）；其餘到年底前才會到期
    names = lambda xs: "、".join(dict.fromkeys(r["name"] for r, _ in xs))  # noqa: E731
    add("recurring", not due, f"{year} 年該入帳的定期交易都已入帳" if not due else
        (f"已到期 {len(now)} 筆尚未入帳：{names(now)}" if now else "") + ("；" if now and len(due) > len(now) else "")
        + (f"年底前還有 {len(due) - len(now)} 筆會到期" if len(due) > len(now) else ""), due_now=len(now))
    banks = []
    for a in monthclose.bank_accounts(db):
        recs = db.list_reconciliations(a["id"])
        last = recs[0]["statement_date"] if recs else ""
        banks.append({"id": a["id"], "name": a["name"], "last": last, "ok": last >= dec})
    left = [b["name"] for b in banks if not b["ok"]]
    add("reconcile", not left, "沒有需要對帳的銀行帳戶" if not banks else
        "每個銀行帳戶都有 12 月以後的對帳" if not left else "尚未對到年底：" + "、".join(left), accounts=banks)
    live = [h for h in Investments(db).holdings(end) if h["shares"] > 1e-9]
    stale = [h["name"] for h in live if not h["price_date"] or h["price_date"] < dec]
    add("valuation", not stale, "年底沒有持股，不需要評價" if not live else
        "每一檔持股 12 月都評價過" if not stale else f"{len(stale)} 檔 12 月還沒有評價：" + "、".join(stale[:5]) + ("…" if len(stale) > 5 else ""))
    add("health", False, "確認借貸平衡、備份正常", auto=False)
    add("report", False, "預覽整年度的報告，可以列印或另存 PDF", auto=False)
    closed = db.year_closings()
    first = db.first_year() or year
    pending = [y for y in range(first, year + 1) if y not in closed and has_data(db, y)]
    done = year in closed
    over = year < today.year
    add("close", done, f"{year} 年度已經結帳" if done else
        (f"{year} 年還沒結束，{year + 1} 年 1 月 1 日起才能結帳；前面的步驟可以先準備" if not over else
         f"結轉 {year} 年損益並鎖定 {year}/12/31 以前的帳" + (f"（會一併結 {'、'.join(map(str, pending[:-1]))} 年）" if len(pending) > 1 else "")),
        can_close=over and not done)
    return {"year": year, "steps": steps, "done": sum(1 for s in steps if s["ok"]), "total": len(steps), "closed": done,
            "years": [y for y in range(max(today.year, year), first - 1, -1) if has_data(db, y) or y == year][:10]}


def check(db: Database, year: int, key: str, on: bool = True) -> None:
    if key not in MANUAL:
        raise ValueError("這個步驟會依帳務自動判斷")
    allv = _saved(db)
    cur = allv.setdefault(str(year), {})
    checked = set(cur.get("checked", []))
    checked.add(key) if on else checked.discard(key)
    cur["checked"] = sorted(checked)
    db.set_json(KEY, allv)


def reminder(db: Database, today: _dt.date | None = None) -> int | None:
    """總覽提醒：12/15～隔年 3/31，該年有帳且還沒結帳。"""
    today = today or _dt.date.today()
    if not ((today.month == 12 and today.day >= 15) or today.month <= 3):
        return None
    year = default_year(today)
    return year if has_data(db, year) and year not in db.year_closings() else None
