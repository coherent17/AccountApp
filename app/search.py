"""全域搜尋：一次找遍傳票、會計科目、投資標的與定期交易。

搜尋文字以空白分成多個關鍵字，每個關鍵字都要符合（AND）。關鍵字依外觀判斷：

* ``V000123`` / ``v123``：傳票編號。
* 日期 ``2025-03``、``2025/3/5``、``114/03``（民國）：該日期或月份開頭的傳票。
* 數字 ``1,500``、``0.866``：金額、單價、股數相同，或科目／標的代號相同，或傳票號碼相同。
* 其他文字：摘要、備註、科目名稱、分錄說明、標的名稱、附件檔名、作廢原因等包含此文字。

只讀取資料，不修改任何東西。
"""

from __future__ import annotations

import json
import re

from .database import CLOSING, SPECIALS, TYPE_LABELS, voucher_no

_VOUCHER = re.compile(r"^[vV](\d{1,9})$")
_DATE = re.compile(r"^(\d{2,4})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?$")
_NUMBER = re.compile(r"^(?:NT\$|\$)?[-+]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")

GROUP_ORDER = {"科目": 0, "投資標的": 1, "定期交易": 2, "傳票": 3}


def _date_prefix(tok: str) -> str | None:
    m = _DATE.match(tok)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), m.group(3)
    if y < 1911:          # 民國年
        y += 1911
    if not (1 <= mo <= 12) or y < 1912:
        return None
    if d is None:
        return f"{y:04d}-{mo:02d}"
    if not 1 <= int(d) <= 31:
        return None
    return f"{y:04d}-{mo:02d}-{int(d):02d}"


def _number(tok: str) -> float | None:
    if not _NUMBER.match(tok):
        return None
    try:
        return float(tok.replace("NT$", "").replace("$", "").replace(",", ""))
    except ValueError:
        return None


class _Token:
    def __init__(self, raw: str):
        self.raw = raw
        self.text = raw.lower()
        m = _VOUCHER.match(raw)
        self.vid = int(m.group(1)) if m else None
        self.date = None if self.vid else _date_prefix(raw)
        self.num = None if (self.vid or self.date) else _number(raw)


def parse(text: str) -> list[_Token]:
    return [_Token(t) for t in (text or "").split() if t.strip()]


def _num_hit(tok: _Token, numbers) -> bool:
    n = abs(tok.num)
    return any(abs(abs(x) - n) < 0.0005 for x in numbers if x)


def _text_match(tok: _Token, hay: str, codes=(), numbers=(), ident: int | None = None,
                date: str = "") -> bool:
    """一個關鍵字是否符合某筆資料。"""
    if tok.vid is not None:
        return ident is not None and ident == tok.vid
    if tok.date is not None:
        return bool(date) and date.startswith(tok.date)
    if tok.num is not None:
        raw = tok.raw.replace(",", "")
        if any(c == raw for c in codes if c):
            return True
        if ident is not None and raw.isdigit() and int(raw) == ident:
            return True
        if _num_hit(tok, numbers):
            return True
        return tok.text in hay      # 例如備註中的「0050」
    return tok.text in hay


def search(db, text: str, limit: int = 300) -> dict:
    """回傳 {"rows": [...], "total_vouchers": n, "truncated": bool}。"""
    toks = parse(text)
    if not toks:
        return {"rows": [], "total_vouchers": 0, "truncated": False}
    rows: list[dict] = []
    rows += _search_chart(db, toks)
    rows += _search_securities(db, toks)
    rows += _search_recurring(db, toks)
    vouchers = _search_vouchers(db, toks)
    total = len(vouchers)
    rows += vouchers[:limit]
    return {"rows": rows, "total_vouchers": total, "truncated": total > limit}


# ---------------------------------------------------------------------------
def _search_chart(db, toks) -> list[dict]:
    out = []
    accs = {a["id"]: a for a in db.list_accounts(include_archived=True)}
    for c in db.chart_of_accounts(include_archived=True):
        kind, ident = c["key"]
        note = accs[ident]["note"] if kind == "account" and ident in accs else ""
        hay = " ".join([c["code"], c["name"], c["group"], c.get("category") or "",
                        c.get("currency") or "", note]).lower()
        ok = True
        for t in toks:
            if t.vid is not None or t.date is not None:
                ok = False
            elif t.num is not None:
                raw = t.raw.replace(",", "")
                ok = c["code"].startswith(raw) or t.text in hay
            else:
                ok = t.text in hay
            if not ok:
                break
        if ok:
            out.append({"group": "科目", "kind": kind, "id": ident, "date": "", "ref": c["code"],
                        "title": c["name"] + ("（已隱藏）" if c.get("archived") else ""),
                        "detail": c["group"] + (f"・{c['category']}" if c.get("category") else "")
                        + (f"・{c['currency']}" if c.get("currency") and c["currency"] != db.base_currency
                           else ""),
                        "amount": None, "currency": "", "void": False})
    return out


def _search_securities(db, toks) -> list[dict]:
    out = []
    for s in db._q("SELECT s.*, a.name AS account_name FROM securities s"
                   " JOIN accounts a ON a.id = s.account_id ORDER BY s.code, s.id"):
        hay = " ".join([s["code"], s["name"], s["type_name"], s["note"], s["account_name"]]).lower()
        if all(t.vid is None and t.date is None and
               (t.text in hay or (t.num is not None and s["code"].startswith(t.raw.replace(",", ""))))
               for t in toks):
            out.append({"group": "投資標的", "kind": "security", "id": s["id"], "date": "",
                        "ref": s["code"], "title": s["name"] + ("（已封存）" if s["archived"] else ""),
                        "detail": "・".join(x for x in (s["type_name"], s["account_name"], s["note"]) if x),
                        "amount": None, "currency": "", "void": False})
    return out


def _search_recurring(db, toks) -> list[dict]:
    out = []
    accs = {a["id"]: a["name"] for a in db.list_accounts(include_archived=True)}
    cats = {c["id"]: c["name"] for c in db.list_categories(include_archived=True)}
    for r in db.list_recurring():
        d = r["data"] if isinstance(r["data"], dict) else json.loads(r["data"])
        names = [accs.get(d.get("account_id"), ""), accs.get(d.get("to_account_id"), ""),
                 cats.get(d.get("category_id"), "")]
        hay = " ".join([r["name"], d.get("note", "") or "", *names]).lower()
        nums = [d.get("amount") or 0]
        if all(_text_match(t, hay, numbers=nums) for t in toks):
            out.append({"group": "定期交易", "kind": "recurring", "id": r["id"], "date": "",
                        "ref": "", "title": r["name"] + ("" if r["active"] else "（停用）"),
                        "detail": "・".join(x for x in [TYPE_LABELS.get(d.get("type"), ""), *names] if x),
                        "amount": d.get("amount"), "currency": db.base_currency, "void": False})
    return out


def _search_vouchers(db, toks) -> list[dict]:
    base = db.base_currency
    accs = {a["id"]: a for a in db.list_accounts(include_archived=True)}
    acodes = db.account_codes()
    cats = {c["id"]: c for c in db.list_categories(include_archived=True)}
    ccodes = db.category_codes()
    secs = {s["id"]: s for s in db._q("SELECT id, code, name FROM securities")}
    lines: dict[int, list[dict]] = {}
    for ln in db._q("SELECT * FROM txn_lines ORDER BY txn_id, seq"):
        lines.setdefault(ln["txn_id"], []).append(ln)
    atts: dict[int, list[str]] = {}
    for a in db._q("SELECT txn_id, name FROM attachments"):
        atts.setdefault(a["txn_id"], []).append(a["name"])
    tags: dict[int, list[str]] = {}
    for g in db._q("SELECT txn_id, tag FROM txn_tags"):
        tags.setdefault(g["txn_id"], []).append(g["tag"])

    out = []
    for t in db._q("SELECT * FROM transactions ORDER BY date DESC, id DESC"):
        words = [voucher_no(t["id"]), t["date"], t["date"].replace("-", "/"),
                 TYPE_LABELS.get(t["type"], ""), t["note"], t["void_reason"],
                 "作廢" if t["void"] else "", "系統" if t["source"].startswith(("inv:", "close:")) else ""]
        codes: list[str] = []
        nums = [t["amount"], t["to_amount"] or 0]
        names: list[str] = []
        for aid in (t["account_id"], t["to_account_id"]):
            if aid in accs:
                names.append(accs[aid]["name"])
                codes.append(acodes.get(aid, ""))
        if t["category_id"] in cats:
            names.append(cats[t["category_id"]]["name"])
            codes.append(ccodes.get(t["category_id"], ""))
        for ln in lines.get(t["id"], []):
            if ln["account_id"] in accs:
                n = accs[ln["account_id"]]["name"]
                codes.append(acodes.get(ln["account_id"], ""))
            elif ln["category_id"] in cats:
                n = cats[ln["category_id"]]["name"]
                codes.append(ccodes.get(ln["category_id"], ""))
            else:
                code, n, _g = SPECIALS.get(ln["special"], CLOSING)
                codes.append(code)
            if n not in names:
                names.append(n)
            words.append(ln["memo"])
            if ln["security_id"] in secs:
                s = secs[ln["security_id"]]
                words += [s["code"], s["name"]]
                codes.append(s["code"])
            nums += [ln["debit"], ln["credit"], ln["orig"] or 0, ln["shares"], ln["price"]]
        words += names + codes + atts.get(t["id"], []) + tags.get(t["id"], [])
        hay = " ".join(w for w in words if w).lower()
        if not all(_text_match(tok, hay, codes, nums, t["id"], t["date"]) for tok in toks):
            continue
        if t["type"] == "journal":
            cur, amt = base, t["amount"]
        else:
            a = accs.get(t["account_id"])
            cur, amt = (a["currency"] if a else base), t["amount"]
        note = t["note"] or "、".join(ln["memo"] for ln in lines.get(t["id"], []) if ln["memo"])
        out.append({"group": "傳票", "kind": "voucher", "id": t["id"], "date": t["date"],
                    "ref": voucher_no(t["id"]), "title": note or TYPE_LABELS.get(t["type"], ""),
                    "detail": TYPE_LABELS.get(t["type"], "") + "・" + "、".join(names[:4])
                    + (f"・附件 {len(atts[t['id']])}" if t["id"] in atts else "")
                    + (f"・標籤 {'、'.join(tags[t['id']])}" if t["id"] in tags else ""),
                    "amount": amt, "currency": cur, "void": bool(t["void"]),
                    "system": t["source"].startswith(("inv:", "close:"))})
    return out
