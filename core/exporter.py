"""Excel 報表匯出（openpyxl）。

合計、小計、比率等欄位一律寫成 Excel 公式，方便在 Excel 中稽核、追溯與修改。
"""

from __future__ import annotations

import datetime as dt

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .database import (ADJUST_ACCOUNT, CURRENCIES, EQUITY_ACCOUNT, FX_ACCOUNT, REALIZED_ACCOUNT,
                       CLOSING_SOURCE, TYPE_LABELS,
                       Database, month_keys, voucher_no)

FONT = "微軟正黑體"
NAVY = "1C2840"
BLUE = "2563EB"
LIGHT = "EEF3FB"
ZEBRA = "F8FAFC"
SUB = "E8EEF8"
TOTAL = "DCE6F7"
GREEN = "0F9D6E"
RED = "C62828"

THIN = Side(style="thin", color="CBD3DF")
MED = Side(style="medium", color=NAVY)
DOUBLE = Side(style="double", color=NAVY)

F_TITLE = Font(name=FONT, size=16, bold=True, color=NAVY)
F_SUBT = Font(name=FONT, size=10, color="64748B")
F_HEAD = Font(name=FONT, size=11, bold=True, color="FFFFFF")
F_BODY = Font(name=FONT, size=11)
F_BOLD = Font(name=FONT, size=11, bold=True)
F_SECTION = Font(name=FONT, size=12, bold=True, color=NAVY)

FILL_HEAD = PatternFill("solid", fgColor=NAVY)
FILL_SUB = PatternFill("solid", fgColor=SUB)
FILL_TOTAL = PatternFill("solid", fgColor=TOTAL)
FILL_ZEBRA = PatternFill("solid", fgColor=ZEBRA)
FILL_LIGHT = PatternFill("solid", fgColor=LIGHT)

NUM0 = '#,##0;[Red]-#,##0;"-"'
NUM2 = '#,##0.00;[Red]-#,##0.00;"-"'
RATE = '0.0000'
PCT = '0.0%;[Red]-0.0%;"-"'
DATE = 'yyyy/mm/dd'


def _num_fmt(code: str) -> str:
    return NUM0 if code in ("TWD", "JPY") else NUM2


def _code(code: str):
    return int(code) if str(code).isdigit() else code


def _d(iso: str) -> dt.date:
    return dt.date.fromisoformat(iso)


class _Sheet:
    """openpyxl 工作表的小幫手，負責一致的格式。"""

    def __init__(self, ws: Worksheet):
        self.ws = ws

    def title(self, text: str, sub: str, span: int) -> int:
        ws = self.ws
        ws["A1"] = text
        ws["A1"].font = F_TITLE
        ws["A2"] = sub
        ws["A2"].font = F_SUBT
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)
        ws.row_dimensions[1].height = 28
        return 4

    def header(self, row: int, labels: list[str]) -> None:
        for i, label in enumerate(labels, 1):
            c = self.ws.cell(row=row, column=i, value=label)
            c.font = F_HEAD
            c.fill = FILL_HEAD
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        self.ws.row_dimensions[row].height = 24

    def cell(self, row: int, col: int, value=None, fmt: str | None = None, bold=False,
             fill=None, align: str | None = None, color: str | None = None, border=True,
             indent: int = 0):
        c = self.ws.cell(row=row, column=col, value=value)
        c.font = Font(name=FONT, size=11, bold=bold, color=color) if (bold or color) else F_BODY
        if fmt:
            c.number_format = fmt
        if fill:
            c.fill = fill
        if align or indent:
            c.alignment = Alignment(horizontal=align or "left", vertical="center", indent=indent)
        if border:
            c.border = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
        return c

    def widths(self, widths: list[float]) -> None:
        for i, w in enumerate(widths, 1):
            self.ws.column_dimensions[get_column_letter(i)].width = w

    def total_border(self, row: int, c1: int, c2: int, double=False) -> None:
        for col in range(c1, c2 + 1):
            c = self.ws.cell(row=row, column=col)
            c.border = Border(left=THIN, right=THIN, top=MED,
                              bottom=DOUBLE if double else THIN)

    def print_setup(self, header_row: int | None = None, landscape: bool = False) -> None:
        ws = self.ws
        ws.page_setup.orientation = "landscape" if landscape else "portrait"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_options.horizontalCentered = True
        ws.page_margins.left = ws.page_margins.right = 0.4
        ws.oddFooter.center.text = "第 &P 頁，共 &N 頁"
        ws.oddFooter.right.text = "&A"
        if header_row:
            ws.print_title_rows = f"{header_row}:{header_row}"
        ws.sheet_view.showGridLines = False


# 可選擇匯出的工作表（依活頁簿順序）與說明
SHEET_INFO = [
    ("財務摘要", "報表期間的重點數字與各工作表說明"),
    ("資產負債表", "依流動性分類列示資產與負債，並附財務比率分析"),
    ("收支損益表", "本期收入、支出、結餘與業外損益"),
    ("現金流量表", "期初現金 ＋ 生活／投資／籌資活動 ＝ 期末現金（直接法）"),
    ("收支明細", "逐筆交易紀錄，可使用篩選，合計會自動重算"),
    ("月度收支", "每月收支、儲蓄率、累計結餘與淨資產趨勢（含圖表）"),
    ("分類統計", "各分類逐月金額、占比與預算執行率"),
    ("日記簿", "每筆交易之借貸分錄"),
    ("分類帳", "各帳戶（會計科目）期初餘額、逐筆借貸與累計餘額"),
    ("試算表", "科目借貸餘額，驗證帳務平衡"),
    ("帳戶清單", "所有帳戶（會計科目）之基本資料與期末餘額"),
    ("投資明細", "期末持股、平均成本、帳面價值、未實現損益與期間交易"),
    ("報稅彙總", "依稅務歸類彙總之所得與扣除項目（綜合所得稅參考）"),
]
# 工作表公式引用的其他工作表：未勾選但被引用時改為隱藏，公式才能正確計算
SHEET_DEPS = {"財務摘要": ("資產負債表", "收支損益表"), "收支損益表": ("收支明細",),
              "月度收支": ("收支明細",), "分類統計": ("收支明細",)}


def sheets_needed(selected) -> set[str]:
    need, todo = set(), list(selected)
    while todo:
        name = todo.pop()
        if name not in need:
            need.add(name)
            todo.extend(SHEET_DEPS.get(name, ()))
    return need


def export_workbook(db: Database, path: str, start: str, end: str, sheets=None) -> str:
    """匯出 Excel 報表。sheets 為要匯出的工作表名稱（None 表示全部）。"""
    selected = [n for n, _ in SHEET_INFO if sheets is None or n in sheets]
    if not selected:
        raise ValueError("請至少選擇一份報表")
    base = db.base_currency
    base_name = CURRENCIES.get(base, (base,))[0]
    owner = db.get_setting("owner_name") or "本人"
    period = f"{start.replace('-', '/')} 至 {end.replace('-', '/')}"
    made = dt.datetime.now().strftime("%Y/%m/%d %H:%M")
    bfmt = _num_fmt(base)
    sub = f"編製者：{owner}　｜　期間：{period}　｜　單位：{base_name}（{base}）　｜　編製時間：{made}"

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "財務摘要"
    ws_bs = wb.create_sheet("資產負債表")
    ws_is = wb.create_sheet("收支損益表")
    ws_det = wb.create_sheet("收支明細")
    ws_mon = wb.create_sheet("月度收支")
    ws_cat = wb.create_sheet("分類統計")
    ws_jnl = wb.create_sheet("日記簿")
    ws_led = wb.create_sheet("分類帳")
    ws_tb = wb.create_sheet("試算表")
    ws_acc = wb.create_sheet("帳戶清單")
    ws_cf = wb.create_sheet("現金流量表", 3)
    ws_inv = wb.create_sheet("投資明細")
    ws_tax = wb.create_sheet("報稅彙總")

    acodes = db.account_codes()
    ccodes = db.category_codes()

    # ================================================================ 收支明細
    s = _Sheet(ws_det)
    r = s.title("收支明細表", sub, 13)
    heads = ["日期", "傳票號碼", "類型", "分類／對方科目", "帳戶", "轉入帳戶", "摘要",
             "幣別", "原幣金額", "匯率", f"收入（{base}）", f"支出（{base}）", "標籤／專案"]
    s.header(r, heads)
    hdr_row = r
    txns = list(reversed(db.query_transactions(start=start, end=end)))
    cat_names = {c["id"]: (c["name"], c["kind"]) for c in db.list_categories(include_archived=True)}
    detail = []
    for t in txns:
        if t["source"].startswith(CLOSING_SOURCE):
            continue   # 年度結帳分錄只記錄於日記簿，不列入收支
        if t["type"] != "journal":
            cat = t["category_name"] or ("帳戶間轉帳" if t["type"] == "transfer" else ADJUST_ACCOUNT)
            detail.append((t, TYPE_LABELS[t["type"]], cat, t["account_name"], t["to_account_name"] or "",
                           t["note"], t["currency"], t["amount"], t["rate"]))
            continue
        # 分錄：收入／支出科目逐行列示，讓 SUMIFS 能正確彙總；其餘以一列「分錄」表示
        lines = db.get_lines(t["id"])
        cat_lines = [ln for ln in lines if ln["category_id"]]
        for ln in cat_lines:
            name, kind = cat_names[ln["category_id"]]
            amt = ln["debit"] - ln["credit"] if kind == "expense" else ln["credit"] - ln["debit"]
            memo = f"{t['note']}　{ln['memo']}".strip()
            detail.append((t, "支出" if kind == "expense" else "收入", name, t["account_name"], "",
                           memo, base, amt, 1.0))
        if not cat_lines:
            detail.append((t, "分錄", t["category_name"], t["account_name"], "", t["note"], base,
                           t["amount"], 1.0))
    first = r + 1
    for i, (t, tlabel, cat, acc_name, to_name, note_, cur, amt, rate) in enumerate(detail):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        t = dict(t, currency=cur)
        vals = [_d(t["date"]), voucher_no(t["id"]), tlabel, cat, acc_name, to_name, note_, cur, amt, rate]
        fmts = [DATE, None, None, None, None, None, None, None, _num_fmt(t["currency"]), RATE]
        for col, (v, f) in enumerate(zip(vals, fmts), 1):
            s.cell(r, col, v, f, fill=fill, align="center" if col in (1, 2, 3, 8) else None)
        s.cell(r, 11, f'=IF(C{r}="收入",ROUND(I{r}*J{r},2),0)', bfmt, fill=fill,
               color=GREEN)
        s.cell(r, 12, f'=IF(C{r}="支出",ROUND(I{r}*J{r},2),0)', bfmt, fill=fill,
               color=RED)
        s.cell(r, 13, "、".join(t.get("tags") or []) or None, None, fill=fill)
    last = max(r, first)
    if not txns:
        r += 1
        s.cell(r, 1, "本期間沒有任何紀錄", border=False)
    r += 1
    s.cell(r, 7, "合計（篩選後自動重算）", bold=True, fill=FILL_TOTAL, align="right")
    for col in range(1, 14):
        if col not in (7, 11, 12):
            s.cell(r, col, None, fill=FILL_TOTAL)
    s.cell(r, 11, f"=SUBTOTAL(9,K{first}:K{last})", bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 12, f"=SUBTOTAL(9,L{first}:L{last})", bfmt, bold=True, fill=FILL_TOTAL)
    s.total_border(r, 1, 13, double=True)
    ws_det.auto_filter.ref = f"A{hdr_row}:M{last}"
    ws_det.freeze_panes = f"A{hdr_row + 1}"
    s.widths([14, 13, 11, 19, 20, 16, 26, 8, 14, 10, 15, 15, 18])
    s.print_setup(hdr_row, landscape=True)

    D = "'收支明細'!"
    rng = lambda col: f"{D}${col}${first}:${col}${last}"  # noqa: E731

    def sumifs(value_col: str, type_label: str, d1: str, d2: str, cat_cell: str | None = None) -> str:
        crit = f'{rng("C")},"{type_label}",{rng("A")},">="&{d1},{rng("A")},"<="&{d2}'
        if cat_cell:
            crit += f",{rng('D')},{cat_cell}"
        return f"SUMIFS({rng(value_col)},{crit})"

    date_lit = lambda iso: f"DATE({int(iso[:4])},{int(iso[5:7])},{int(iso[8:10])})"  # noqa: E731
    P1, P2 = date_lit(start), date_lit(end)

    # ================================================================ 資產負債表
    s = _Sheet(ws_bs)
    r = s.title("資產負債表", f"編製者：{owner}　｜　基準日：{end.replace('-', '/')}　｜　"
                f"單位：{base_name}（{base}）　｜　編製時間：{made}", 8)
    bs = db.balance_sheet(end)
    s.header(r, ["科目代號", "會計科目／帳戶", "類別", "幣別", "原幣餘額", "匯率",
                 f"金額（{base}）", "占總資產"])
    bs_hdr = r
    subtotal_cells: dict[str, str] = {}
    total_asset_row = None
    rows_for_pct: list[int] = []

    def bs_group(name: str, accs: list[dict], liability: bool) -> None:
        nonlocal r
        r += 1
        s.cell(r, 1, None, fill=FILL_SUB)
        s.cell(r, 2, name, bold=True, fill=FILL_SUB)
        for col in range(3, 9):
            s.cell(r, col, None, fill=FILL_SUB)
        g_first = r + 1
        for acc in sorted(accs, key=lambda a: acodes[a["id"]]):
            r += 1
            s.cell(r, 1, _code(acodes[acc["id"]]), align="center")
            s.cell(r, 2, acc["name"], indent=1)
            s.cell(r, 3, acc["category"], align="center")
            s.cell(r, 4, acc["currency"], align="center")
            s.cell(r, 5, acc["balance"], _num_fmt(acc["currency"]))
            s.cell(r, 6, acc["rate"], RATE)
            s.cell(r, 7, f"=ROUND(E{r}*F{r},2)", bfmt)
            rows_for_pct.append(r)
        r += 1
        s.cell(r, 2, f"{name}合計", bold=True, fill=FILL_LIGHT, align="right")
        for col in (1, 3, 4, 5, 6, 8):
            s.cell(r, col, None, fill=FILL_LIGHT)
        s.cell(r, 7, f"=SUM(G{g_first}:G{r - 1})" if r - 1 >= g_first else 0, bfmt, bold=True,
               fill=FILL_LIGHT)
        if not liability:
            rows_for_pct.append(r)
        subtotal_cells[name] = f"G{r}"

    r += 1
    s.cell(r, 2, "資　產", bold=True, color=BLUE, border=False)
    bs_group("流動資產", bs["groups"]["流動資產"], False)
    bs_group("非流動資產", bs["groups"]["非流動資產"], False)
    r += 1
    s.cell(r, 2, "資產總計", bold=True, fill=FILL_TOTAL, align="right")
    s.cell(r, 7, f"={subtotal_cells['流動資產']}+{subtotal_cells['非流動資產']}", bfmt,
           bold=True, fill=FILL_TOTAL)
    s.cell(r, 8, f"=IFERROR(G{r}/G{r},0)", PCT, bold=True, fill=FILL_TOTAL)
    for col in (1, 3, 4, 5, 6):
        s.cell(r, col, None, fill=FILL_TOTAL)
    s.total_border(r, 1, 8, double=True)
    total_asset_row = r
    for pr in rows_for_pct:
        s.cell(pr, 8, f"=IFERROR(G{pr}/$G${total_asset_row},0)", PCT,
               fill=FILL_LIGHT if f"G{pr}" in subtotal_cells.values() else None)

    r += 2
    s.cell(r, 2, "負債及淨值", bold=True, color=BLUE, border=False)
    bs_group("流動負債", bs["groups"]["流動負債"], True)
    bs_group("非流動負債", bs["groups"]["非流動負債"], True)
    r += 1
    s.cell(r, 2, "負債總計", bold=True, fill=FILL_TOTAL, align="right")
    for col in (1, 3, 4, 5, 6, 8):
        s.cell(r, col, None, fill=FILL_TOTAL)
    s.cell(r, 7, f"={subtotal_cells['流動負債']}+{subtotal_cells['非流動負債']}", bfmt,
           bold=True, fill=FILL_TOTAL)
    s.cell(r, 8, f"=IFERROR(G{r}/$G${total_asset_row},0)", PCT, bold=True, fill=FILL_TOTAL)
    total_liab_row = r
    r += 1
    s.cell(r, 2, "淨資產（業主權益）", bold=True, fill=FILL_TOTAL, align="right")
    for col in (1, 3, 4, 5, 6):
        s.cell(r, col, None, fill=FILL_TOTAL)
    s.cell(r, 7, f"=G{total_asset_row}-G{total_liab_row}", bfmt, bold=True, fill=FILL_TOTAL,
           color=BLUE)
    s.cell(r, 8, f"=IFERROR(G{r}/$G${total_asset_row},0)", PCT, bold=True, fill=FILL_TOTAL)
    net_row = r
    r += 1
    s.cell(r, 2, "負債及淨值總計", bold=True, fill=FILL_TOTAL, align="right")
    for col in (1, 3, 4, 5, 6):
        s.cell(r, col, None, fill=FILL_TOTAL)
    s.cell(r, 7, f"=G{total_liab_row}+G{net_row}", bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 8, f'=IF(ROUND(G{r}-G{total_asset_row},2)=0,"✓ 平衡","✗ 不平衡")', bold=True,
           fill=FILL_TOTAL, align="center")
    s.total_border(r, 1, 8, double=True)

    # 財務比率
    ratios = db.ratios(end)
    r += 2
    s.cell(r, 2, "財務比率分析", bold=True, color=BLUE, border=False)
    r += 1
    s.header(r, ["", "指標", "公式", "", "", "", "數值", "參考"])
    ratio_rows = [
        ("負債比率", "負債總計 ÷ 資產總計", f"=IFERROR(G{total_liab_row}/G{total_asset_row},0)",
         PCT, "愈低愈穩健，一般建議 < 30%"),
        ("流動比率", "流動資產 ÷ 流動負債",
         f"=IFERROR({subtotal_cells['流動資產']}/{subtotal_cells['流動負債']},\"無流動負債\")",
         '0.00"倍"', "> 2 倍表示短期償債能力佳"),
        ("流動資產占比", "流動資產 ÷ 資產總計",
         f"=IFERROR({subtotal_cells['流動資產']}/G{total_asset_row},0)", PCT, "資產變現能力"),
        ("緊急預備金", "現金及約當現金 ÷ 近 12 月平均月支出",
         ratios["emergency_months"] if ratios["emergency_months"] is not None else "無支出資料",
         '0.0"個月"', "建議至少 6 個月"),
        ("近 12 月儲蓄率", "（收入 − 支出）÷ 收入",
         ratios["savings_rate"] if ratios["savings_rate"] is not None else "無收入資料",
         PCT, "收入中能存下的比例"),
    ]
    for name, formula_text, val, fmt, ref in ratio_rows:
        r += 1
        s.cell(r, 2, name, bold=True)
        s.cell(r, 3, formula_text)
        ws_bs.merge_cells(start_row=r, start_column=3, end_row=r, end_column=6)
        s.cell(r, 7, val, fmt, bold=True, align="right")
        s.cell(r, 8, ref, color="64748B")
    s.widths([10, 26, 12, 7, 15, 10, 17, 34])
    s.print_setup(bs_hdr)
    ws_bs.freeze_panes = f"A{bs_hdr + 1}"

    # ================================================================ 收支損益表
    s = _Sheet(ws_is)
    r = s.title("收支損益表", sub, 4)
    s.header(r, ["科目代號", "會計科目", f"本期金額（{base}）", "占收入比"])
    is_hdr = r
    inc_stmt = db.income_statement(start, end)

    def is_section(title: str, cats: list[dict], tlabel: str) -> str:
        nonlocal r
        r += 1
        s.cell(r, 1, None, fill=FILL_SUB)
        s.cell(r, 2, title, bold=True, fill=FILL_SUB)
        s.cell(r, 3, None, fill=FILL_SUB)
        s.cell(r, 4, None, fill=FILL_SUB)
        g1 = r + 1
        for c in sorted(cats, key=lambda c: ccodes[c["id"]]):
            r += 1
            s.cell(r, 1, _code(ccodes[c["id"]]), align="center")
            s.cell(r, 2, c["name"], indent=1)
            s.cell(r, 3, "=" + sumifs("K" if tlabel == "收入" else "L", tlabel, P1, P2, f"B{r}"), bfmt)
        r += 1
        s.cell(r, 2, f"{title}合計", bold=True, fill=FILL_LIGHT, align="right")
        s.cell(r, 1, None, fill=FILL_LIGHT)
        s.cell(r, 3, f"=SUM(C{g1}:C{r - 1})" if r - 1 >= g1 else 0, bfmt, bold=True,
               fill=FILL_LIGHT)
        s.cell(r, 4, None, fill=FILL_LIGHT)
        return f"C{r}", g1

    inc_cell, inc_first = is_section("收入", inc_stmt["income"], "收入")
    inc_last = int(inc_cell[1:]) - 1
    exp_cell, exp_first = is_section("支出（費用）", inc_stmt["expense"], "支出")
    exp_last = int(exp_cell[1:]) - 1
    for rr in list(range(inc_first, inc_last + 1)) + list(range(exp_first, exp_last + 1)) + \
            [int(inc_cell[1:]), int(exp_cell[1:])]:
        s.cell(rr, 4, f"=IFERROR(C{rr}/{inc_cell},0)", PCT,
               fill=FILL_LIGHT if rr in (int(inc_cell[1:]), int(exp_cell[1:])) else None)
    r += 1
    s.cell(r, 2, "本期收支結餘", bold=True, fill=FILL_TOTAL, align="right")
    s.cell(r, 1, None, fill=FILL_TOTAL)
    s.cell(r, 3, f"={inc_cell}-{exp_cell}", bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 4, f"=IFERROR(C{r}/{inc_cell},0)", PCT, bold=True, fill=FILL_TOTAL)
    s.total_border(r, 1, 4)
    oper_row = r
    r += 1
    s.cell(r, 1, None, fill=FILL_SUB)
    s.cell(r, 2, "業外損益", bold=True, fill=FILL_SUB)
    s.cell(r, 3, None, fill=FILL_SUB)
    s.cell(r, 4, None, fill=FILL_SUB)
    r += 1
    s.cell(r, 1, 7101, align="center")
    s.cell(r, 2, f"{ADJUST_ACCOUNT}（市值變動）", indent=1)
    s.cell(r, 3, inc_stmt["adjust"], bfmt)
    s.cell(r, 4, None)
    adj_row = r
    r += 1
    s.cell(r, 1, 7201, align="center")
    s.cell(r, 2, f"{FX_ACCOUNT}（匯率變動）", indent=1)
    s.cell(r, 3, inc_stmt["fx"], bfmt)
    s.cell(r, 4, None)
    fx_row = r
    r += 1
    s.cell(r, 1, 7301, align="center")
    s.cell(r, 2, f"{REALIZED_ACCOUNT}（證券買賣）", indent=1)
    s.cell(r, 3, inc_stmt["realized"], bfmt)
    s.cell(r, 4, None)
    real_row = r
    r += 1
    s.cell(r, 2, "本期綜合損益（淨資產增減）", bold=True, fill=FILL_TOTAL, align="right", color=BLUE)
    s.cell(r, 1, None, fill=FILL_TOTAL)
    s.cell(r, 3, f"=C{oper_row}+C{adj_row}+C{fx_row}+C{real_row}", bfmt, bold=True, fill=FILL_TOTAL,
           color=BLUE)
    s.cell(r, 4, None, fill=FILL_TOTAL)
    s.total_border(r, 1, 4, double=True)
    compr_row = r
    r += 2
    note = ws_is.cell(row=r, column=1, value="註：收入及支出金額以 SUMIFS 公式自「收支明細」工作表彙總；"
                      "業外損益為市值評價、匯率變動與證券處分之損益。")
    note.font = F_SUBT
    ws_is.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
    s.widths([11, 34, 20, 12])
    s.print_setup(is_hdr)

    # ================================================================ 月度收支
    s = _Sheet(ws_mon)
    r = s.title("月度收支表", sub, 6)
    s.header(r, ["月份", f"收入（{base}）", f"支出（{base}）", "結餘", "儲蓄率", "累計結餘"])
    mon_hdr = r
    months = month_keys(start, end)
    m_first = r + 1
    for i, ym in enumerate(months):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        y, m = map(int, ym.split("-"))
        d1 = f"MAX(DATE({y},{m},1),{P1})"
        d2 = f"MIN(EOMONTH(DATE({y},{m},1),0),{P2})"
        s.cell(r, 1, f"{y}年{m:02d}月", fill=fill, align="center")
        s.cell(r, 2, "=" + sumifs("K", "收入", d1, d2), bfmt, fill=fill, color=GREEN)
        s.cell(r, 3, "=" + sumifs("L", "支出", d1, d2), bfmt, fill=fill, color=RED)
        s.cell(r, 4, f"=B{r}-C{r}", bfmt, fill=fill, bold=True)
        s.cell(r, 5, f"=IFERROR(D{r}/B{r},0)", PCT, fill=fill)
        s.cell(r, 6, f"=D{r}" if r == m_first else f"=F{r - 1}+D{r}", bfmt, fill=fill)
    m_last = r
    r += 1
    s.cell(r, 1, "合計", bold=True, fill=FILL_TOTAL, align="center")
    s.cell(r, 2, f"=SUM(B{m_first}:B{m_last})", bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 3, f"=SUM(C{m_first}:C{m_last})", bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 4, f"=B{r}-C{r}", bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 5, f"=IFERROR(D{r}/B{r},0)", PCT, bold=True, fill=FILL_TOTAL)
    s.cell(r, 6, None, fill=FILL_TOTAL)
    s.total_border(r, 1, 6, double=True)
    r += 1
    s.cell(r, 1, "月平均", bold=True, fill=FILL_LIGHT, align="center")
    n = len(months)
    s.cell(r, 2, f"=B{r - 1}/{n}", bfmt, fill=FILL_LIGHT)
    s.cell(r, 3, f"=C{r - 1}/{n}", bfmt, fill=FILL_LIGHT)
    s.cell(r, 4, f"=D{r - 1}/{n}", bfmt, fill=FILL_LIGHT)
    s.cell(r, 5, None, fill=FILL_LIGHT)
    s.cell(r, 6, None, fill=FILL_LIGHT)
    s.widths([14, 16, 16, 16, 12, 16])
    s.print_setup(mon_hdr)
    ws_mon.freeze_panes = f"A{mon_hdr + 1}"

    chart = BarChart()
    chart.type = "col"
    chart.title = "每月收入與支出"
    chart.x_axis.delete = False
    chart.y_axis.delete = False
    chart.y_axis.numFmt = "#,##0"
    chart.y_axis.majorGridlines = None
    chart.height = 9
    chart.width = 22
    data = Reference(ws_mon, min_col=2, max_col=3, min_row=mon_hdr, max_row=m_last)
    cats = Reference(ws_mon, min_col=1, min_row=m_first, max_row=m_last)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.series[0].graphicalProperties.solidFill = GREEN
    chart.series[0].graphicalProperties.line.solidFill = GREEN
    chart.series[1].graphicalProperties.solidFill = "E0464B"
    chart.series[1].graphicalProperties.line.solidFill = "E0464B"
    ws_mon.add_chart(chart, "H4")

    # 淨資產趨勢
    r += 3
    s.cell(r, 1, "月底淨資產趨勢", bold=True, color=BLUE, border=False)
    r += 1
    s.header(r, ["月份", "總資產", "總負債", "淨資產", "月增減", ""])
    ws_mon.cell(row=r, column=6).fill = PatternFill(fill_type=None)
    nw_hdr = r
    nw_first = r + 1
    for i, item in enumerate(db.net_worth_series(months)):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        y, m = map(int, item["month"].split("-"))
        s.cell(r, 1, f"{y}年{m:02d}月", fill=fill, align="center")
        s.cell(r, 2, item["assets"], bfmt, fill=fill)
        s.cell(r, 3, item["liabilities"], bfmt, fill=fill)
        s.cell(r, 4, f"=B{r}-C{r}", bfmt, fill=fill, bold=True)
        s.cell(r, 5, None if r == nw_first else f"=D{r}-D{r - 1}", bfmt, fill=fill)
    nw_last = r
    line = LineChart()
    line.title = "月底淨資產"
    line.y_axis.numFmt = "#,##0"
    line.y_axis.majorGridlines = None
    line.x_axis.delete = False
    line.y_axis.delete = False
    line.legend = None
    line.height = 9
    line.width = 22
    line.add_data(Reference(ws_mon, min_col=4, min_row=nw_hdr, max_row=nw_last), titles_from_data=True)
    line.set_categories(Reference(ws_mon, min_col=1, min_row=nw_first, max_row=nw_last))
    line.series[0].graphicalProperties.line.solidFill = BLUE
    line.series[0].graphicalProperties.line.width = 28000
    line.series[0].smooth = False
    ws_mon.add_chart(line, f"H{nw_hdr}")

    # ================================================================ 分類統計
    s = _Sheet(ws_cat)
    use_years = len(months) > 24
    if use_years:
        buckets = [(str(y), f"MAX(DATE({y},1,1),{P1})", f"MIN(DATE({y},12,31),{P2})")
                   for y in range(int(start[:4]), int(end[:4]) + 1)]
        labels = [f"{b[0]}年" for b in buckets]
    else:
        buckets = []
        for ym in months:
            y, m = map(int, ym.split("-"))
            buckets.append((ym, f"MAX(DATE({y},{m},1),{P1})", f"MIN(EOMONTH(DATE({y},{m},1),0),{P2})"))
        labels = [f"{int(b[0][5:])}月" if len({x[0][:4] for x in buckets}) == 1
                  else f"{b[0][:4]}/{b[0][5:]}" for b in buckets]
    ncols = 2 + len(buckets) + 4
    r = s.title("分類統計表", sub + "　｜　預算欄為「每月預算 × 月數」", ncols)
    cat_hdr = r

    def cat_block(kind: str, tlabel: str, value_col: str) -> None:
        nonlocal r
        cats = db.list_categories(kind, include_archived=True)
        used = {c["id"] for c in db.category_totals(start, end, kind)}
        cats = [c for c in cats if c["id"] in used or (not c["archived"] and c["budget"])]
        extra = ["期間預算", "預算執行率"] if kind == "expense" else []
        s.header(r, ["科目代號", f"{tlabel}分類"] + labels + ["合計", "占比"] + extra)
        g1 = r + 1
        for i, c in enumerate(cats):
            r += 1
            fill = FILL_ZEBRA if i % 2 else None
            s.cell(r, 1, _code(ccodes[c["id"]]), fill=fill, align="center")
            s.cell(r, 2, c["name"], fill=fill)
            for j, (_, d1, d2) in enumerate(buckets):
                s.cell(r, 3 + j, "=" + sumifs(value_col, tlabel, d1, d2, f"$B{r}"), bfmt, fill=fill)
            tc = 3 + len(buckets)
            s.cell(r, tc, f"=SUM({get_column_letter(3)}{r}:{get_column_letter(tc - 1)}{r})", bfmt,
                   fill=fill, bold=True)
            if kind == "expense":
                s.cell(r, tc + 2, (c["budget"] or 0) * len(months), bfmt, fill=fill)
                s.cell(r, tc + 3, f'=IF({get_column_letter(tc + 2)}{r}>0,'
                       f'{get_column_letter(tc)}{r}/{get_column_letter(tc + 2)}{r},"")', PCT, fill=fill)
        g2 = r
        r += 1
        tc = 3 + len(buckets)
        s.cell(r, 2, "合計", bold=True, fill=FILL_TOTAL, align="center")
        s.cell(r, 1, None, fill=FILL_TOTAL)
        for col in range(3, tc + 1):
            L = get_column_letter(col)
            s.cell(r, col, f"=SUM({L}{g1}:{L}{g2})" if g2 >= g1 else 0, bfmt, bold=True,
                   fill=FILL_TOTAL)
        TL = get_column_letter(tc)
        for rr in range(g1, g2 + 2):
            s.cell(rr, tc + 1, f"=IFERROR({TL}{rr}/{TL}${r},0)", PCT,
                   fill=FILL_TOTAL if rr == r else (FILL_ZEBRA if (rr - g1) % 2 else None))
        if kind == "expense":
            BL = get_column_letter(tc + 2)
            s.cell(r, tc + 2, f"=SUM({BL}{g1}:{BL}{g2})" if g2 >= g1 else 0, bfmt, bold=True,
                   fill=FILL_TOTAL)
            s.cell(r, tc + 3, f'=IF({BL}{r}>0,{TL}{r}/{BL}{r},"")', PCT, bold=True, fill=FILL_TOTAL)
        s.total_border(r, 1, tc + (3 if kind == "expense" else 1), double=True)
        r += 3

    cat_block("expense", "支出", "L")
    cat_block("income", "收入", "K")
    s.widths([10, 16] + [12.5] * len(buckets) + [15, 9, 14, 11])
    s.print_setup(cat_hdr, landscape=True)
    ws_cat.freeze_panes = f"C{cat_hdr + 1}"

    # ================================================================ 日記簿
    s = _Sheet(ws_jnl)
    r = s.title("日記簿（會計分錄）", sub, 8)
    s.header(r, ["日期", "傳票號碼", "摘要", "科目代號", "會計科目", "科目類別",
                 f"借方金額（{base}）", f"貸方金額（{base}）"])
    j_hdr = r
    j_first = r + 1
    for i, e in enumerate(db.journal(start, end)):
        fill = FILL_ZEBRA if i % 2 else None
        for k, line_ in enumerate(e["lines"]):
            r += 1
            s.cell(r, 1, _d(e["date"]) if k == 0 else None, DATE, fill=fill, align="center")
            s.cell(r, 2, e["voucher"] if k == 0 else None, fill=fill, align="center")
            s.cell(r, 3, e["summary"] if k == 0 else None, fill=fill)
            s.cell(r, 4, _code(line_["code"]), fill=fill, align="center")
            s.cell(r, 5, line_["name"], fill=fill, indent=0 if line_["debit"] else 2)
            s.cell(r, 6, line_["group"], fill=fill, align="center")
            s.cell(r, 7, line_["debit"] or None, bfmt, fill=fill)
            s.cell(r, 8, line_["credit"] or None, bfmt, fill=fill)
    j_last = max(r, j_first)
    r += 1
    s.cell(r, 5, "借貸合計", bold=True, fill=FILL_TOTAL, align="right")
    for col in (1, 2, 3, 4):
        s.cell(r, col, None, fill=FILL_TOTAL)
    s.cell(r, 6, f'=IF(ROUND(G{r}-H{r},2)=0,"✓ 平衡","✗ 不平衡")', bold=True, fill=FILL_TOTAL,
           align="center")
    s.cell(r, 7, f"=SUM(G{j_first}:G{j_last})", bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 8, f"=SUM(H{j_first}:H{j_last})", bfmt, bold=True, fill=FILL_TOTAL)
    s.total_border(r, 1, 8, double=True)
    s.widths([14, 11, 26, 10, 22, 10, 16, 16])
    s.print_setup(j_hdr, landscape=True)
    ws_jnl.freeze_panes = f"A{j_hdr + 1}"

    _ledger_sheet(db, ws_led, start, end, sub, acodes)

    # ================================================================ 試算表
    s = _Sheet(ws_tb)
    r = s.title("試算表（六欄式）", sub + "　｜　期初餘額＋本期發生額＝期末餘額；損益科目為本期發生額", 9)
    s.header(r, ["科目代號", "會計科目", "科目類別", "期初借方", "期初貸方", "本期借方", "本期貸方",
                 f"期末借方（{base}）", f"期末貸方（{base}）"])
    tb_hdr = r
    t_first = r + 1
    for i, row in enumerate(db.trial_balance(start, end)):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        s.cell(r, 1, _code(row["code"]), fill=fill, align="center")
        s.cell(r, 2, row["name"], fill=fill)
        s.cell(r, 3, row["group"], fill=fill, align="center")
        for col, key in ((4, "open_debit"), (5, "open_credit"), (6, "period_debit"), (7, "period_credit")):
            s.cell(r, col, row[key] or None, bfmt, fill=fill)
        # 期末以公式計算：期初＋本期借方－本期貸方，依正負放在借方或貸方
        net = f"(D{r}-E{r}+F{r}-G{r})"
        s.cell(r, 8, f"=IF(ROUND({net},2)>0,{net},0)", bfmt, fill=fill, bold=True)
        s.cell(r, 9, f"=IF(ROUND({net},2)<0,-{net},0)", bfmt, fill=fill, bold=True)
    t_last = max(r, t_first)
    r += 1
    s.cell(r, 1, None, fill=FILL_TOTAL)
    s.cell(r, 2, "合計", bold=True, fill=FILL_TOTAL, align="right")
    s.cell(r, 3, f'=IF(AND(ROUND(D{r}-E{r},0)=0,ROUND(F{r}-G{r},0)=0,ROUND(H{r}-I{r},0)=0),'
                 f'"✓ 借貸平衡","✗ 不平衡")', bold=True, fill=FILL_TOTAL, align="center")
    for col in range(4, 10):
        L = "ABCDEFGHI"[col - 1]
        s.cell(r, col, f"=SUM({L}{t_first}:{L}{t_last})", bfmt, bold=True, fill=FILL_TOTAL)
    s.total_border(r, 1, 9, double=True)
    r += 2
    for text in [
        f"科目編碼：11 流動資產、12 非流動資產、21 流動負債、22 非流動負債、3101 {EQUITY_ACCOUNT}、",
        f"41 收入、51 支出（費用）、7101 {ADJUST_ACCOUNT}、7201 {FX_ACCOUNT}。",
        "期初淨值 = 期初日前一日之淨資產 + 期間內新開立帳戶之期初金額。",
    ]:
        c = ws_tb.cell(row=r, column=1, value=text)
        c.font = F_SUBT
        r += 1
    s.widths([10, 26, 14, 15, 15, 15, 15, 16, 16])
    s.print_setup(tb_hdr, landscape=True)
    ws_tb.freeze_panes = f"C{tb_hdr + 1}"

    # ================================================================ 帳戶清單
    s = _Sheet(ws_acc)
    r = s.title("帳戶清單（會計科目明細）", f"基準日：{end.replace('-', '/')}　｜　編製時間：{made}", 13)
    s.header(r, ["科目代號", "帳戶名稱", "性質", "類別", "流動性", "幣別", "匯率", "期初日期",
                 "期初金額", "期末餘額（原幣）", f"期末餘額（{base}）", "狀態", "備註"])
    a_hdr = r
    for i, acc in enumerate(sorted(db.account_summaries(end, include_archived=True),
                                   key=lambda a: acodes[a["id"]])):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        cf = _num_fmt(acc["currency"])
        vals = [(_code(acodes[acc["id"]]), None, "center"), (acc["name"], None, None),
                ("資產" if acc["kind"] == "asset" else "負債", None, "center"),
                (acc["category"], None, "center"),
                ("流動" if db.is_current(acc) else "非流動", None, "center"),
                (acc["currency"], None, "center"), (acc["rate"], RATE, None),
                (_d(acc["opening_date"]), DATE, "center"), (acc["opening_balance"], cf, None),
                (acc["balance"], cf, None)]
        for col, (v, f, al) in enumerate(vals, 1):
            s.cell(r, col, v, f, fill=fill, align=al)
        s.cell(r, 11, f"=ROUND(J{r}*G{r},2)", bfmt, fill=fill, bold=True)
        s.cell(r, 12, "已封存" if acc["archived"] else "使用中", fill=fill, align="center")
        s.cell(r, 13, acc["note"], fill=fill)
    s.widths([10, 22, 7, 11, 9, 7, 10, 14, 15, 16, 16, 9, 30])
    s.print_setup(a_hdr, landscape=True)
    ws_acc.freeze_panes = f"C{a_hdr + 1}"

    # ================================================================ 財務摘要
    s = _Sheet(ws_sum)
    ws_sum["A1"] = "個人財務報告"
    ws_sum["A1"].font = Font(name=FONT, size=20, bold=True, color=NAVY)
    ws_sum.row_dimensions[1].height = 34
    info_rows = [("編製者", owner), ("報表期間", period), ("資產負債基準日", end.replace("-", "/")),
                 ("本位幣", f"{base_name}（{base}）"), ("編製時間", made)]
    r = 3
    for k, v in info_rows:
        s.cell(r, 1, k, bold=True, fill=FILL_LIGHT)
        s.cell(r, 2, v)
        ws_sum.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
        r += 1
    r += 1
    s.header(r, ["項目", f"金額（{base}）", "說明"])
    sum_hdr = r
    is_inc_row = int(inc_cell[1:])
    is_exp_row = int(exp_cell[1:])
    key_rows = [
        ("資產總計", f"='資產負債表'!G{total_asset_row}", bfmt, "資產負債表"),
        ("負債總計", f"='資產負債表'!G{total_liab_row}", bfmt, "資產負債表"),
        ("淨資產（業主權益）", f"='資產負債表'!G{net_row}", bfmt, "資產總計 − 負債總計"),
        ("本期收入", f"='收支損益表'!C{is_inc_row}", bfmt, "收支損益表"),
        ("本期支出", f"='收支損益表'!C{is_exp_row}", bfmt, "收支損益表"),
        ("本期收支結餘", f"='收支損益表'!C{oper_row}", bfmt, "收入 − 支出"),
        ("本期儲蓄率", f"=IFERROR('收支損益表'!C{oper_row}/'收支損益表'!C{is_inc_row},0)", PCT,
         "結餘 ÷ 收入"),
        ("未實現評價損益", f"='收支損益表'!C{adj_row}", bfmt, "投資市值變動"),
        ("本期綜合損益", f"='收支損益表'!C{compr_row}", bfmt, "淨資產本期增減"),
        ("傳票張數", len(txns), "#,##0", "收支明細"),
    ]
    for i, (k, f, fmt, note_) in enumerate(key_rows):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        s.cell(r, 1, k, bold=True, fill=fill)
        s.cell(r, 2, f, fmt, bold=True, fill=fill, color=BLUE if "淨資產" in k else None)
        s.cell(r, 3, note_, fill=fill, color="64748B")
    r += 2
    c = ws_sum.cell(row=r, column=1, value="各工作表說明")
    c.font = F_SECTION
    for name, desc in [x for x in SHEET_INFO[1:] if x[0] in selected]:
        r += 1
        s.cell(r, 1, name, bold=True)
        s.cell(r, 2, desc)
        ws_sum.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    s.widths([22, 22, 40])
    s.print_setup(sum_hdr)

    _cash_flow_sheet(db, ws_cf, start, end, sub, bfmt, base)
    _investment_sheet(db, ws_inv, start, end, sub, bfmt)
    _tax_sheet(db, ws_tax, int(end[:4]), owner, made, bfmt, base_name, base)

    need = sheets_needed(selected)
    for ws in list(wb.worksheets):
        if ws.title not in need:
            wb.remove(ws)
        elif ws.title not in selected:
            ws.sheet_state = "hidden"
    wb.active = next(i for i, ws in enumerate(wb.worksheets) if ws.sheet_state == "visible")
    wb.calculation.fullCalcOnLoad = True
    wb.save(path)
    return path


def export_ledger(db: Database, path: str, key: tuple, start: str, end: str) -> str:
    """只匯出一個會計科目的分類帳。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "分類帳"
    owner = db.get_setting("owner_name") or "本人"
    sub = (f"編製者：{owner}　｜　期間：{start.replace('-', '/')} 至 {end.replace('-', '/')}　｜　"
           f"編製時間：{dt.datetime.now():%Y/%m/%d %H:%M}")
    _ledger_sheet(db, ws, start, end, sub, {}, [key])
    wb.save(path)
    return path


def _ledger_sheet(db: Database, ws, start: str, end: str, sub: str, acodes: dict, keys: list | None = None) -> None:
    """分類帳：每個會計科目一段，期初餘額、逐筆借貸、以公式累計餘額，並與帳上期末餘額核對。"""
    s = _Sheet(ws)
    r = s.title("分類帳", sub + "　｜　資產、負債科目為原幣，其餘為本位幣", 8)
    s.header(r, ["日期", "傳票號碼", "摘要", "對方科目", "借方", "貸方", "餘額", "核對"])
    hdr = r
    n = 0
    for key in keys or [x["key"] for x in db.ledger_subjects()]:
        lg = db.subject_ledger(key, start, end)
        if not keys and not lg["rows"] and not lg["opening"] and not lg["closing"]:
            continue
        n += 1
        fmt = _num_fmt(lg["currency"])
        debit_side = lg["normal_side"] == "借"
        r += 2 if n > 1 else 1
        s.cell(r, 1, f"{lg['code']}　{lg['name']}", bold=True, fill=FILL_SUB, color=NAVY)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        s.cell(r, 5, f"{lg['label']}　{lg['currency']}　正常餘額：{lg['normal_side']}方",
               fill=FILL_SUB, color="64748B")
        ws.merge_cells(start_row=r, start_column=5, end_row=r, end_column=8)
        r += 1
        s.cell(r, 1, _d(start), DATE, align="center")
        s.cell(r, 3, "期初餘額（上期結轉）", bold=True)
        for col in (2, 4, 5, 6, 8):
            s.cell(r, col, None)
        s.cell(r, 7, lg["opening"], fmt, bold=True)
        first = r + 1
        for i, row in enumerate(lg["rows"]):
            r += 1
            fill = FILL_ZEBRA if i % 2 else None
            s.cell(r, 1, _d(row["date"]), DATE, fill=fill, align="center")
            s.cell(r, 2, row["voucher"], fill=fill, align="center")
            s.cell(r, 3, row["summary"], fill=fill)
            s.cell(r, 4, row["counter"], fill=fill)
            s.cell(r, 5, row["debit"] or None, fmt, fill=fill)
            s.cell(r, 6, row["credit"] or None, fmt, fill=fill)
            s.cell(r, 7, f"=G{r - 1}+E{r}-F{r}" if debit_side else f"=G{r - 1}+F{r}-E{r}", fmt, fill=fill)
            s.cell(r, 8, None, fill=fill)
        last = r
        r += 1
        s.cell(r, 3, "本期合計／期末餘額", bold=True, fill=FILL_TOTAL, align="right")
        for col in (1, 2, 4):
            s.cell(r, col, None, fill=FILL_TOTAL)
        s.cell(r, 5, f"=SUM(E{first}:E{last})" if last >= first else 0, fmt, bold=True, fill=FILL_TOTAL)
        s.cell(r, 6, f"=SUM(F{first}:F{last})" if last >= first else 0, fmt, bold=True, fill=FILL_TOTAL)
        s.cell(r, 7, f"=G{last}", fmt, bold=True, fill=FILL_TOTAL)
        s.cell(r, 8, f'=IF(ROUND(G{r}-({lg["closing"]}),2)=0,"✓ 相符","✗ 不符")', bold=True,
               fill=FILL_TOTAL, align="center")
        s.total_border(r, 1, 8)
    if not n:
        s.cell(r + 1, 1, "本期間沒有任何紀錄", border=False)
    s.widths([14, 11, 28, 26, 15, 15, 16, 10])
    s.print_setup(hdr, landscape=True)
    ws.freeze_panes = f"A{hdr + 1}"



# ====================================================================== 新增工作表
def _cash_flow_sheet(db: Database, ws, start: str, end: str, sub: str, bfmt: str, base: str) -> None:
    from .analytics import cash_flow
    cf = cash_flow(db, start, end)
    s = _Sheet(ws)
    r = s.title("現金流量表（直接法）", sub, 3)
    s.header(r, ["項目", f"金額（{base}）", "說明"])
    hdr = r
    r += 1
    s.cell(r, 1, "期初現金及約當現金", bold=True, fill=FILL_TOTAL)
    s.cell(r, 2, cf["opening"], bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 3, "現金、銀行存款、定期存款、外幣存款", fill=FILL_TOTAL, color="64748B")
    open_row = r
    subtotal_cells = []
    for title, key in (("一、生活（營業）活動之現金流量", "operating"), ("二、投資活動之現金流量", "investing"),
                       ("三、籌資活動之現金流量", "financing"), ("四、其他", "other")):
        r += 1
        s.cell(r, 1, title, bold=True, fill=FILL_SUB)
        s.cell(r, 2, None, fill=FILL_SUB)
        s.cell(r, 3, None, fill=FILL_SUB)
        g1 = r + 1
        for item in cf[key]:
            r += 1
            s.cell(r, 1, item["name"], indent=2)
            s.cell(r, 2, item["amount"], bfmt, color=GREEN if item["amount"] > 0 else RED)
            s.cell(r, 3, "流入" if item["amount"] > 0 else "流出", color="64748B")
        r += 1
        s.cell(r, 1, "淨現金流入（流出）", bold=True, fill=FILL_LIGHT, align="right")
        s.cell(r, 2, f"=SUM(B{g1}:B{r - 1})" if r - 1 >= g1 else 0, bfmt, bold=True, fill=FILL_LIGHT)
        s.cell(r, 3, None, fill=FILL_LIGHT)
        subtotal_cells.append(f"B{r}")
    r += 1
    s.cell(r, 1, "本期現金及約當現金淨增減", bold=True, fill=FILL_TOTAL)
    s.cell(r, 2, "=" + "+".join(subtotal_cells), bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 3, None, fill=FILL_TOTAL)
    net_row = r
    r += 1
    s.cell(r, 1, "期末現金及約當現金", bold=True, fill=FILL_TOTAL, color=BLUE)
    s.cell(r, 2, f"=B{open_row}+B{net_row}", bfmt, bold=True, fill=FILL_TOTAL, color=BLUE)
    s.cell(r, 3, None, fill=FILL_TOTAL)
    s.total_border(r, 1, 3, double=True)
    end_row = r
    r += 1
    s.cell(r, 1, "帳上期末現金及約當現金（勾稽）")
    s.cell(r, 2, cf["closing"], bfmt)
    s.cell(r, 3, f'=IF(ROUND(B{end_row}-B{r},0)=0,"✓ 相符","✗ 不符")', bold=True, align="center")
    s.widths([40, 18, 30])
    s.print_setup(hdr)


def _investment_sheet(db: Database, ws, start: str, end: str, sub: str, bfmt: str) -> None:
    from .investments import KIND_LABELS, Investments
    inv = Investments(db)
    s = _Sheet(ws)
    r = s.title("投資明細表", sub.replace("期間", "基準日：" + end.replace("-", "/") + "　｜　交易期間"), 10)
    s.header(r, ["代號", "名稱", "投資帳戶", "持股", "平均成本", "總成本", "最近評價市價", "帳面價值", "未實現損益", "報酬率"])
    hdr = r
    g1 = r + 1
    for i, h in enumerate(inv.holdings(end)):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        s.cell(r, 1, h["code"], fill=fill, align="center")
        s.cell(r, 2, h["name"], fill=fill)
        s.cell(r, 3, h["account_name"], fill=fill)
        s.cell(r, 4, h["shares"], "#,##0", fill=fill)
        s.cell(r, 5, f"=IFERROR(F{r}/D{r},0)", "#,##0.00", fill=fill)
        s.cell(r, 6, round(h["cost"], 2), bfmt, fill=fill)
        s.cell(r, 7, h["price"] or None, "#,##0.00", fill=fill)
        s.cell(r, 8, h["market_value"], bfmt, fill=fill, bold=True)
        s.cell(r, 9, f"=H{r}-F{r}", bfmt, fill=fill)
        s.cell(r, 10, f"=IFERROR(I{r}/F{r},0)", PCT, fill=fill)
    g2 = r
    r += 1
    s.cell(r, 2, "合計", bold=True, fill=FILL_TOTAL, align="center")
    for col in (1, 3, 4, 5, 7):
        s.cell(r, col, None, fill=FILL_TOTAL)
    for col, L in ((6, "F"), (8, "H"), (9, "I")):
        s.cell(r, col, f"=SUM({L}{g1}:{L}{g2})" if g2 >= g1 else 0, bfmt, bold=True, fill=FILL_TOTAL)
    s.cell(r, 10, f"=IFERROR(I{r}/F{r},0)", PCT, bold=True, fill=FILL_TOTAL)
    s.total_border(r, 1, 10, double=True)
    r += 3
    ws.cell(row=r, column=1, value="期間交易紀錄").font = F_SECTION
    r += 1
    s.header(r, ["日期", "標的", "類別", "股數", "價格", "手續費", "證交稅", "股利", "補充保費", "備註"])
    for i, e in enumerate(x for x in inv.events(start=start, end=end) if x["kind"] != "price"):
        r += 1
        fill = FILL_ZEBRA if i % 2 else None
        vals = [(_d(e["date"]), DATE), (f"{e['code']} {e['sec_name']}".strip(), None),
                (KIND_LABELS[e["kind"]], None), (e["shares"] or None, "#,##0"),
                (e["price"] or None, "#,##0.00"), (e["fee"] or None, bfmt), (e["tax"] or None, bfmt),
                (e["amount"] or None, bfmt), (e["nhi"] or None, bfmt),
                (e["note"] + (f"（{e['cash_name']}）" if e.get("txn_id") else ""), None)]
        for col, (v, f) in enumerate(vals, 1):
            s.cell(r, col, v, f, fill=fill, align="center" if col in (1, 3) else None)
    ps = inv.period_summary(start, end)
    r += 2
    for label, v in (("期間已實現損益", ps["realized"]), ("期間現金股利", ps["dividends"]),
                     ("期間健保補充保費", ps["nhi"])):
        s.cell(r, 2, label, bold=True, fill=FILL_LIGHT)
        s.cell(r, 3, v, bfmt, bold=True, fill=FILL_LIGHT)
        r += 1
    s.widths([14, 18, 16, 11, 11, 15, 10, 15, 14, 18])
    s.print_setup(hdr, landscape=True)


def _tax_sheet(db: Database, ws, year: int, owner: str, made: str, bfmt: str, base_name: str,
               base: str) -> None:
    from .analytics import tax_summary
    ts = tax_summary(db, year)
    s = _Sheet(ws)
    r = s.title(f"{year} 年度報稅彙總（民國 {year - 1911} 年）",
                f"編製者：{owner}　｜　單位：{base_name}（{base}）　｜　編製時間：{made}　｜　僅供申報參考", 4)
    s.header(r, ["項目", f"金額（{base}）", "來源分類", "說明"])
    hdr = r
    for title, items in (("所得", ts["incomes"]), ("可列舉扣除與相關支出", ts["deductions"])):
        r += 1
        s.cell(r, 1, title, bold=True, fill=FILL_SUB)
        for col in (2, 3, 4):
            s.cell(r, col, None, fill=FILL_SUB)
        for it in items:
            r += 1
            s.cell(r, 1, it["label"], indent=1)
            s.cell(r, 2, it["amount"], bfmt, bold=True)
            s.cell(r, 3, "、".join(it["categories"]))
            c = s.cell(r, 4, it["note"], color="64748B")
            c.alignment = Alignment(wrap_text=True, vertical="center")
            ws.row_dimensions[r].height = 36 if len(it["note"]) > 30 else 20
        if not items:
            r += 1
            s.cell(r, 1, "（無已歸類項目，可在程式「設定 → 收支分類 → 稅務歸類」設定）", color="64748B")
    r += 1
    s.cell(r, 1, "處分投資損益（參考）", indent=1)
    s.cell(r, 2, ts["realized"], bfmt)
    s.cell(r, 3, "")
    s.cell(r, 4, ts["realized_note"], color="64748B")
    r += 2
    c = ws.cell(row=r, column=1, value="註：稅法規定時有修訂，實際申報請以財政部最新規定與國稅局所得資料為準。")
    c.font = F_SUBT
    s.widths([30, 16, 34, 60])
    s.print_setup(hdr, landscape=True)
