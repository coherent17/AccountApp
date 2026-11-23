"""復原上一步（Ctrl+Z）。

Database 在本次開啟期間把每個操作記在 db.undo_stack（關閉程式後清空），這裡負責把它復原：

* 新增的傳票 → 作廢（傳票保留在帳上，原因為「復原」；帳不刪除，符合作廢不刪除的原則）
* 修改 → 改回修改前的內容（含分錄行、投資連結與標籤）
* 作廢 → 取消作廢（並接回銀行對帳勾選）
* 取消作廢 → 再次作廢（原因不變）
* 修改標籤 → 改回原來的標籤
* 投資管理新增的交易 → 刪除；刪除的投資交易 → 加回（同一編號）
* 定期交易入帳／略過 → 一併把「上次入帳日」改回去，下次會再提醒

每一步都照常寫入修改紀錄，並另外記一筆「復原」。
"""

from __future__ import annotations

from .database import Database, voucher_no

UNDO_REASON = "復原（Ctrl+Z）：取消剛才的新增"


def can_undo(db: Database) -> bool:
    return bool(db.undo_stack)


def next_label(db: Database) -> str:
    return db.undo_stack[-1]["label"] if db.undo_stack else ""


def undo_last(db: Database) -> str:
    """復原最近一步，傳回說明文字。失敗時丟出 ValueError（該步驟留在清單上，可以修正後再試）。"""
    if not db.undo_stack:
        raise ValueError("目前沒有可以復原的操作")
    entry = db.undo_stack[-1]
    with db.undo_paused():
        try:
            for op in reversed(entry["ops"]):
                _apply(db, op)
        except ValueError as e:
            db.conn.rollback()
            raise ValueError(f"無法復原「{entry['label']}」：{e}") from None
    db.undo_stack.pop()
    db._log("復原", None, entry["label"])
    db.conn.commit()
    return entry["label"]


def _apply(db: Database, op: dict) -> None:
    kind = op["kind"]
    if kind == "added":
        t = db.get_transaction(op["tid"])
        if t and not t["void"]:
            db.void_transactions([op["tid"]], UNDO_REASON)
    elif kind == "edited":
        _restore(db, op["snap"])
    elif kind == "voided":
        t = db.get_transaction(op["tid"])
        if t and t["void"]:
            db.unvoid_transaction(op["tid"])
            for r in op.get("recon") or []:
                db.conn.execute("INSERT OR IGNORE INTO recon_items(recon_id, txn_id, account_id) VALUES (?, ?, ?)",
                                (r["recon_id"], r["txn_id"], r["account_id"]))
    elif kind == "unvoided":
        t = db.get_transaction(op["tid"])
        if t and not t["void"]:
            db.void_transactions([op["tid"]], op.get("reason") or "")
    elif kind == "tags":
        if db.get_transaction(op["tid"]):
            db.set_tags(op["tid"], op["tags"])
    elif kind == "recurring":
        db.conn.execute("UPDATE recurring SET last_date = ? WHERE id = ?", (op["last_date"] or "", op["rec_id"]))
    elif kind == "event_added":
        _undo_event_added(db, op)
    elif kind == "events_deleted":
        _reinsert_events(db, op["rows"])
    else:
        raise ValueError(f"不支援的復原動作：{kind}")


def _restore(db: Database, snap: dict) -> None:
    old = snap["txn"]
    tid = old["id"]
    if not db.get_transaction(tid):
        raise ValueError(f"找不到 {voucher_no(tid)}")
    if old["type"] == "journal":
        lines = [{k: ln[k] for k in ("account_id", "category_id", "special", "debit", "credit", "orig", "memo",
                                     "security_id", "shares", "price")} for ln in snap["lines"]]
        db.update_journal(tid, old["date"], old["note"], lines, tags=snap["tags"])
    else:
        db.update_transaction(tid, tags=snap["tags"], **{k: old[k] for k in (
            "date", "type", "account_id", "to_account_id", "amount", "to_amount", "category_id", "note")})


def _undo_event_added(db: Database, op: dict) -> None:
    from .investments import Investments
    inv = Investments(db)
    ev = db._q1("SELECT * FROM sec_events WHERE id = ?", (op["eid"],))
    if ev:
        inv.delete_event(op["eid"])
    if op.get("replaced"):
        _reinsert_events(db, op["replaced"])


def _reinsert_events(db: Database, rows: list[dict]) -> None:
    from .investments import Investments
    inv = Investments(db)
    first: dict[int, str] = {}
    for ev in rows:
        if db._q1("SELECT 1 FROM sec_events WHERE id = ?", (ev["id"],)):
            continue
        db._check_open(ev["date"])
        cols = list(ev.keys())
        db.conn.execute(f"INSERT INTO sec_events({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                        [ev[c] for c in cols])
        sid = ev["security_id"]
        first[sid] = min(first.get(sid, ev["date"]), ev["date"])
    try:
        for sid in first:
            inv.replay(sid)
    except ValueError as e:
        db.conn.rollback()
        raise ValueError(f"加回投資交易後持股不正確（{e}）") from None
    for sid, d in first.items():
        inv.rebuild(sid, d)
