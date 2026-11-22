"""收支明細與記一筆：查詢、新增、修改、作廢、迴轉、標籤、附件、修改紀錄、復原。"""

from __future__ import annotations

import datetime as dt
import json
import os

from app import undo
from app.database import TYPE_LABELS, voucher_no

from v3.rpc import exposed


def _signed(r: dict) -> float:
    return -r["amount"] if r["type"] == "expense" else r["amount"]


def _row(r: dict) -> dict:
    """收支明細的一列（與 v2 收支明細相同的欄位與文字）。"""
    if r["category_name"]:
        cat = r["category_name"]
    elif r["type"] == "transfer":
        cat = "帳戶間轉帳"
    else:
        cat = "未實現評價損益"
    acc = f"{r['account_name']} → {r['to_account_name']}" if r["type"] == "transfer" else (r["account_name"] or "")
    system = r["source"].startswith("inv:")
    return {
        "id": r["id"], "voucher": voucher_no(r["id"]), "date": r["date"], "type": r["type"],
        "type_label": "已作廢" if r["void"] else ("投資" if system else TYPE_LABELS[r["type"]]),
        "category": cat, "account": acc, "note": r["note"], "tags": r.get("tags", []),
        "void": bool(r["void"]), "void_reason": r["void_reason"] or "", "source": r["source"],
        "amount": r["amount"] if r["type"] == "journal" else _signed(r), "currency": r["currency"],
        "signed": r["type"] not in ("transfer", "journal"),
        "to_amount": r["to_amount"] if r["type"] == "transfer" and r["to_currency"] != r["currency"] else None,
        "to_currency": r["to_currency"],
        "base": _signed(r) * (r["rate"] or 1) if r["type"] != "journal" else r["amount"],
        "inc": r["inc"], "exp": r["exp"], "n_attach": r["n_attach"], "n_cleared": r["n_cleared"],
    }


class TxnApi:
    # ------------------------------------------------------------------ 收支明細
    @exposed
    def txn_filters(self) -> dict:
        db = self._db
        return {
            "accounts": [{"id": a["id"], "name": a["name"] + ("（已封存）" if a["archived"] else ""),
                          "kind": a["kind"]} for a in db.list_accounts(include_archived=True)],
            "categories": [{"id": c["id"], "name": c["name"], "kind": c["kind"]}
                           for c in db.list_categories(include_archived=True)],
            "tags": [t["name"] for t in db.all_tags()],
            "range": list(db.date_range()),
        }

    @exposed
    def txn_list(self, f: dict) -> dict:
        a, b = f.get("start"), f.get("end")
        if a and b and a > b:
            a, b = b, a
        rows = self._db.query_transactions(start=a, end=b, ttype=f.get("type") or None,
                                           account_id=f.get("account") or None,
                                           category_id=f.get("category") or None,
                                           keyword=(f.get("keyword") or "").strip() or None,
                                           include_void=bool(f.get("void")), tag=f.get("tag") or None)
        out = [_row(r) for r in rows]
        live = [r for r in rows if not r["void"]]
        return {"rows": out, "count": len(live), "voided": len(rows) - len(live),
                "income": sum(r["inc"] for r in rows), "expense": sum(r["exp"] for r in rows)}

    # ------------------------------------------------------------------ 記一筆
    @exposed
    def txn_form(self, tid: int | None = None) -> dict:
        """記一筆／編輯視窗需要的清單：帳戶（含餘額）、收入與支出分類、常用說明、標籤。"""
        db = self._db
        accounts = [{"id": a["id"], "name": a["name"], "currency": a["currency"], "rate": a["rate"],
                     "kind": a["kind"], "balance": a["balance"], "category": a["category"], "code": a["code"],
                     "archived": bool(a["archived"])}
                    for a in db.account_summaries(include_archived=tid is not None)]
        codes = db.category_codes()
        cats = {k: [{"id": c["id"], "name": c["name"], "code": codes.get(c["id"], "")}
                    for c in db.list_categories(k)] for k in ("income", "expense")}
        last = db.get_setting("last_account_id")
        out = {"accounts": accounts, "categories": cats, "notes": db.recent_notes(),
               "tags": [t["name"] for t in db.all_tags()], "last_account": int(last) if last.isdigit() else None,
               "closed_until": db.closed_until, "txn": None}
        if tid:
            t = db.get_transaction(tid)
            if not t:
                raise ValueError(f"找不到 {voucher_no(tid)}")
            out["txn"] = {**dict(t), "voucher": voucher_no(tid), "tags": db.get_tags(tid),
                          "attachments": self._attachments(tid), "system": bool(t["source"]),
                          "locked": bool(db.closed_until and t["date"] <= db.closed_until)}
            if t["category_id"] and not any(c["id"] == t["category_id"] for c in cats.get(t["type"], [])):
                c = db.get_category(t["category_id"])     # 已封存的分類仍要顯示
                cats.setdefault(t["type"], []).append({"id": c["id"], "name": c["name"] + "（已封存）",
                                                       "code": codes.get(c["id"], "")})
        return out

    @exposed
    def txn_save(self, data: dict, tid: int | None = None, attachments: list[str] | None = None) -> dict:
        db = self._db
        fields = {k: data.get(k) for k in ("date", "type", "account_id", "to_account_id", "amount", "to_amount",
                                           "category_id", "note")}
        if fields["type"] not in ("income", "expense", "transfer", "adjust"):
            raise ValueError("不支援的傳票類型")
        if not fields["account_id"]:
            raise ValueError("請先到「帳戶管理」新增至少一個帳戶")
        if fields["amount"] is None:
            raise ValueError("請輸入金額（可輸入數字或算式）")
        if fields["type"] in ("income", "expense") and not fields["category_id"]:
            raise ValueError("請點選一個分類")
        if fields["type"] == "transfer":
            if not fields["to_account_id"]:
                raise ValueError("請選擇轉入帳戶")
            if fields["to_amount"] is None:
                fields["to_amount"] = fields["amount"]
        else:
            fields["to_account_id"] = fields["to_amount"] = None
        if fields["type"] not in ("income", "expense"):
            fields["category_id"] = None
        fields["note"] = (fields["note"] or "").strip()
        tags = data.get("tags") or []
        if tid:
            db.update_transaction(tid, tags=tags, **fields)
        else:
            tid = db.add_transaction(tags=tags, **fields)
            for p in attachments or []:
                try:
                    db.add_attachment(tid, p, os.path.join(self._folder, "憑證附件"))
                except OSError:
                    pass
        db.set_setting("last_account_id", fields["account_id"])
        return {"id": tid, "voucher": voucher_no(tid)}

    # ------------------------------------------------------------------ 傳票（唯讀檢視）
    @exposed
    def voucher(self, tid: int) -> dict:
        """傳票的借貸分錄（分錄與系統傳票的檢視；複式分錄的編輯另見分錄視窗）。"""
        db = self._db
        t = db.get_transaction(tid)
        if not t:
            raise ValueError(f"找不到 {voucher_no(tid)}")
        lines = db.txn_lines_of(t, live=False)
        secs = {}
        if any(ln.get("security_id") for ln in lines):
            from app.investments import Investments
            secs = {s["id"]: s["name"] for s in Investments(db).list_securities(include_archived=True)}
        return {**dict(t), "voucher": voucher_no(tid), "type_label": TYPE_LABELS[t["type"]],
                "tags": db.get_tags(tid), "attachments": self._attachments(tid),
                "locked": bool(db.closed_until and t["date"] <= db.closed_until),
                "lines": [{"code": ln["code"], "name": ln["name"], "group": ln["group"], "debit": ln["debit"],
                           "credit": ln["credit"], "memo": ln.get("memo") or "",
                           "security": secs.get(ln.get("security_id")), "shares": ln.get("shares"),
                           "price": ln.get("price")} for ln in lines]}

    # ------------------------------------------------------------------ 作廢、迴轉、刪除系統傳票
    @exposed
    def txn_void(self, ids: list[int], reason: str) -> int:
        self._db.void_transactions(ids, (reason or "").strip() or "作廢")
        return len(ids)

    @exposed
    def txn_unvoid(self, tid: int) -> str:
        self._db.unvoid_transaction(tid)
        return voucher_no(tid)

    @exposed
    def txn_reverse(self, tid: int) -> str:
        return voucher_no(self._db.reverse_transaction(tid))

    @exposed
    def inv_voucher_events(self, ids: list[int]) -> list[str]:
        """系統傳票對應的投資交易說明（刪除前讓她確認）。"""
        from app.investments import KIND_LABELS, Investments
        inv = Investments(self._db)
        desc = []
        for tid in ids:
            evs = inv.voucher_events(tid)
            for ev in evs:
                sec = inv.get_security(ev["security_id"])
                desc.append(f"{voucher_no(tid)}：{ev['date'].replace('-', '/')} {sec['name']} "
                            f"{KIND_LABELS.get(ev['kind'], ev['kind'])}")
            if not evs:
                desc.append(f"{voucher_no(tid)}：{self._db.get_transaction(tid)['note']}")
        return desc

    @exposed
    def inv_delete_vouchers(self, ids: list[int]) -> int:
        from app.investments import Investments
        return Investments(self._db).delete_vouchers(ids)

    @exposed
    def txn_copy(self, tid: int) -> dict:
        """複製一筆：傳回可帶入記一筆視窗的內容（日期改為今天）。"""
        t = self._db.get_transaction(tid)
        if t["source"].startswith(("inv:", "close:")):
            raise ValueError("系統自動產生的傳票（投資分錄、年度結帳分錄）不能複製。")
        out = {k: t[k] for k in ("type", "account_id", "to_account_id", "amount", "to_amount", "category_id", "note")}
        out["date"] = dt.date.today().isoformat()
        out["tags"] = self._db.get_tags(tid)
        if t["type"] == "journal":
            out["lines"] = [{k: ln[k] for k in ("account_id", "category_id", "special", "debit", "credit", "orig",
                                                "memo")} for ln in self._db.get_lines(tid)]
        return out

    # ------------------------------------------------------------------ 標籤
    @exposed
    def tag_add(self, ids: list[int], tag: str) -> int:
        return self._db.add_tag(ids, tag)

    @exposed
    def tag_remove(self, ids: list[int], tag: str) -> int:
        return self._db.remove_tag_from(ids, tag)

    # ------------------------------------------------------------------ 附件
    def _attachments(self, tid: int) -> list[dict]:
        return [{"id": a["id"], "name": a["name"], "path": a["path"], "exists": os.path.exists(a["path"])}
                for a in self._db.list_attachments(tid)]

    @exposed
    def attach_add(self, tid: int, paths: list[str]) -> list[dict]:
        for p in paths:
            self._db.add_attachment(tid, p, os.path.join(self._folder, "憑證附件"))
        return self._attachments(tid)

    @exposed
    def attach_remove(self, tid: int, att_id: int) -> list[dict]:
        self._db.remove_attachment(att_id)
        return self._attachments(tid)

    # ------------------------------------------------------------------ 修改紀錄
    @exposed
    def audit(self, tid: int | None = None, keyword: str = "") -> list[dict]:
        rows = self._db.list_audit(tid, limit=3000)
        out = []
        for r in rows:
            text = r["summary"]
            if r["detail"]:
                try:
                    d = json.loads(r["detail"])
                    extra = "；".join(f"{k}：{v}" for k, v in d.items() if v)
                    if extra:
                        text += f"　〔{extra}〕"
                except ValueError:
                    pass
            if keyword and not any(keyword in x for x in (r["voucher"], r["action"], text)):
                continue
            out.append({"id": r["id"], "at": r["at"].replace("T", " ").replace("-", "/"), "action": r["action"],
                        "voucher": r["voucher"], "text": text})
        return out

    # ------------------------------------------------------------------ 復原（Ctrl+Z）
    @exposed
    def undo_label(self) -> str:
        return undo.next_label(self._db)

    @exposed
    def undo(self) -> str:
        return undo.undo_last(self._db)
