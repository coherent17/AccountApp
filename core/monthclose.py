"""月結小幫手：每個月月初，帶她一步一步把上個月的帳收好。

能從帳上判斷的步驟自動打勾（定期交易已入帳、銀行帳戶已對帳、持股已評價）；需要她自己確認的步驟
（檢視預算、健康檢查、月報）由她按「完成」。進度存在設定 month_close（JSON，不需要改資料表）。
"""

from __future__ import annotations

import datetime as _dt

from .database import Database, month_end, month_start

KEY = "month_close"
STEPS = [
    ("recurring", "定期交易都已入帳", "房租、保費、薪資等定期交易，本月該入帳的都入帳了"),
    ("reconcile", "銀行帳戶已對帳", "拿出存摺或網路銀行明細，與帳上逐筆核對"),
    ("valuation", "持股依月底市價評價", "輸入月底收盤價，讓投資的帳面價值反映市價"),
    ("budget", "檢視本月預算執行", "看看哪些分類超出預算，下個月可以留意"),
    ("health", "帳務健康檢查", "確認借貸平衡、備份正常，沒有需要處理的事"),
    ("report", "列印或存檔本月月報", "一頁看完本月收支、資產與投資，可列印或另存 PDF"),
]
BANK_WORDS = ("存款", "銀行", "郵局", "活存", "活儲")
NOT_BANK = ("保險", "保單", "投資", "基金", "證券", "定期", "定存")


def label(ym: str) -> str:
    y, m = ym.split("-")
    return f"{int(y)} 年 {int(m)} 月"


def previous_month(today: _dt.date | None = None) -> str:
    today = today or _dt.date.today()
    first = today.replace(day=1) - _dt.timedelta(days=1)
    return first.strftime("%Y-%m")


def _saved(db: Database) -> dict:
    v = db.get_json(KEY, {})
    return v if isinstance(v, dict) else {}


def bank_accounts(db: Database) -> list[dict]:
    """需要對帳的帳戶：名稱或類別看起來是銀行／郵局存款的資產帳戶，以及信用卡。"""
    out = []
    for a in db.list_accounts():
        text = (a["category"] or "") + a["name"]
        if (a["kind"] == "asset" and any(w in text for w in BANK_WORDS) and not any(w in text for w in NOT_BANK)) \
                or (a["kind"] == "liability" and "信用卡" in text):
            out.append(a)
    return out


def status(db: Database, ym: str) -> dict:
    from .investments import Investments

    start, end = month_start(ym), month_end(ym)
    saved = _saved(db).get(ym, {})
    manual = set(saved.get("checked", []))
    steps = []

    def add(key, ok, detail, auto=True, **extra):
        title, hint = next((t, h) for k, t, h in STEPS if k == key)
        steps.append({"key": key, "title": title, "hint": hint, "ok": bool(ok or key in manual),
                      "auto": auto and bool(ok), "manual": key in manual, "detail": detail, **extra})

    due = db.due_recurring(end)
    add("recurring", not due, "本月該入帳的定期交易都已入帳" if not due else
        f"還有 {len(due)} 筆尚未入帳：" + "、".join(dict.fromkeys(r["name"] for r, _ in due)))

    banks = []
    for a in bank_accounts(db):
        recs = db.list_reconciliations(a["id"])
        last = recs[0]["statement_date"] if recs else ""
        banks.append({"id": a["id"], "name": a["name"], "last": last, "ok": last >= start})
    left = [b["name"] for b in banks if not b["ok"]]
    add("reconcile", banks and not left,
        "沒有需要對帳的銀行帳戶" if not banks else "每個銀行帳戶都已對帳" if not left else "尚未對帳：" + "、".join(left),
        accounts=banks)

    inv = Investments(db)
    live = [h for h in inv.holdings(end) if h["shares"] > 1e-9]
    recent = (_dt.date.fromisoformat(end) - _dt.timedelta(days=10)).isoformat()
    stale = [h["name"] for h in live if not h["price_date"] or h["price_date"] < recent]
    add("valuation", not stale, "沒有持股，不需要評價" if not live else
        "每一檔持股都已依月底市價評價" if not stale else "尚未評價：" + "、".join(stale[:5]))

    spent = {c["id"]: c["total"] for c in db.category_totals(start, end, "expense")}
    budgets = [{"name": c["name"], "budget": c["budget"], "used": spent.get(c["id"], 0.0)}
               for c in db.list_categories("expense") if c["budget"] > 0]
    over = [b["name"] for b in budgets if b["used"] > b["budget"]]
    add("budget", False, "沒有設定預算" if not budgets else
        "每個分類都在預算內" if not over else f"{len(over)} 個分類超出預算：" + "、".join(over), auto=False, budgets=budgets)
    add("health", False, "按「開始檢查」，約幾秒鐘", auto=False)
    add("report", False, "按「預覽月報」，可以列印或另存 PDF", auto=False)

    done = sum(1 for s in steps if s["ok"])
    return {"ym": ym, "label": label(ym), "start": start, "end": end, "steps": steps, "done": done,
            "total": len(steps), "finished": saved.get("finished", "")}


def check(db: Database, ym: str, key: str, on: bool = True) -> None:
    if key not in {k for k, _, _ in STEPS}:
        raise ValueError("不支援的步驟")
    allv = _saved(db)
    cur = allv.setdefault(ym, {})
    checked = set(cur.get("checked", []))
    checked.add(key) if on else checked.discard(key)
    cur["checked"] = sorted(checked)
    db.set_json(KEY, allv)


def finish(db: Database, ym: str) -> None:
    allv = _saved(db)
    allv.setdefault(ym, {})["finished"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    db.set_json(KEY, allv)


def should_prompt(db: Database, today: _dt.date | None = None) -> str:
    """每個月月初（1～20 日）第一次開啟時：上個月有紀錄且還沒完成月結，就提醒一次。傳回月份或空字串。"""
    today = today or _dt.date.today()
    ym = previous_month(today)
    if today.day > 20 or db.get_setting("month_close_prompted") == ym or _saved(db).get(ym, {}).get("finished"):
        return ""
    n = db._q1("SELECT COUNT(*) AS n FROM transactions WHERE void = 0 AND source = '' AND date BETWEEN ? AND ?",
               (month_start(ym), month_end(ym)))["n"]
    return ym if n else ""


def mark_prompted(db: Database, ym: str) -> None:
    db.set_setting("month_close_prompted", ym)
