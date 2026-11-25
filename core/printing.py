"""列印與 PDF：傳票、日記簿、總分類帳、六欄式試算表、資產負債表、收支損益表、權益變動表、
現金流量表，以及一鍵產生的「年度財務報告」（封面、年度摘要、比較報表、比率、投資績效、標籤、報稅參考）。

報表先組成 HTML，再以 QTextDocument 分頁列印；表頭（<thead>）會在每頁重複，頁尾自動加頁碼。
"""

from __future__ import annotations

import datetime as dt
from html import escape

from . import statements as st
from .database import CURRENCIES, TYPE_LABELS, Database, fmt_shares as fmt_shares_, voucher_no
from .fmt import fmt_date, fmt_num

# 可列印的報表：(代碼, 名稱)
REPORTS = [
    ("vouchers", "傳票（每張一頁）"),
    ("journal", "日記簿"),
    ("ledger", "總分類帳"),
    ("trial", "試算表（六欄式）"),
    ("bs", "資產負債表"),
    ("is", "收支損益表"),
    ("equity", "權益變動表"),
    ("ratios", "財務比率分析"),
    ("cashflow", "現金流量表"),
]

# 年度財務報告的章節：(代碼, 名稱, 預設勾選)
ANNUAL_SECTIONS = [
    ("summary", "年度摘要（重點數字、支出排行、預算執行）", True),
    ("bs", "比較資產負債表（年底 vs 去年底）", True),
    ("is", "比較收支損益表（今年 vs 去年）", True),
    ("equity", "權益變動表", True),
    ("cashflow", "現金流量表", True),
    ("ratios", "財務比率分析", True),
    ("monthly", "月度收支表（12 個月）", True),
    ("invest", "投資績效（持股、報酬率）", True),
    ("tags", "標籤／專案彙總", True),
    ("tax", "報稅參考（所得與扣除額）", True),
    ("trial", "試算表（六欄式）", False),
    ("journal", "日記簿（全年所有分錄）", False),
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
.cover { font-size: 26pt; font-weight: bold; color: #1E3A8A; }
.cover2 { font-size: 15pt; color: #334155; }
.kpi td { padding: 8px 10px; border: 1px solid #CBD5E1; font-size: 11pt; }
.kpi th { background: #E8EEFC; padding: 8px 10px; border: 1px solid #94A3B8; font-size: 10pt; }
.toc td { padding: 4px 8px; font-size: 11pt; }
.good { color: #0B7A55; }
.bad { color: #B42318; }
"""


def _pct(v: float | None, blank: str = "") -> str:
    return blank if v is None else f"{v:.1%}"


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
        out = [self._head("總分類帳", f"期間：{fmt_date(start)} 至 {fmt_date(end)}　｜　資產、負債科目為原幣，其餘為本位幣", first)]
        n = 0
        for sub in self.db.ledger_subjects():
            lg = self.db.subject_ledger(sub["key"], start, end)
            if not lg["rows"] and not lg["opening"] and not lg["closing"]:
                continue
            n += 1
            cur = lg["currency"]
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
            out.append(f'<h2>{lg["code"]}　{escape(lg["name"])}'
                       f'<span style="font-size:9pt; font-weight:normal; color:#475569">'
                       f'　（{escape(lg["label"])}，{cur}，正常餘額在{lg["normal_side"]}方）</span></h2>')
            out.append(self._table([("日期", ""), ("傳票號碼", ""), ("摘要", ""), ("對方科目", ""), ("借方", ""),
                                    ("貸方", ""), ("餘額", "")], rows, [12, 11, 21, 20, 12, 12, 12]))
        if not n:
            out.append("<p>本期間沒有任何紀錄。</p>")
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

    def bs(self, start: str, end: str, first: bool = True, compare: str = "none") -> str:
        cdate = st.compare_date(compare, start, end)
        data = st.balance_sheet(self.db, end, cdate)
        cmp = cdate is not None
        rows = []
        for r in data["rows"]:
            if r["style"] == "blank":
                continue
            if r["cur"] is None:
                rows.append(self._tr([(escape(r["name"]), "b")] + [("", "")] * (5 if cmp else 2), "sec"))
                continue
            indent = "　" if r["level"] >= 2 else ""
            cells = [(indent + escape(r["name"]), "b" if r["style"] else ""), (fmt_num(r["cur"], self.base), "r"),
                     (_pct(r["share"]), "r")]
            if cmp:
                d, dp = st.change(r["cur"], r["prev"])
                cells += [(fmt_num(r["prev"], self.base), "r"), (fmt_num(d, self.base, signed=True), "r"),
                          (_pct(dp, "—"), "r")]
            rows.append(self._tr(cells, "tot" if r["style"] in ("total", "grand") else ""))
        if cmp:
            heads = [("會計科目", ""), (fmt_date(end), ""), ("占總資產", ""), (fmt_date(cdate), ""),
                     ("增減金額", ""), ("增減 %", "")]
            widths = [36, 15, 9, 15, 15, 10]
            period = f"基準日：{fmt_date(end)}　比較日：{fmt_date(cdate)}"
        else:
            heads, widths, period = [("會計科目", ""), ("金額", ""), ("占總資產", "")], [60, 25, 15], \
                f"基準日：{fmt_date(end)}"
        title = "比較資產負債表" if cmp else "資產負債表"
        return self._head(title, period, first) + self._table(heads, rows, widths)

    def income(self, start: str, end: str, first: bool = True, compare: str = "none") -> str:
        crange = st.compare_range(compare, start, end)
        data = st.income_statement(self.db, start, end, crange)
        cmp = crange is not None
        rows = []
        items: list[dict] = []
        block: list[dict] = []
        for r in data["rows"]:      # 列印時各類科目依代號排序（畫面上依金額排序）
            if r["code"] and not r["style"]:
                block.append(r)
                continue
            items += sorted(block, key=lambda x: x["code"])
            block = []
            items.append(r)
        items += sorted(block, key=lambda x: x["code"])
        for r in items:
            if r["style"] == "section":
                rows.append(self._tr([(escape(r["name"]), "b")] + [("", "")] * (4 if cmp else 1), "sec"))
                continue
            name = (f'　{r["code"]}　' if r["code"] else "") + escape(r["name"])
            cells = [(name, "b" if r["style"] else ""), (fmt_num(r["cur"], self.base), "r")]
            if cmp:
                d, dp = st.change(r["cur"], r["prev"])
                cells += [(fmt_num(r["prev"], self.base), "r"), (fmt_num(d, self.base, signed=True), "r"),
                          (_pct(dp, "—"), "r")]
            rows.append(self._tr(cells, "tot" if r["style"] in ("total", "grand") else ""))
        period = f"期間：{fmt_date(start)} 至 {fmt_date(end)}"
        if cmp:
            period += f"　比較：{fmt_date(crange[0])} 至 {fmt_date(crange[1])}"
            heads = [("會計科目", ""), ("本期", ""), ("比較期間", ""), ("增減金額", ""), ("增減 %", "")]
            widths = [40, 16, 16, 16, 12]
        else:
            heads, widths = [("會計科目", ""), ("金額", "")], [70, 30]
        return self._head("比較收支損益表" if cmp else "收支損益表", period, first) + self._table(heads, rows, widths)

    def ratios(self, start: str, end: str, first: bool = True, compare: str = "none") -> str:
        crange = st.compare_range(compare, start, end)
        cmp = crange is not None
        rows = []
        for r in st.ratios(self.db, start, end, crange):
            cells = [(escape(r["name"]), "b"), (st.fmt_ratio(r["cur"], r["kind"], r["note"]), "r")]
            if cmp:
                cells += [(st.fmt_ratio(r["prev"], r["kind"]), "r"),
                          (st.fmt_ratio_change(r["cur"], r["prev"], r["kind"]), "r")]
            cells.append((escape(r["help"]), ""))
            rows.append(self._tr(cells))
        if cmp:
            heads = [("比率", ""), ("本期", ""), ("比較期", ""), ("增減", ""), ("說明", "")]
            widths = [20, 12, 12, 14, 42]
            period = (f"基準日：{fmt_date(end)}　比較：{fmt_date(crange[1])}"
                      f"（期間比率以 {fmt_date(start)} 至 {fmt_date(end)} 計算）")
        else:
            heads, widths = [("比率", ""), ("數值", ""), ("說明", "")], [24, 16, 60]
            period = f"基準日：{fmt_date(end)}（期間比率以 {fmt_date(start)} 至 {fmt_date(end)} 計算）"
        return self._head("財務比率分析", period, first) + self._table(heads, rows, widths)

    def equity(self, start: str, end: str, first: bool = True) -> str:
        e = self.db.equity_statement(start, end)
        rows = [self._tr([(escape(n), ""), (fmt_num(v, self.base), "r")]) for n, v in e["rows"]]
        rows.append(self._tr([("期末淨值", "b"), (fmt_num(e["closing"], self.base), "r")], "tot"))
        closed = [y for y in self.db.year_closings() if start[:4] <= str(y) <= end[:4]]
        note = (f'<p class="sub">已辦理年度結帳：{"、".join(map(str, sorted(closed)))} 年，'
                "本期損益已結轉累積淨值。</p>") if closed else ""
        return (self._head("權益變動表", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", first)
                + self._table([("項目", ""), ("金額", "")], rows, [70, 30]) + note)

    def cashflow(self, start: str, end: str, first: bool = True) -> str:
        from .analytics import cash_flow
        cf = cash_flow(self.db, start, end)
        rows = [self._tr([("期初現金及約當現金", "b"), (fmt_num(cf["opening"], self.base), "r")], "tot")]
        for title, key, total_key in (("一、生活（營業）活動之現金流量", "operating", "op_total"),
                                      ("二、投資活動之現金流量", "investing", "inv_total"),
                                      ("三、籌資活動之現金流量", "financing", "fin_total"),
                                      ("四、其他", "other", "other_total")):
            if key == "other" and not cf["other"]:
                continue
            rows.append(self._tr([(title, "b"), ("", "")], "sec"))
            for r in cf[key]:
                rows.append(self._tr([("　" + escape(r["name"]), ""), (fmt_num(r["amount"], self.base), "r")]))
            if not cf[key]:
                rows.append(self._tr([("　（本期無）", ""), ("", "")]))
            rows.append(self._tr([("淨現金流入（流出）", "b"), (fmt_num(cf[total_key], self.base), "r")]))
        rows.append(self._tr([("本期現金及約當現金淨增減", "b"), (fmt_num(cf["net"], self.base, signed=True), "r")],
                             "tot"))
        rows.append(self._tr([("期末現金及約當現金", "b"), (fmt_num(cf["closing"], self.base), "r")], "tot"))
        ok = abs(cf["check"]) < 0.05
        note = ("勾稽：期初 ＋ 本期淨增減 ＝ 期末　✓ 相符" if ok else f"勾稽差額 {fmt_num(cf['check'], self.base)}")
        return (self._head("現金流量表", f"期間：{fmt_date(start)} 至 {fmt_date(end)}（直接法）", first)
                + self._table([("項目", ""), ("金額", "")], rows, [70, 30]) + f'<p class="sub">{note}</p>')

    # ------------------------------------------------------------------ 年度財務報告
    def _kpis(self, year: int) -> dict:
        start, end = f"{year}-01-01", f"{year}-12-31"
        s = self.db.income_statement(start, end)
        bs = self.db.balance_sheet(end)
        prev_end = f"{year - 1}-12-31"
        opening = self.db.balance_sheet(prev_end)["net"]
        r = self.db.ratios(end)
        return {"start": start, "end": end, "net": bs["net"], "opening": opening,
                "change": bs["net"] - opening, "assets": bs["assets"], "liabilities": bs["liabilities"],
                "income": s["total_income"], "expense": s["total_expense"], "operating": s["operating"],
                "other": s["comprehensive"] - s["operating"], "comprehensive": s["comprehensive"],
                "savings": s["operating"] / s["total_income"] if s["total_income"] else None,
                "debt_ratio": r["debt_ratio"]}

    def annual_cover(self, year: int, sections: list[str]) -> str:
        k = self._kpis(year)
        b = self.base
        owner = escape(self.db.get_setting("owner_name") or "本人")

        def cell(v, signed=False):
            cls = "good" if v >= 0 else "bad"
            return f'<span class="{cls}">{fmt_num(v, b, signed=signed)}</span>' if signed else fmt_num(v, b)
        kpi = ('<table class="kpi" cellspacing="0" width="100%">'
               f'<tr><th width="25%">年底淨資產</th><th width="25%">比去年底增減</th>'
               f'<th width="25%">全年收入</th><th width="25%">全年支出</th></tr>'
               f'<tr><td align="center"><b>{fmt_num(k["net"], b)}</b></td>'
               f'<td align="center"><b>{cell(k["change"], True)}</b></td>'
               f'<td align="center">{fmt_num(k["income"], b)}</td><td align="center">{fmt_num(k["expense"], b)}</td></tr>'
               '</table>')
        names = dict((key, name.split("（")[0]) for key, name, _ in ANNUAL_SECTIONS)
        nums = "一二三四五六七八九十"
        toc = "".join(f'<tr><td width="12%" align="right">{nums[i] if i < 10 else i + 1}、</td>'
                      f'<td>{escape(names[s])}</td></tr>' for i, s in enumerate(sections))
        return (f'<p>&nbsp;</p><p>&nbsp;</p><p align="center" class="cover">{owner}</p>'
                f'<p align="center" class="cover">{year} 年度財務報告</p>'
                f'<p align="center" class="cover2">民國 {year - 1911} 年 1 月 1 日 至 12 月 31 日</p>'
                f'<p>&nbsp;</p>{kpi}<p>&nbsp;</p>'
                f'<h2>目　錄</h2><table class="toc" cellspacing="0" width="70%">{toc}</table>'
                f'<p>&nbsp;</p><p class="sub" align="center">{self.unit}　｜　{self.owner}　｜　{self.made}</p>'
                '<p class="sub" align="center">本報告依帳本資料自動產生；比較數字為去年同期。</p>')

    def annual_summary(self, year: int, first: bool = False) -> str:
        k = self._kpis(year)
        p = self._kpis(year - 1) if self.db.first_year() and self.db.first_year() < year else None
        b = self.base

        def pct_(v):
            return "—" if v is None else f"{v:.1%}"
        items = [("年初淨資產（去年底）", k["opening"], None, "n"), ("年底淨資產", k["net"], p and p["net"], "n"),
                 ("淨資產增減", k["change"], p and p["change"], "n"), ("資產總計", k["assets"], p and p["assets"], "n"),
                 ("負債總計", k["liabilities"], p and p["liabilities"], "n"),
                 ("全年收入", k["income"], p and p["income"], "n"), ("全年支出", k["expense"], p and p["expense"], "n"),
                 ("本期收支結餘", k["operating"], p and p["operating"], "n"),
                 ("業外損益（投資、匯率）", k["other"], p and p["other"], "n"),
                 ("本期綜合損益", k["comprehensive"], p and p["comprehensive"], "n"),
                 ("儲蓄率", k["savings"], p and p["savings"], "p"), ("負債比率", k["debt_ratio"], p and p["debt_ratio"], "p")]
        rows = []
        for name, v, pv, kind in items:
            fmt = (lambda x: fmt_num(x, b)) if kind == "n" else pct_
            cells = [(escape(name), "b"), (fmt(v) if v is not None else "—", "r")]
            if p:
                if kind == "n" and v is not None and pv is not None:
                    d = (fmt_num(v - pv, b, signed=True), "r")
                elif kind == "p" and v is not None and pv is not None:
                    d = (f"{(v - pv) * 100:+.1f} 個百分點", "r")
                else:
                    d = ("—", "r")
                cells += [(fmt(pv) if pv is not None else "—", "r"), d]
            rows.append(self._tr(cells))
        heads = [("項目", ""), (f"{year} 年", "")] + ([(f"{year - 1} 年", ""), ("增減", "")] if p else [])
        out = [self._head(f"{year} 年度摘要", f"期間：{fmt_date(k['start'])} 至 {fmt_date(k['end'])}", first),
               self._table(heads, rows, [34, 22, 22, 22] if p else [60, 40])]
        # 支出排行
        cats = self.db.category_totals(k["start"], k["end"], "expense")
        total = sum(c["total"] for c in cats) or 1
        if cats:
            rows = [self._tr([(str(i + 1), "c"), (escape(c["name"]), ""), (fmt_num(c["total"], b), "r"),
                              (f"{c['total'] / total:.1%}", "r"), (fmt_num(c["total"] / 12, b), "r")])
                    for i, c in enumerate(cats[:10])]
            out.append("<h2>支出排行（前 10 名）</h2>")
            out.append(self._table([("名次", ""), ("分類", ""), ("全年金額", ""), ("占支出", ""), ("每月平均", "")],
                                   rows, [8, 36, 20, 16, 20]))
        budgeted = [c for c in cats if c.get("budget")]
        if budgeted:
            rows = []
            for c in budgeted:
                bud = c["budget"] * 12
                diff = bud - c["total"]
                cls = "good" if diff >= 0 else "bad"
                rows.append(self._tr([(escape(c["name"]), ""), (fmt_num(bud, b), "r"), (fmt_num(c["total"], b), "r"),
                                      (f"{c['total'] / bud:.0%}", "r"),
                                      (f'<span class="{cls}">{fmt_num(diff, b, signed=True)}</span>', "r")]))
            out.append("<h2>預算執行（全年預算＝每月預算 × 12）</h2>")
            out.append(self._table([("分類", ""), ("全年預算", ""), ("實際", ""), ("執行率", ""), ("差異", "")],
                                   rows, [32, 18, 18, 14, 18]))
        return "".join(out)

    def annual_monthly(self, year: int, first: bool = False) -> str:
        start, end = f"{year}-01-01", f"{year}-12-31"
        data = self.db.monthly_totals(start, end)
        rows, ti, te = [], 0.0, 0.0
        for m in range(1, 13):
            key = f"{year}-{m:02d}"
            d = data.get(key, {})
            inc, exp = d.get("income", 0.0), d.get("expense", 0.0)
            ti += inc
            te += exp
            rows.append(self._tr([(f"{m} 月", "c"), (_n(inc, self.base), "r"), (_n(exp, self.base), "r"),
                                  (fmt_num(inc - exp, self.base, signed=True) if inc or exp else "", "r"),
                                  (_pct((inc - exp) / inc) if inc else "", "r")]))
        rows.append(self._tr([("合計", "c"), (fmt_num(ti, self.base), "r"), (fmt_num(te, self.base), "r"),
                              (fmt_num(ti - te, self.base, signed=True), "r"), (_pct((ti - te) / ti) if ti else "", "r")],
                             "tot"))
        rows.append(self._tr([("每月平均", "c"), (fmt_num(ti / 12, self.base), "r"), (fmt_num(te / 12, self.base), "r"),
                              (fmt_num((ti - te) / 12, self.base, signed=True), "r"), ("", "")]))
        return (self._head("月度收支表", f"{year} 年 1 月至 12 月（不含業外損益）", first)
                + self._table([("月份", ""), ("收入", ""), ("支出", ""), ("結餘", ""), ("儲蓄率", "")], rows,
                              [14, 22, 22, 24, 18]))

    def annual_invest(self, year: int, first: bool = False) -> str:
        from .investments import Investments
        from .performance import portfolio_performance
        inv = Investments(self.db)
        start, end = f"{year}-01-01", f"{year}-12-31"
        as_of = min(end, dt.date.today().isoformat())
        perf = portfolio_performance(inv, as_of)
        ps = inv.period_summary(start, end)
        b = self.base
        out = [self._head("投資績效", f"截至 {fmt_date(as_of)}（自開始投資起累計；股利已扣補充保費）", first)]
        rows = []
        for r in perf["rows"]:
            cur = r["currency"]
            rows.append(self._tr([(escape(f"{r['code']} {r['name']}".strip()), ""),
                                  (fmt_shares_(r["shares"]), "r"), (fmt_num(r["invested"], cur), "r"),
                                  (fmt_num(r["value"], cur), "r"), (fmt_num(r["gain"], cur, signed=True), "r"),
                                  (_pct(r["total_return"], "—"), "r"),
                                  (_pct(r["xirr"], "未滿一年" if 0 < r["years"] < 1 else "—"), "r")]))
        t = perf["total"]
        rows.append(self._tr([("投資組合合計（本位幣）", "b"), ("", ""), (fmt_num(t["invested"], b), "r"),
                              (fmt_num(t["value"], b), "r"), (fmt_num(t["gain"], b, signed=True), "r"),
                              (_pct(t["total_return"], "—"), "r"),
                              (_pct(t["xirr"], "未滿一年" if 0 < t["years"] < 1 else "—"), "r")], "tot"))
        if not perf["rows"]:
            out.append("<p>沒有投資標的。</p>")
            return "".join(out)
        out.append(self._table([("標的", ""), ("持有股數", ""), ("投入金額", ""), ("帳面價值", ""), ("總損益", ""),
                                ("總報酬率", ""), ("年化報酬率", "")], rows, [26, 11, 14, 14, 13, 10, 12]))
        out.append(f"<h2>{year} 年度投資收益</h2>")
        rows = [self._tr([("已實現損益（處分投資損益）", ""), (fmt_num(ps["realized"], b, signed=True), "r")]),
                self._tr([("現金股利（扣補充保費前）", ""), (fmt_num(ps["dividends"], b), "r")]),
                self._tr([("二代健保補充保費", ""), (fmt_num(ps["nhi"], b), "r")]),
                self._tr([("未實現評價損益變動（市價評價）", ""),
                          (fmt_num(self.db.adjust_totals(start, end), b, signed=True), "r")])]
        out.append(self._table([("項目", ""), ("金額", "")], rows, [70, 30]))
        return "".join(out)

    def annual_tags(self, year: int, first: bool = False) -> str:
        start, end = f"{year}-01-01", f"{year}-12-31"
        data = self.db.tag_summary(start, end)
        out = [self._head("標籤／專案彙總", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", first)]
        if not data:
            out.append("<p>本年度沒有加上標籤的紀錄。</p>")
            return "".join(out)
        rows = [self._tr([(escape(r["name"]), "b"), (str(r["count"]), "r"),
                          (f"{fmt_date(r['first'])} ～ {fmt_date(r['last'])}", "c"), (_n(r["income"], self.base), "r"),
                          (_n(r["expense"], self.base), "r"), (fmt_num(r["net"], self.base, signed=True), "r")])
                for r in data]
        out.append(self._table([("標籤／專案", ""), ("筆數", ""), ("期間", ""), ("收入", ""), ("支出", ""), ("淨額", "")],
                               rows, [26, 8, 26, 13, 13, 14]))
        out.append('<p class="sub">一筆紀錄可以有多個標籤，所以各標籤合計可能大於全年收支。</p>')
        return "".join(out)

    def annual_tax(self, year: int, first: bool = False) -> str:
        from .analytics import tax_summary
        ts = tax_summary(self.db, year)
        out = [self._head("報稅參考", f"{year} 年度（民國 {year - 1911} 年）綜合所得稅參考資料", first)]
        for title, items in (("所得", ts["incomes"]), ("扣除額相關支出", ts["deductions"])):
            out.append(f"<h2>{title}</h2>")
            if not items:
                out.append("<p>（無已歸類的科目；可到「設定 → 收支分類」設定稅務歸類）</p>")
                continue
            rows = [self._tr([(escape(t["label"]), "b"), (fmt_num(t["amount"], self.base), "r"),
                              (escape("、".join(t["categories"])), ""), (escape(t["note"]), "")]) for t in items]
            out.append(self._table([("類別", ""), ("金額", ""), ("來源科目", ""), ("說明", "")], rows, [18, 14, 26, 42]))
        out.append(f'<p class="sub">處分投資損益：{fmt_num(ts["realized"], self.base, signed=True)}　'
                   f'{escape(ts["realized_note"])}</p>'
                   '<p class="sub">以上為依帳本整理的參考數字，實際申報請以財政部所得資料與最新規定為準。</p>')
        return "".join(out)

    # ------------------------------------------------------------------ 月報（一頁看完一個月）
    def monthly(self, ym: str) -> str:
        from . import reminders
        from .database import month_end, month_start
        from .investments import Investments
        db, b = self.db, self.base
        start, end = month_start(ym), month_end(ym)
        y, m = int(ym[:4]), int(ym[5:])
        prev_end = (dt.date(y, m, 1) - dt.timedelta(days=1)).isoformat()
        prev_start = prev_end[:8] + "01"
        cur, prv = db.income_expense_totals(start, end), db.income_expense_totals(prev_start, prev_end)
        bs, bs0 = db.balance_sheet(end), db.balance_sheet(prev_end)
        rate = cur["net"] / cur["income"] if cur["income"] else None

        def signed(v):
            return f'<span class="{"good" if v >= 0 else "bad"}">{fmt_num(v, b, signed=True)}</span>'
        kpi = ('<table class="kpi" cellspacing="0" width="100%">'
               '<tr><th width="25%">本月收入</th><th width="25%">本月支出</th><th width="25%">本月結餘</th><th width="25%">儲蓄率</th></tr>'
               f'<tr><td align="center"><b>{fmt_num(cur["income"], b)}</b></td><td align="center"><b>{fmt_num(cur["expense"], b)}</b></td>'
               f'<td align="center"><b>{signed(cur["net"])}</b></td><td align="center"><b>{_pct(rate, "—")}</b></td></tr>'
               '<tr><th>月底淨資產</th><th>比上月底增減</th><th>資產總計</th><th>負債總計</th></tr>'
               f'<tr><td align="center"><b>{fmt_num(bs["net"], b)}</b></td><td align="center"><b>{signed(bs["net"] - bs0["net"])}</b></td>'
               f'<td align="center">{fmt_num(bs["assets"], b)}</td><td align="center">{fmt_num(bs["liabilities"], b)}</td></tr></table>')
        out = [self._head(f"{y} 年 {m} 月 月報", f"期間：{fmt_date(start)} 至 {fmt_date(end)}", True), kpi]

        cats = db.category_totals(start, end, "expense")
        before = {c["id"]: c["total"] for c in db.category_totals(prev_start, prev_end, "expense")}
        if cats:
            rows = []
            for c in cats:
                p = before.get(c["id"], 0.0)
                bud = c.get("budget") or 0
                use = f"{c['total'] / bud:.0%}" if bud else "—"
                use = f'<span class="bad">{use}</span>' if bud and c["total"] > bud else use
                rows.append(self._tr([(escape(c["name"]), ""), (fmt_num(c["total"], b), "r"), (fmt_num(p, b) if p else "—", "r"),
                                      (fmt_num(c["total"] - p, b, signed=True), "r"), (fmt_num(bud, b) if bud else "—", "r"),
                                      (use, "r")]))
            rows.append(self._tr([("支出合計", "b"), (fmt_num(cur["expense"], b), "r"), (fmt_num(prv["expense"], b), "r"),
                                  (fmt_num(cur["expense"] - prv["expense"], b, signed=True), "r"), ("", ""), ("", "")], "tot"))
            out.append("<h2>支出分類（與上月比較、預算執行）</h2>")
            out.append(self._table([("分類", ""), ("本月", ""), ("上月", ""), ("增減", ""), ("每月預算", ""), ("執行率", "")],
                                   rows, [28, 15, 15, 15, 15, 12]))
        inc = db.category_totals(start, end, "income")
        if inc:
            rows = [self._tr([(escape(c["name"]), ""), (fmt_num(c["total"], b), "r")]) for c in inc]
            rows.append(self._tr([("收入合計", "b"), (fmt_num(cur["income"], b), "r")], "tot"))
            out.append("<h2>收入</h2>" + self._table([("分類", ""), ("金額", "")], rows, [70, 30]))
        big = sorted(db.query_transactions(start, end, ttype="expense"), key=lambda t: t.get("exp") or t["amount"],
                     reverse=True)[:5]
        if big:
            rows = [self._tr([(fmt_date(t["date"]), "c"), (escape(t["note"] or ""), ""), (escape(t["category_name"] or ""), ""),
                              (fmt_num(t.get("exp") or t["amount"], b), "r")]) for t in big]
            out.append("<h2>本月較大的支出</h2>" + self._table([("日期", ""), ("說明", ""), ("分類", ""), ("金額", "")],
                                                         rows, [16, 44, 20, 20]))
        inv = Investments(db)
        hold = [h for h in inv.holdings(end) if h["shares"] > 1e-9]
        if hold:
            ps = inv.period_summary(start, end)
            rate = {a["id"]: a["rate"] or 1 for a in db.list_accounts(include_archived=True)}
            cost = sum(h["cost"] * rate.get(h["account_id"], 1) for h in hold)
            value = sum(h["market_value"] * rate.get(h["account_id"], 1) for h in hold)
            rows = [self._tr([("持股帳面價值（成本＋評價）", ""), (fmt_num(value, b), "r")]),
                    self._tr([("持股成本", ""), (fmt_num(cost, b), "r")]),
                    self._tr([("未實現損益", ""), (signed(value - cost), "r")]),
                    self._tr([("本月現金股利", ""), (fmt_num(ps["dividends"], b), "r")]),
                    self._tr([("本月已實現損益", ""), (signed(ps["realized"]), "r")])]
            out.append(f"<h2>投資（{len(hold)} 檔持股）</h2>" + self._table([("項目", ""), ("金額", "")], rows, [70, 30]))
        base_day = max(dt.date.fromisoformat(end) + dt.timedelta(days=1), dt.date.today())
        ev = reminders.upcoming(db, 31, base_day)
        if ev:
            rows = [self._tr([(fmt_date(e["date"]), "c"), (escape(e["title"]), ""), (escape(e["sub"] or ""), ""),
                              (fmt_num(e["amount"], e["currency"]) if e.get("amount") else "", "r")]) for e in ev[:8]]
            out.append(f"<h2>接下來 31 天的提醒（自 {fmt_date(base_day.isoformat())} 起）</h2>"
                       + self._table([("日期", ""), ("事項", ""), ("說明", ""), ("金額", "")], rows, [16, 32, 36, 16]))
        out.append(f'<p class="sub">本月報依帳本資料自動產生。{self.made}</p>')
        return f"<html><head><style>{_CSS}</style></head><body>{''.join(out)}</body></html>"

    # ------------------------------------------------------------------ 健康檢查報告
    def health(self, result: dict) -> str:
        mark = {"ok": ('<span class="good">✓ 正常</span>'), "info": "提醒", "warn": '<span class="bad">建議處理</span>',
                "bad": '<span class="bad"><b>需要處理</b></span>'}
        rows = [self._tr([(escape(c["title"]), "b"), (mark[c["status"]], "c"), (escape(c["detail"]), "")])
                for c in result["checks"]]
        verdict = (f'<p class="cover2" align="center"><span class="{"good" if result["ok"] else "bad"}">'
                   f'{escape(result["summary"])}</span></p>')
        body = (self._head("帳務健康檢查報告", f"檢查時間：{result['at'].replace('-', '/')}", True) + verdict
                + self._table([("檢查項目", ""), ("結果", ""), ("說明", "")], rows, [26, 14, 60])
                + '<p class="sub">「需要處理」表示帳務或檔案可能有誤；「建議處理」不影響帳務正確，但建議找時間處理。</p>')
        return f"<html><head><style>{_CSS}</style></head><body>{body}</body></html>"

    def annual(self, year: int, sections: list[str] | None = None) -> str:
        """年度財務報告：封面＋所選章節，每章從新的一頁開始。"""
        sections = [s for s in (sections or [k for k, _, d in ANNUAL_SECTIONS if d])
                    if s in {k for k, _, _ in ANNUAL_SECTIONS}]
        start, end = f"{year}-01-01", f"{year}-12-31"
        cmp = "prior_year" if (self.db.first_year() or year) < year else "none"
        parts = [self.annual_cover(year, sections)]
        fns = {"summary": lambda: self.annual_summary(year), "bs": lambda: self.bs(start, end, False, cmp),
               "is": lambda: self.income(start, end, False, cmp), "equity": lambda: self.equity(start, end, False),
               "cashflow": lambda: self.cashflow(start, end, False),
               "ratios": lambda: self.ratios(start, end, False, cmp), "monthly": lambda: self.annual_monthly(year),
               "invest": lambda: self.annual_invest(year), "tags": lambda: self.annual_tags(year),
               "tax": lambda: self.annual_tax(year), "trial": lambda: self.trial(start, end, False),
               "journal": lambda: self.journal(start, end, False)}
        parts += [fns[s]() for s in sections]
        return f"<html><head><style>{_CSS}</style></head><body>{''.join(parts)}</body></html>"

    def build_voucher(self, txn_id: int) -> str:
        return f"<html><head><style>{_CSS}</style></head><body>{self.voucher(txn_id)}</body></html>"

    def build(self, keys: list[str], start: str, end: str, compare: str = "none") -> str:
        """compare：資產負債表、收支損益表、財務比率的比較方式（statements.COMPARE_MODES）。"""
        fns = {"vouchers": self.vouchers, "journal": self.journal, "ledger": self.ledger, "trial": self.trial,
               "bs": self.bs, "is": self.income, "equity": self.equity, "ratios": self.ratios,
               "cashflow": self.cashflow}
        body = "".join(fns[k](start, end, n == 0, compare) if k in ("bs", "is", "ratios")
                       else fns[k](start, end, n == 0) for n, k in enumerate(keys))
        return f"<html><head><style>{_CSS}</style></head><body>{body}</body></html>"
