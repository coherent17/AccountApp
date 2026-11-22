"""複式分錄（傳票）：多行借貸、連結投資標的、外幣原幣金額、常用範本。"""

from __future__ import annotations

from app.database import CLOSING, CLOSING_SOURCE, voucher_no
from app.investments import KIND_LABELS, Investments
from app.journal_templates import TEMPLATES, load_templates, resolve_template_key, save_templates

from v3.rpc import exposed


def _key(k) -> str:
    return f"{k[0]}:{k[1]}"


def _parse_key(s: str) -> dict:
    kind, _, val = s.partition(":")
    if kind == "account":
        return {"account_id": int(val)}
    if kind == "category":
        return {"category_id": int(val)}
    return {"special": val}


class JournalApi:
    def _chart(self, closing: bool = False) -> list[dict]:
        db = self._db
        accs = {a["id"]: a for a in db.list_accounts(include_archived=True)}
        out = []
        for a in db.chart_of_accounts():
            acc = accs.get(a["key"][1]) if a["key"][0] == "account" else None
            out.append({"key": _key(a["key"]), "code": a["code"], "name": a["name"], "group": a["group"],
                        "kind": a["kind"], "investment": bool(a["investment"]),
                        "currency": acc["currency"] if acc else None, "rate": acc["rate"] if acc else 1})
        if closing:
            out.append({"key": "special:closing", "code": CLOSING[0], "name": CLOSING[1], "group": CLOSING[2],
                        "kind": "special", "investment": False, "currency": None, "rate": 1})
        return out

    def _templates(self, chart_by_key: dict) -> list[dict]:
        out = []
        for name, lines in load_templates(self._db):
            rows = []
            for side, spec, memo, amount in lines:
                k = resolve_template_key(self._db, chart_by_key, spec)
                rows.append({"side": side, "key": _key(k) if k else "", "memo": memo or "", "amount": amount})
            out.append({"name": name, "lines": rows})
        return out

    @exposed
    def journal_form(self, tid: int | None = None) -> dict:
        db = self._db
        t = db.get_transaction(tid) if tid else None
        closing = bool(t and t["source"].startswith(CLOSING_SOURCE))
        chart = self._chart(closing)
        by_key = {c["key"]: {"key": tuple(c["key"].split(":", 1)) if not c["key"].startswith(("account:", "category:"))
                             else (c["key"].split(":")[0], int(c["key"].split(":")[1]))} for c in chart}
        secs = [{"id": s["id"], "label": f"{s['code']} {s['name']}".strip(), "account_id": s["account_id"],
                 "archived": bool(s["archived"])} for s in Investments(db).list_securities(include_archived=True)]
        out = {"chart": chart, "securities": secs, "base": db.base_currency, "templates": self._templates(by_key),
               "tags": [x["name"] for x in db.all_tags()], "notes": db.recent_notes(), "txn": None}
        if t:
            readonly = ""
            if t["void"]:
                readonly = "此傳票已作廢。"
            elif closing:
                readonly = "這是年度結帳分錄：損益科目結轉本期損益，只記錄於日記簿、不影響報表金額。如需更正該年度，請先到「設定」解除結帳。"
            elif t["source"].startswith("inv:"):
                readonly = "此傳票由「投資管理」自動產生，不能修改；可按「刪除這張傳票」連同該筆投資交易一併刪除。"
            elif db.closed_until and t["date"] <= db.closed_until:
                readonly = f"這張傳票在已結帳的期間（{db.closed_until.replace('-', '/')} 以前），只能檢視。如需更正，請在收支明細按右鍵「迴轉」。"
            lines = []
            for ln in db.get_lines(tid):
                k = f"account:{ln['account_id']}" if ln["account_id"] else \
                    f"category:{ln['category_id']}" if ln["category_id"] else f"special:{ln['special']}"
                lines.append({"key": k, "debit": ln["debit"] or None, "credit": ln["credit"] or None, "memo": ln["memo"],
                              "security_id": ln["security_id"], "shares": ln["shares"] or None,
                              "price": ln["price"] or None, "orig": ln["orig"]})
            out["txn"] = {"id": tid, "voucher": voucher_no(tid), "date": t["date"], "note": t["note"],
                          "tags": db.get_tags(tid), "lines": lines, "readonly": readonly, "void": bool(t["void"]),
                          "system": t["source"].startswith("inv:"), "source": t["source"]}
        return out

    @exposed
    def sec_info(self, sid: int) -> dict:
        inv = Investments(self._db)
        st = inv.replay(sid)
        s = inv.get_security(sid)
        return {"label": f"{s['code']} {s['name']}".strip(), "currency": s["currency"], "shares": st["shares"],
                "avg_cost": st["avg_cost"], "cost": st["cost"]}

    @exposed
    def journal_save(self, d: dict, tid: int | None = None, confirmed: bool = False) -> dict:
        db = self._db
        inv = Investments(db)
        lines = []
        for i, ln in enumerate(d["lines"], 1):
            dr, cr = ln.get("debit") or 0, ln.get("credit") or 0
            if not ln.get("key") and not dr and not cr:
                continue
            if not ln.get("key"):
                raise ValueError(f"第 {i} 行尚未選擇會計科目")
            item = _parse_key(ln["key"])
            item.update({"debit": dr, "credit": cr, "memo": ln.get("memo") or ""})
            if ln.get("orig") and (dr or cr):
                if ln["orig"] <= 0:
                    raise ValueError(f"第 {i} 行的原幣金額必須大於 0")
                item["orig"] = ln["orig"] if dr else -ln["orig"]
            if ln.get("security_id") and (dr or cr):
                item["security_id"] = ln["security_id"]
                item["shares"] = ln.get("shares") or 0
                item["price"] = ln.get("price") or 0
                if item["shares"] <= 0:
                    raise ValueError(f"第 {i} 行已選擇投資標的，請輸入股數")
            lines.append(item)
        if not confirmed:   # 投資科目已有標的、但這一行沒有連結標的：金額不會計入持股
            loose = [db.get_account(x["account_id"])["name"] for x in lines
                     if x.get("account_id") and not x.get("security_id") and inv.list_securities(x["account_id"])]
            if loose:
                return {"need_confirm": list(dict.fromkeys(loose))}
        tags = d.get("tags") or []
        if tid:
            db.update_journal(tid, d["date"], d.get("note") or "", lines, tags=tags)
        else:
            tid = db.add_journal(d["date"], d.get("note") or "", lines, tags=tags)
        return {"id": tid, "voucher": voucher_no(tid)}

    # ------------------------------------------------------------------ 範本
    @exposed
    def template_list(self) -> list[dict]:
        return [{"name": n, "lines": [list(x) for x in lines]} for n, lines in load_templates(self._db)]

    @exposed
    def template_save_all(self, items: list[dict]) -> None:
        names = [i["name"].strip() for i in items]
        if any(not n for n in names):
            raise ValueError("範本名稱不能空白")
        if len(set(names)) != len(names):
            raise ValueError("範本名稱不能重複")
        save_templates(self._db, [[i["name"].strip(), [list(x) for x in i["lines"]]] for i in items])

    @exposed
    def template_add(self, name: str, lines: list[list]) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("請輸入範本名稱")
        items = load_templates(self._db)
        if any(n == name for n, _ in items):
            raise ValueError(f"已有名為「{name}」的範本，請換一個名稱")
        if len(lines) < 2:
            raise ValueError("範本至少需要兩行會計科目")
        save_templates(self._db, [[n, [list(x) for x in ls]] for n, ls in items] + [[name, lines]])

    @exposed
    def template_defaults(self) -> list[str]:
        return [n for n, _ in TEMPLATES[1:]]

    @exposed
    def voucher_event_text(self, tid: int) -> str:
        inv = Investments(self._db)
        evs = inv.voucher_events(tid)
        if not evs:
            return ""
        names = "、".join(f"{inv.get_security(ev['security_id'])['name']} {KIND_LABELS.get(ev['kind'], ev['kind'])}"
                         for ev in evs)
        return f"（{evs[0]['date'].replace('-', '/')} {names}）"
