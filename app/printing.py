"""列印與 PDF：傳票、日記簿、總分類帳、六欄式試算表、資產負債表、收支損益表、權益變動表。

報表先組成 HTML，再以 QTextDocument 分頁列印；表頭（<thead>）會在每頁重複，頁尾自動加頁碼。
"""

from __future__ import annotations

import datetime as dt
from html import escape

from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter

from .database import CURRENCIES, TYPE_LABELS, Database, voucher_no
from .theme import FONT_FAMILY, fmt_date, fmt_num

# 可列印的報表：(代碼, 名稱)
REPORTS = [
    ("vouchers", "傳票（每張一頁）"),
    ("journal", "日記簿"),
    ("ledger", "總分類帳"),
    ("trial", "試算表（六欄式）"),
    ("bs", "資產負債表"),
    ("is", "收支損益表"),
    ("equity", "權益變動表"),
]

_CSS = """
body { font-size: 10pt; }
h1 { font-size: 16pt; margin: 0; }
h2 { font-size: 13pt; margin: 6px 0 2px 0; }
.sub { color: #475569; font-size: 9pt; }
table.t { border-collapse: collapse; width: 100%; margin-top: 6px; }
table.t th { background: #E2E8F0; font-weight: bold; padding: 4px; border: 1px solid #94A3B8;
             font-size: 9pt; white-space: nowrap; }
table.t td { padding: 3px 4px; border: 1px solid #CBD5E1; font-size: 9pt; }
.r { text-align: right; white-space: nowrap; }
.c { text-align: center; white-space: nowrap; }
.b { font-weight: bold; }
.tot td { font-weight: bold; background: #EEF2F7; }
.sec td { font-weight: bold; background: #F1F5F9; }
.void { color: #C62828; font-size: 14pt; font-weight: bold; }
"""


def _n(v: float, base: str, blank_zero: bool = True) -> str:
    return "" if blank_zero and not v else fmt_num(v, base)


class Report:
    def __init__(self, db: Database):
        self.db = db
        self.base = db.base_currency
        owner = db.get_setting("owner_name") or "本人"
        name = CURRENCIES.get(self.base, (self.base,))[0]
        self.unit = f"單位：{name}（{self.base}）"
        self.owner = f"編製者：{escape(owner)}"
        self.made = f"列印時間：{dt.datetime.now():%Y/%m/%d %H:%M}"

    # ------------------------------------------------------------------ 共用
    def _head(self, title: str, period: str, first: bool) -> str:
        brk = "" if first else ' style="page-break-before: always"'
        return (f'<h1 align="center"{brk}>{escape(title)}</h1>'
                f'<p class="sub" align="center">{self.owner}　｜　{escape(period)}　｜　{self.unit}'
                f'　｜　{self.made}</p>')

    @staticmethod
    def _table(heads: list[tuple[str, str]], rows: list[str], widths: list[int] | None = None) -> str:
        cols = "".join(f'<th width="{w}%">{escape(h)}</th>' if widths else f"<th>{escape(h)}</th>"
                       for (h, _), w in zip(heads, widths or [0] * len(heads)))
        return f'<table class="t" cellspacing="0"><thead><tr>{cols}</tr></thead><tbody>{"".join(rows)}</tbody></table>'

    @staticmethod
    def _tr(cells: list[tuple[str, str]], cls: str = "") -> str:
        tds = "".join(f'<td class="{c}">{v}</td>' for v, c in cells)
        return f'<tr class="{cls}">{tds}</tr>' if cls else f"<tr>{tds}</tr>"

    # ------------------------------------------------------------------ 傳票
    def voucher_kind(self, t: dict, lines: list[dict]) -> str:
        """有「現金」科目的分錄依方向為現金收入／支出傳票，其餘為轉帳傳票。"""
        cash = {a["id"] for a in self.db.list_accounts(include_archived=True) if a["category"] == "現金"}
        dr = any(ln["kind"] == "account" and ln["id"] in cash and ln["debit"] for ln in lines)
        cr = any(ln["kind"] == "account" and ln["id"] in cash and ln["credit"] for ln in lines)
        if dr and not cr:
            return "現金收入傳票"
        if cr and not dr:
            return "現金支出傳票"
        return "轉帳傳票"

    def voucher(self, txn_id: int, first: bool = True) -> str:
        t = self.db.get_transaction(txn_id)
        lines = self.db.txn_lines_of(t, live=False)
        memos = {}
        if t["type"] == "journal":
            for ln in self.db.get_lines(txn_id):
                key = (("account", ln["account_id"]) if ln["account_id"] else
                       ("category", ln["category_id"]) if ln["category_id"] else ("special", ln["special"]))
                memos.setdefault(key, []).append(ln["memo"])
        rows, d, c = [], 0.0, 0.0
        for ln in lines:
            left = memos.get((ln["kind"], ln["id"]))
            memo = left.pop(0) if left else ""
            d += ln["debit"]
            c += ln["credit"]
            rows.append(self._tr([(escape(ln["code"]), "c"), (escape(ln["name"]), ""), (escape(memo or ""), ""),
                                  (_n(ln["debit"], self.base), "r"), (_n(ln["credit"], self.base), "r")]))
        rows.append(self._tr([("", ""), ("合　計", "c"), ("", ""), (fmt_num(d, self.base), "r"),
                              (fmt_num(c, self.base), "r")], "tot"))
        brk = "" if first else ' style="page-break-before: always"'
        roc = int(t["date"][:4]) - 1911
        void = f'<p class="void" align="center">【已作廢】{escape(t["void_reason"] or "")}</p>' if t["void"] else ""
        return (f'<h1 align="center"{brk}>{self.voucher_kind(t, lines)}</h1>{void}'
                f'<table width="100%"><tr><td>傳票號碼：<b>{voucher_no(txn_id)}</b></td>'
                f'<td align="center">日期：民國 {roc} 年 {int(t["date"][5:7])} 月 {int(t["date"][8:10])} 日'
                f'（{fmt_date(t["date"])}）</td><td align="right">{self.unit}</td></tr>'
                f'<tr><td colspan="3">摘要：{escape(t["note"] or TYPE_LABELS[t["type"]])}</td></tr></table>'
                + self._table([("科目代號", ""), ("會計科目", ""), ("摘要", ""), ("借方金額", ""), ("貸方金額", "")],
                              rows, [12, 30, 26, 16, 16])
                + '<table class="t" cellspacing="0" width="100%" style="margin-top:14px"><tr>'
                + "".join(f'<th width="25%">{x}</th>' for x in ("核　准", "會　計", "覆　核", "製　單"))
                + "</tr><tr>" + "<td>&nbsp;<br>&nbsp;<br>&nbsp;<br>&nbsp;</td>" * 4 + "</tr></table>")

    def vouchers(self, start: str, end: str, first: bool = True) -> str:
        ids = [r["id"] for r in self.db._q("SELECT id FROM transactions WHERE void = 0 AND date BETWEEN ? AND ?"
                                          " ORDER BY date, id", (start, end))]
        if not ids:
            return self._head("傳票", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", first) + "<p>本期間沒有傳票。</p>"
        return "".join(self.voucher(i, first and n == 0) for n, i in enumerate(ids))

    # ------------------------------------------------------------------ 帳簿
    def journal(self, start: str, end: str, first: bool = True) -> str:
        rows, d, c = [], 0.0, 0.0
        for e in self.db.journal(start, end):
            for k, ln in enumerate(e["lines"]):
                d += ln["debit"]
                c += ln["credit"]
                rows.append(self._tr([(fmt_date(e["date"]) if k == 0 else "", "c"),
                                      (e["voucher"] if k == 0 else "", "c"),
                                      (escape(e["summary"]) if k == 0 else "", ""),
                                      (escape(ln["code"]), "c"),
                                      (("" if ln["debit"] else "　　") + escape(ln["name"]), ""),
                                      (_n(ln["debit"], self.base), "r"), (_n(ln["credit"], self.base), "r")]))
        ok = "✓ 借貸平衡" if abs(d - c) < 0.5 else "✗ 借貸不平衡"
        rows.append(self._tr([("", ""), ("", ""), ("", ""), ("", ""), (f"借貸合計　{ok}", "r"),
                              (fmt_num(d, self.base), "r"), (fmt_num(c, self.base), "r")], "tot"))
        return (self._head("日記簿", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", first)
                + self._table([("日期", ""), ("傳票號碼", ""), ("摘要", ""), ("代號", ""), ("會計科目", ""),
                               ("借方", ""), ("貸方", "")], rows, [12, 11, 20, 7, 22, 14, 14]))

    def ledger(self, start: str, end: str, first: bool = True) -> str:
        codes = self.db.account_codes()
        out = [self._head("總分類帳", f"期間：{fmt_date(start)} 至 {fmt_date(end)}　｜　金額為各帳戶原幣", first)]
        n = 0
        for acc in sorted(self.db.list_accounts(include_archived=True), key=lambda a: codes[a["id"]]):
            lg = self.db.ledger(acc["id"], start, end)
            if not lg["rows"] and not lg["opening"] and not lg["closing"]:
                continue
            n += 1
            cur = acc["currency"]
            rows = [self._tr([(fmt_date(start), "c"), ("", ""), ("期初餘額（上期結轉）", "b"), ("", ""), ("", ""),
                              ("", ""), (fmt_num(lg["opening"], cur), "r")])]
            for r in lg["rows"]:
                rows.append(self._tr([(fmt_date(r["date"]), "c"), (escape(r["voucher"]), "c"),
                                      (escape(r["summary"]), ""), (escape(r["counter"]), ""),
                                      (_n(r["debit"], cur), "r"), (_n(r["credit"], cur), "r"),
                                      (fmt_num(r["balance"], cur), "r")]))
            rows.append(self._tr([("", ""), ("", ""), ("本期合計／期末餘額", "b"), ("", ""),
                                  (fmt_num(lg["debit_total"], cur), "r"), (fmt_num(lg["credit_total"], cur), "r"),
                                  (fmt_num(lg["closing"], cur), "r")], "tot"))
            out.append(f'<h2>{codes[acc["id"]]}　{escape(acc["name"])}'
                       f'<span style="font-size:9pt; font-weight:normal; color:#475569">'
                       f'　（{escape(acc["category"])}，{cur}，正常餘額在{lg["normal_side"]}方）</span></h2>')
            out.append(self._table([("日期", ""), ("傳票號碼", ""), ("摘要", ""), ("對方科目", ""), ("借方", ""),
                                    ("貸方", ""), ("餘額", "")], rows, [12, 11, 21, 20, 12, 12, 12]))
        if not n:
            out.append("<p>本期間沒有任何帳戶紀錄。</p>")
        return "".join(out)

    # ------------------------------------------------------------------ 報表
    def trial(self, start: str, end: str, first: bool = True) -> str:
        keys = ("open_debit", "open_credit", "period_debit", "period_credit", "debit", "credit")
        data = self.db.trial_balance(start, end)
        rows = [self._tr([(escape(r["code"]), "c"), (escape(r["name"]), ""), (escape(r["group"]), "c")]
                         + [(_n(r[k], self.base), "r") for k in keys]) for r in data]
        tot = {k: sum(r[k] for r in data) for k in keys}
        ok = all(abs(tot[a] - tot[b]) < 0.5 for a, b in zip(keys[::2], keys[1::2]))
        rows.append(self._tr([("", ""), ("合計　" + ("✓ 借貸平衡" if ok else "✗ 不平衡"), "b"), ("", "")]
                             + [(fmt_num(tot[k], self.base), "r") for k in keys], "tot"))
        heads = [("代號", ""), ("會計科目", ""), ("類別", ""), ("期初借方", ""), ("期初貸方", ""),
                 ("本期借方", ""), ("本期貸方", ""), ("期末借方", ""), ("期末貸方", "")]
        return (self._head("試算表（六欄式）", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", first)
                + self._table(heads, rows, [6, 18, 6, 11, 11, 12, 12, 12, 12])
                + '<p class="sub">期初餘額＋本期借貸發生額＝期末餘額；損益科目只有本期發生額。</p>')

    def bs(self, start: str, end: str, first: bool = True) -> str:
        b = self.db.balance_sheet(end)
        total = b["assets"] or 1
        rows = []

        def group(name: str, sign: int):
            rows.append(self._tr([(name, "b"), ("", ""), ("", "")], "sec"))
            for a in sorted(b["groups"][name], key=lambda a: a["code"]):
                v = a["base_value"] * sign
                rows.append(self._tr([(f'　{a["code"]}　{escape(a["name"])}', ""), (fmt_num(v, self.base), "r"),
                                      (f"{v / total:.1%}", "r")]))
            v = b["totals"][name]
            rows.append(self._tr([(f"{name}合計", "b"), (fmt_num(v, self.base), "r"), (f"{v / total:.1%}", "r")]))

        group("流動資產", 1)
        group("非流動資產", 1)
        rows.append(self._tr([("資產總計", "b"), (fmt_num(b["assets"], self.base), "r"), ("100.0%", "r")], "tot"))
        group("流動負債", -1)
        group("非流動負債", -1)
        rows.append(self._tr([("負債總計", "b"), (fmt_num(b["liabilities"], self.base), "r"),
                              (f'{b["liabilities"] / total:.1%}', "r")], "tot"))
        rows.append(self._tr([("淨資產（業主權益）", "b"), (fmt_num(b["net"], self.base), "r"),
                              (f'{b["net"] / total:.1%}', "r")], "tot"))
        return (self._head("資產負債表", f"基準日：{fmt_date(end)}", first)
                + self._table([("會計科目", ""), ("金額", ""), ("占總資產", "")], rows, [60, 25, 15]))

    def income(self, start: str, end: str, first: bool = True) -> str:
        s = self.db.income_statement(start, end)
        ccodes = self.db.category_codes()
        rows = []
        for title, items, key in (("收入", s["income"], "total_income"), ("支出（費用）", s["expense"], "total_expense")):
            rows.append(self._tr([(title, "b"), ("", "")], "sec"))
            for c in sorted(items, key=lambda c: ccodes[c["id"]]):
                rows.append(self._tr([(f'　{ccodes[c["id"]]}　{escape(c["name"])}', ""),
                                      (fmt_num(c["total"], self.base), "r")]))
            rows.append(self._tr([(f"{title}合計", "b"), (fmt_num(s[key], self.base), "r")]))
        rows.append(self._tr([("本期收支結餘", "b"), (fmt_num(s["operating"], self.base), "r")], "tot"))
        rows.append(self._tr([("業外損益", "b"), ("", "")], "sec"))
        for name, key in (("未實現評價損益", "adjust"), ("處分投資損益", "realized"), ("兌換損益", "fx")):
            rows.append(self._tr([(f"　{name}", ""), (fmt_num(s[key], self.base), "r")]))
        rows.append(self._tr([("本期綜合損益", "b"), (fmt_num(s["comprehensive"], self.base), "r")], "tot"))
        return (self._head("收支損益表", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", first)
                + self._table([("會計科目", ""), ("金額", "")], rows, [70, 30]))

    def equity(self, start: str, end: str, first: bool = True) -> str:
        e = self.db.equity_statement(start, end)
        rows = [self._tr([(escape(n), ""), (fmt_num(v, self.base), "r")]) for n, v in e["rows"]]
        rows.append(self._tr([("期末淨值", "b"), (fmt_num(e["closing"], self.base), "r")], "tot"))
        closed = [y for y in self.db.year_closings() if start[:4] <= str(y) <= end[:4]]
        note = (f'<p class="sub">已辦理年度結帳：{"、".join(map(str, sorted(closed)))} 年，'
                "本期損益已結轉累積淨值。</p>") if closed else ""
        return (self._head("權益變動表", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", first)
                + self._table([("項目", ""), ("金額", "")], rows, [70, 30]) + note)

    def build_voucher(self, txn_id: int) -> str:
        return f"<html><head><style>{_CSS}</style></head><body>{self.voucher(txn_id)}</body></html>"

    def build(self, keys: list[str], start: str, end: str) -> str:
        fns = {"vouchers": self.vouchers, "journal": self.journal, "ledger": self.ledger, "trial": self.trial,
               "bs": self.bs, "is": self.income, "equity": self.equity}
        body = "".join(fns[k](start, end, n == 0) for n, k in enumerate(keys))
        return f"<html><head><style>{_CSS}</style></head><body>{body}</body></html>"


def make_document(html: str) -> QTextDocument:
    doc = QTextDocument()
    doc.setDefaultFont(QFont(FONT_FAMILY, 10))
    doc.setHtml(html)
    return doc


def setup_printer(printer: QPrinter, landscape: bool = False) -> QPrinter:
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
    return printer


def print_html(html: str, printer: QPrinter) -> None:
    make_document(html).print_(printer)


def save_pdf(html: str, path: str, landscape: bool = False) -> str:
    printer = setup_printer(QPrinter(QPrinter.PrinterMode.HighResolution), landscape)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    print_html(html, printer)
    return path

