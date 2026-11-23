"""智慧對帳：讀取銀行下載的交易明細（Excel／CSV），自動找出帳上對應的紀錄。

比對方式：金額相同、日期相差 3 天以內，一筆對一筆，日期最接近的優先。
只回傳建議，勾選與儲存仍由她在「銀行對帳」視窗確認。
"""

from __future__ import annotations

import datetime as _dt

from .importer import FIELD_ALIASES, find_header, guess_mapping, parse_amount, parse_date, read_table

BALANCE_ALIASES = ["餘額", "帳戶餘額", "結餘", "結存", "balance"]


def read_statement(path: str) -> dict:
    """讀取銀行明細：每列的日期、金額（存入為正、提出為負）、摘要，以及最後一列的餘額（若有）。"""
    try:
        rows = read_table(path)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"無法讀取檔案：{e}") from None
    h = find_header(rows)
    head = rows[h] if rows else []
    m = guess_mapping(head)
    if m.get("date") is None:
        raise ValueError("找不到「日期」欄。請確認檔案是銀行網站下載的交易明細（第一列為欄位名稱，例如：日期、摘要、存入、提出、餘額）。")
    if m.get("amount") is None and m.get("income") is None and m.get("expense") is None:
        raise ValueError("找不到金額欄（例如「金額」或「存入」「提出」）。")
    names = [str(c).strip().lower() if c is not None else "" for c in head]
    bal_col = next((i for i, c in enumerate(names) if c in BALANCE_ALIASES), None)

    def cell(r, i):
        return r[i] if i is not None and i < len(r) else None

    out = []
    for n, r in enumerate(rows[h + 1:], start=h + 2):
        d = parse_date(cell(r, m["date"]))
        if not d:
            continue
        if m.get("amount") is not None:
            amt = parse_amount(cell(r, m["amount"]))
        else:
            inc = parse_amount(cell(r, m.get("income"))) or 0.0
            exp = parse_amount(cell(r, m.get("expense"))) or 0.0
            amt = inc - abs(exp) if (inc or exp) else None
        if amt is None or abs(amt) < 0.005:
            continue
        note = " ".join(str(cell(r, i)).strip() for i in (m.get("note"), m.get("category"))
                        if cell(r, i) not in (None, "")).strip()
        out.append({"row": n, "date": d, "amount": round(amt, 2), "note": note,
                    "balance": parse_amount(cell(r, bal_col)) if bal_col is not None else None})
    if not out:
        raise ValueError("檔案裡沒有可以比對的交易（需要有日期與金額）。")
    last = max(out, key=lambda x: (x["date"], x["row"]))
    return {"rows": out, "last_date": last["date"],
            "last_balance": next((x["balance"] for x in sorted(out, key=lambda x: (x["date"], x["row"]), reverse=True)
                                  if x["balance"] is not None), None)}


def _days(a: str, b: str) -> int:
    return abs((_dt.date.fromisoformat(a) - _dt.date.fromisoformat(b)).days)


def _pair(book: list[dict], bank: list[dict], sign: int, tol: int) -> list[tuple[int, int]]:
    used, pairs = set(), []
    for j, b in sorted(enumerate(bank), key=lambda x: x[1]["date"]):
        best = None
        for i, c in enumerate(book):
            if i in used or abs(c["effect"] - sign * b["amount"]) >= 0.005:
                continue
            d = _days(c["date"], b["date"])
            if d <= tol and (best is None or d < best[0]):
                best = (d, i)
        if best:
            used.add(best[1])
            pairs.append((best[1], j))
    return pairs


def match(book: list[dict], bank: list[dict], statement_date: str, tol: int = 3) -> dict:
    """book：銀行對帳的未核銷紀錄（txn_id、date、effect）；bank：read_statement 的 rows。

    信用卡明細常以「消費為正數」表示，所以兩種正負號都試，取配對較多的一種。"""
    bank = [b for b in bank if b["date"] <= statement_date]
    best = max((_pair(book, bank, s, tol) for s in (1, -1)), key=len)
    paired_bank = {j for _, j in best}
    return {"matched": [book[i]["txn_id"] for i, _ in best],
            "bank_only": [b for j, b in enumerate(bank) if j not in paired_bank],
            "book_only": [book[i]["txn_id"] for i in range(len(book)) if i not in {i for i, _ in best}]}
