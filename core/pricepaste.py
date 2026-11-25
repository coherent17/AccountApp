"""市價評價：把從 Excel（或網頁）複製的「代號、價格」整欄貼上，對應到持股。只解析文字，不寫入帳本。"""

from __future__ import annotations

import re

PRICE_HEADS = ("收盤", "市價", "股價", "成交價", "現價", "價格", "淨值", "price", "close")
JUMP = 0.3          # 與上次評價相差超過 30% 時提醒再確認


def _num(s: str) -> float | None:
    t = s.strip().replace(",", "").replace("NT$", "").replace("$", "").replace("元", "").strip()
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", t):
        return None
    return float(t)


def _cells(line: str) -> list[str]:
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    # 沒有 Tab：以空白或逗號分開（千分位的逗號不切）
    return [c.strip() for c in re.split(r"\s+|;|(?<=\d{4}),|,(?!\d{3}(?:\D|$))", line.strip()) if c.strip()]


def parse(text: str, rows: list[dict]) -> dict:
    """rows：市價評價的持股 [{id, code, name, price, sold}]。傳回 matches、unknown、problems、missing。"""
    live = [r for r in rows if not r.get("sold")]
    by_code: dict[str, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for r in live:
        by_code.setdefault(r["code"].strip().upper(), []).append(r)
        by_name.setdefault(r["name"].strip(), []).append(r)

    def ident(cells: list[str]) -> int | None:
        """哪一格是代號或名稱。數字只有在最前面、或明顯是代號（0 開頭、含英文字母）時才算代號；
        否則「沒有持有的股票 1234，價格 2330」會被誤認成 2330 的價格是 1234。"""
        for i, c in enumerate(cells):
            if i == price_col or not find(c):
                continue
            if i == 0 or _num(c) is None or c.startswith("0") or not any(_num(x) is not None for x in cells[:i]):
                return i
        return None

    def find(cell: str) -> list[dict] | None:
        c = cell.strip().upper()
        if not c:
            return None
        if c in by_code:
            return by_code[c]
        if c.isdigit():          # Excel 會把 0050 變成 50：補回前面的 0
            hits = [k for k in by_code if k.isdigit() and k.lstrip("0") == c.lstrip("0") and len(k) > len(c)]
            if len(hits) == 1:
                return by_code[hits[0]]
        return by_name.get(cell.strip())

    lines = [_cells(x) for x in text.splitlines() if x.strip()]
    price_col = None
    found: dict[int, float] = {}
    unknown, problems = [], []
    for cells in lines:
        heads = [i for i, c in enumerate(cells) if any(h in c.lower() for h in PRICE_HEADS)]
        if heads and not any(_num(c) is not None for c in cells):
            price_col = heads[0]          # 標題列：記住價格是哪一欄
            continue
        at = ident(cells)
        label = " ".join(cells)[:40]
        if at is None:
            if any(_num(c) is not None for c in cells):
                unknown.append(label)
            continue
        sec = find(cells[at])
        nums = [(i, _num(c)) for i, c in enumerate(cells) if i != at and _num(c) is not None]
        if price_col is not None and price_col < len(cells) and price_col != at:
            price = _num(cells[price_col])
        elif len(nums) == 1:
            price = nums[0][1]
        elif not nums:
            price = None
        else:
            problems.append(f"{label}：這一列有好幾個數字，看不出哪個是市價；請只複製代號與價格兩欄，或連標題列（含「收盤價」）一起複製")
            continue
        if not price:
            problems.append(f"{label}：找不到市價")
            continue
        for r in sec:
            if r["id"] in found and abs(found[r["id"]] - price) > 1e-9:
                problems.append(f"{r['code']} {r['name']}：出現兩個不同的價格（{found[r['id']]:g}、{price:g}），採用第一個")
            else:
                found[r["id"]] = price
    matches = []
    for r in live:
        if r["id"] in found:
            p, old = found[r["id"]], r.get("price") or 0
            matches.append({"id": r["id"], "code": r["code"], "name": r["name"], "price": p, "old": old,
                            "jump": bool(old) and abs(p - old) / old > JUMP})
    return {"matches": matches, "unknown": unknown, "problems": list(dict.fromkeys(problems)),
            "missing": [f"{r['code']} {r['name']}".strip() for r in live if r["id"] not in found]}
