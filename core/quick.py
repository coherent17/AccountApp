"""快速記帳：從她自己記過的收支，找出常記的項目（一鍵帶入）與每個說明上次用的分類、帳戶。

只讀取資料，不寫入；只看她自己記的（source = ''）、未作廢的收入與支出傳票。
"""

from __future__ import annotations

import datetime as _dt

from .database import Database


def _rows(db: Database, days: int, today: _dt.date | None) -> list[dict]:
    since = ((today or _dt.date.today()) - _dt.timedelta(days=days)).isoformat()
    return db._q("SELECT t.id, t.date, t.type, TRIM(t.note) AS note, t.category_id, t.account_id, t.amount"
                  "  FROM transactions t"
                  "  JOIN categories c ON c.id = t.category_id AND c.archived = 0"
                  "  JOIN accounts a ON a.id = t.account_id AND a.archived = 0"
                  " WHERE t.void = 0 AND t.source = '' AND t.type IN ('expense', 'income')"
                  "   AND TRIM(t.note) <> '' AND t.date >= ?"
                  " ORDER BY t.date DESC, t.id DESC", (since,))


def frequent(db: Database, n: int = 6, days: int = 180, today: _dt.date | None = None) -> list[dict]:
    """最常記的項目（同一個說明＋分類至少記過 2 次），依次數、最近日期排序。金額帶最近一次的金額。"""
    groups: dict[tuple, dict] = {}
    for r in _rows(db, days, today):
        key = (r["type"], r["note"], r["category_id"])
        g = groups.get(key)
        if g is None:      # 第一次遇到的就是最近一筆（已依日期由新到舊排序）
            groups[key] = {"type": r["type"], "note": r["note"], "category_id": r["category_id"],
                           "account_id": r["account_id"], "amount": r["amount"], "last": r["date"], "count": 1}
        else:
            g["count"] += 1
    names = {c["id"]: c["name"] for c in db.list_categories()}
    out = [g for g in groups.values() if g["count"] >= 2]
    out.sort(key=lambda g: (g["count"], g["last"]), reverse=True)
    for g in out:
        g["category"] = names.get(g["category_id"], "")
    return out[:n]


def note_hints(db: Database, days: int = 365, today: _dt.date | None = None) -> dict[str, dict]:
    """每個說明上次記帳時的類型、分類與帳戶：輸入「全聯」就能自動帶入。"""
    hints: dict[str, dict] = {}
    for r in _rows(db, days, today):
        if r["note"] not in hints:
            hints[r["note"]] = {"type": r["type"], "category_id": r["category_id"], "account_id": r["account_id"]}
    return hints
