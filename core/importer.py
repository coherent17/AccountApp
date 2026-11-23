"""匯入 Excel／CSV 收支資料。"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .database import Database

FIELDS = {
    "date": "日期",
    "type": "類型（收入／支出）",
    "amount": "金額",
    "income": "收入金額",
    "expense": "支出金額",
    "category": "分類",
    "account": "帳戶",
    "note": "說明",
}
FIELD_ALIASES = {
    "date": ["日期", "交易日", "交易日期", "記帳日期", "date"],
    "type": ["類型", "收支", "收支別", "type"],
    "amount": ["金額", "原幣金額", "amount"],
    "income": ["收入", "存入", "收入金額", "存入金額"],
    "expense": ["支出", "提出", "支出金額", "支出（twd）", "提款"],
    "category": ["分類", "類別", "科目", "分類／對方科目", "category"],
    "account": ["帳戶", "account"],
    "note": ["說明", "摘要", "備註", "內容", "note", "memo"],
}


def read_table(path: str) -> list[list]:
    """讀取檔案內容為二維清單。"""
    if path.lower().endswith((".xlsx", ".xlsm")):
        wb = load_workbook(path, data_only=True, read_only=True)
        ws = wb.worksheets[0]
        for name in ("收支明細", "明細"):
            if name in wb.sheetnames:
                ws = wb[name]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp950", "big5", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    return [r for r in csv.reader(io.StringIO(text))]


def find_header(rows: list[list]) -> int:
    for i, r in enumerate(rows[:30]):
        cells = [str(c).strip().lower() for c in r if c is not None]
        if any(c in FIELD_ALIASES["date"] for c in cells) and len(cells) >= 2:
            return i
    return 0


def guess_mapping(header: list) -> dict[str, int | None]:
    names = [str(h).strip().lower() if h is not None else "" for h in header]
    mapping: dict[str, int | None] = {k: None for k in FIELDS}
    for key, aliases in FIELD_ALIASES.items():
        for i, n in enumerate(names):
            if n in [a.lower() for a in aliases] or any(n.startswith(a.lower()) for a in aliases):
                if mapping[key] is None and i not in mapping.values():
                    mapping[key] = i
    return mapping


def parse_date(v) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < v < 80000:   # Excel 序號
        return (_dt.date(1899, 12, 30) + _dt.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    m = re.match(r"^(\d{2,4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})", s)
    if not m:
        m2 = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
        if not m2:
            return None
        m = m2
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 1000:            # 民國年
        y += 1911
    try:
        return _dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_amount(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("NT$", "").replace("$", "").replace("元", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def build_rows(db: Database, rows: list[list], header_idx: int, mapping: dict,
               default_account: int, sign_mode: str = "expense_positive",
               create_categories: bool = True) -> list[dict]:
    """依欄位對應產生待匯入資料（含驗證結果）。"""
    accounts = {a["name"]: a["id"] for a in db.list_accounts(include_archived=True)}
    cats = {(c["kind"], c["name"]): c["id"] for c in db.list_categories(include_archived=True)}
    out = []

    def col(r, key):
        i = mapping.get(key)
        return r[i] if i is not None and i < len(r) else None

    for n, r in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if not any(c not in (None, "") for c in r):
            continue
        item = {"row": n, "error": "", "new_category": False}
        date = parse_date(col(r, "date"))
        if not date:
            if str(col(r, "date") or "").strip() in ("", "合計") or "合計" in " ".join(str(c) for c in r if c):
                continue
            item["error"] = "日期無法辨識"
        typ_text = str(col(r, "type") or "").strip()
        amount = None
        ttype = None
        if mapping.get("income") is not None or mapping.get("expense") is not None:
            inc = parse_amount(col(r, "income")) or 0
            exp = parse_amount(col(r, "expense")) or 0
            if inc and not exp:
                ttype, amount = "income", abs(inc)
            elif exp and not inc:
                ttype, amount = "expense", abs(exp)
        if ttype is None:
            amount = parse_amount(col(r, "amount"))
            if amount is not None:
                if "收" in typ_text or "存" in typ_text:
                    ttype = "income"
                elif "支" in typ_text or "付" in typ_text or "提" in typ_text:
                    ttype = "expense"
                elif typ_text in ("轉帳", "分錄", "餘額調整"):
                    ttype = None
                    item["error"] = f"「{typ_text}」類型不支援匯入（請改為收入或支出）"
                elif sign_mode == "expense_positive":
                    ttype = "expense" if amount >= 0 else "income"
                elif sign_mode == "income_positive":
                    ttype = "income" if amount >= 0 else "expense"
                else:
                    ttype = "expense"
                amount = abs(amount)
        if not item["error"] and (amount is None or amount == 0):
            item["error"] = "金額無法辨識"
        acc_name = str(col(r, "account") or "").strip()
        account_id = accounts.get(acc_name) or default_account
        cat_name = str(col(r, "category") or "").strip() or ("其他收入" if ttype == "income" else "其他支出")
        cid = cats.get((ttype, cat_name)) if ttype else None
        if ttype and not cid:
            if create_categories:
                item["new_category"] = True
            else:
                cid = cats.get((ttype, "其他收入" if ttype == "income" else "其他支出"))
        item.update({"date": date, "type": ttype, "amount": amount, "account_id": account_id,
                     "account_name": acc_name or "", "category_name": cat_name, "category_id": cid,
                     "note": str(col(r, "note") or "").strip()})
        if not item["error"] and db.closed_until and date and date <= db.closed_until:
            item["error"] = "日期位於已結帳期間"
        out.append(item)
    return out


def do_import(db: Database, items: list[dict]) -> tuple[int, int]:
    ok = skipped = 0
    with db.undo_group(f"匯入 {sum(1 for it in items if not it['error'])} 筆紀錄"):
        for it in items:
            if it["error"]:
                skipped += 1
                continue
            cid = it["category_id"]
            if not cid:
                existing = db.find_category(it["type"], it["category_name"])
                cid = existing["id"] if existing else db.add_category(it["category_name"], it["type"])
            try:
                db.add_transaction(date=it["date"], type=it["type"], account_id=it["account_id"],
                                   amount=it["amount"], category_id=cid, note=it["note"], log="匯入")
                ok += 1
            except ValueError:
                skipped += 1
    return ok, skipped


def write_template(path: str) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "收支明細"
    heads = ["日期", "類型", "分類", "帳戶", "說明", "金額"]
    ws.append(heads)
    for c in ws[1]:
        c.font = Font(name="微軟正黑體", bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1C2840")
        c.alignment = Alignment(horizontal="center")
    samples = [
        (_dt.date(2026, 1, 5), "收入", "退休金", "銀行存款", "月退休金", 42000),
        (_dt.date(2026, 1, 6), "支出", "餐飲", "現金", "市場買菜", 350),
        ("115/01/07", "支出", "醫療保健", "現金", "門診（民國日期也可以）", 200),
    ]
    for s in samples:
        ws.append(list(s))
    for i, w in enumerate([14, 8, 12, 14, 26, 12], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    for r in ws.iter_rows(min_row=2):
        r[0].number_format = "yyyy/mm/dd"
        r[5].number_format = "#,##0"
    note = wb.create_sheet("說明")
    for line in ["匯入說明：", "1. 第一列為欄位名稱，可以只保留需要的欄位。",
                 "2. 日期可用 2026/01/05、2026-01-05 或民國 115/01/05。",
                 "3. 類型填「收入」或「支出」；也可以改用「收入」、「支出」兩個金額欄位。",
                 "4. 分類、帳戶名稱需與程式中相同；找不到的分類可選擇自動新增。",
                 "5. 帳戶留空時，會使用匯入畫面中選擇的預設帳戶。"]:
        note.append([line])
    note.column_dimensions["A"].width = 70
    wb.save(path)
