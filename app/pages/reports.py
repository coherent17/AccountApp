from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..charts import BarChart, DonutChart
from ..database import ADJUST_ACCOUNT, FX_ACCOUNT, REALIZED_ACCOUNT, month_keys
from ..dialogs import ExportDialog
from ..theme import C, fmt_date, fmt_money, fmt_month, fmt_month_short, fmt_num, icon
from ..widgets import (PERIOD_PRESETS, Card, Column, DataTable, button, iso, make_date_edit,
                       page_header, preset_range, qdate, section_title)
from .base import Page


class StatementTree(QTreeWidget):
    """財務報表樣式的樹狀表格。"""

    def __init__(self, headers: list[str], parent=None):
        super().__init__(parent)
        self.setHeaderLabels(headers)
        self.setRootIsDecorated(False)
        self.setIndentation(18)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        h = self.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(headers)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(i, 170)
            self.headerItem().setTextAlignment(i, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._bold = QFont()
        self._bold.setBold(True)

    def row(self, values: list[str], level: int = 1, style: str = "", color: str | None = None):
        item = QTreeWidgetItem(["　" * level + values[0]] + values[1:])
        for i in range(1, len(values)):
            item.setTextAlignment(i, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if style in ("section", "subtotal", "total", "grand"):
            for i in range(len(values)):
                item.setFont(i, self._bold)
        bg = {"section": C.surface_alt, "subtotal": "#F1F5FB", "total": "#E4ECF9",
              "grand": "#DCE6F7"}.get(style)
        if bg:
            for i in range(len(values)):
                item.setBackground(i, QBrush(QColor(bg)))
        if style == "section":
            item.setForeground(0, QBrush(QColor(C.primary)))
        if color:
            for i in range(1, len(values)):
                item.setForeground(i, QBrush(QColor(color)))
        self.addTopLevelItem(item)
        return item


def pct(v: float | None) -> str:
    return "" if v is None else f"{v:.1%}"


class ReportsPage(Page):
    title = "財務報表"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, scroll=False, parent=parent)
        b = self.body
        head, hl = page_header("財務報表", "資產負債表、收支損益表、分類帳與試算表")
        exp = button("匯出 Excel 報表", "Income", icon("download", "#FFFFFF"))
        exp.setMinimumHeight(44)
        exp.clicked.connect(self.export)
        hl.addWidget(exp)
        b.addWidget(head)

        fc = Card(padding=14)
        fl = QHBoxLayout()
        lbl = QLabel("報表期間")
        lbl.setObjectName("Muted")
        self.period = QComboBox()
        self.period.addItems(PERIOD_PRESETS)
        self.d1 = make_date_edit()
        self.d2 = make_date_edit()
        self.period_note = QLabel()
        self.period_note.setObjectName("Hint")
        fl.addWidget(lbl)
        fl.addWidget(self.period)
        fl.addWidget(self.d1)
        fl.addWidget(QLabel("～"))
        fl.addWidget(self.d2)
        fl.addSpacing(10)
        fl.addWidget(self.period_note, 1)
        fc.lay.addLayout(fl)
        b.addWidget(fc)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        b.addWidget(self.tabs, 1)

        # 資產負債表
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        self.bs_title = QLabel()
        self.bs_title.setObjectName("Hint")
        lay.addWidget(self.bs_title)
        self.bs = StatementTree(["會計科目", "原幣金額", f"金額（{ctx.base}）", "占總資產"])
        lay.addWidget(self.bs, 1)
        self.tabs.addTab(w, "資產負債表")

        # 收支損益表
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        ir = QHBoxLayout()
        self.compare = QCheckBox("與去年同期比較")
        self.compare.toggled.connect(self.refresh)
        ir.addWidget(self.compare)
        ir.addStretch()
        lay.addLayout(ir)
        self.is_ = StatementTree(["會計科目", "筆數", f"本期金額（{ctx.base}）", "占收入比",
                                  "去年同期", "增減金額", "增減 %"])
        lay.addWidget(self.is_, 1)
        self.tabs.addTab(w, "收支損益表")

        # 現金流量表
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        self.cf = StatementTree(["項目", "", f"金額（{ctx.base}）", ""])
        lay.addWidget(self.cf, 1)
        cfh = QLabel("現金及約當現金包含：現金、銀行存款、定期存款、外幣存款。生活（營業）活動為日常收支與信用卡；"
                     "投資活動為股票、基金、保單等買賣；籌資活動為貸款借還。")
        cfh.setObjectName("Hint")
        cfh.setWordWrap(True)
        lay.addWidget(cfh)
        self.tabs.addTab(w, "現金流量表")

        # 月度收支
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(16)
        self.mon_table = DataTable([
            Column("月份", lambda r: r["label"], bold=True, width=120,
                   sort=lambda r: r.get("ym", "9999")),
            Column("收入", lambda r: fmt_num(r["income"], ctx.base), align="right",
                   color=lambda r: C.income, sort=lambda r: r["income"], width=130),
            Column("支出", lambda r: fmt_num(r["expense"], ctx.base), align="right",
                   color=lambda r: C.expense, sort=lambda r: r["expense"], width=130),
            Column("結餘", lambda r: fmt_num(r["income"] - r["expense"], ctx.base), align="right",
                   bold=True, sort=lambda r: r["income"] - r["expense"], width=130,
                   color=lambda r: C.expense if r["income"] < r["expense"] else None),
            Column("儲蓄率", lambda r: pct((r["income"] - r["expense"]) / r["income"])
                   if r["income"] else "—", align="right", width=90),
        ], sortable=False)
        mc = Card()
        mc.lay.addWidget(section_title("每月收支"))
        self.mon_chart = BarChart(height=360)
        mc.lay.addWidget(self.mon_chart)
        lay.addWidget(self.mon_table, 5)
        lay.addWidget(mc, 6)
        self.tabs.addTab(w, "月度收支")

        # 分類分析
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(16)
        left = QVBoxLayout()
        self.cat_kind = QComboBox()
        self.cat_kind.addItem("支出分類", "expense")
        self.cat_kind.addItem("收入分類", "income")
        self.cat_kind.currentIndexChanged.connect(self.refresh)
        left.addWidget(self.cat_kind)
        self.cat_table = DataTable([
            Column("分類", lambda r: r["name"], bold=True, stretch=True),
            Column("筆數", lambda r: r["count"], align="right", width=70),
            Column("金額", lambda r: fmt_num(r["total"], ctx.base), align="right",
                   sort=lambda r: r["total"], width=130),
            Column("占比", lambda r: pct(r["_pct"]), align="right", sort=lambda r: r["_pct"], width=80),
            Column("期間預算", lambda r: fmt_num(r["_budget"], ctx.base) if r["_budget"] else "—",
                   align="right", sort=lambda r: r["_budget"], width=115),
            Column("執行率", lambda r: pct(r["total"] / r["_budget"]) if r["_budget"] else "—",
                   align="right", width=90,
                   color=lambda r: C.expense if r["_budget"] and r["total"] > r["_budget"] else None),
            Column("預算差異", lambda r: fmt_num(r["_budget"] - r["total"], ctx.base) if r["_budget"] else "—",
                   align="right", width=110,
                   color=lambda r: (C.expense if r["total"] > r["_budget"] else C.income) if r["_budget"] else None),
        ])
        left.addWidget(self.cat_table, 1)
        cc = Card()
        cc.lay.addWidget(section_title("分類占比"))
        self.cat_chart = DonutChart(height=360)
        cc.lay.addWidget(self.cat_chart)
        lay.addLayout(left, 6)
        lay.addWidget(cc, 5)
        self.tabs.addTab(w, "分類與預算")

        # 日記帳
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        top = QHBoxLayout()
        self.jnl_kw = QLineEdit()
        self.jnl_kw.setPlaceholderText("搜尋摘要或會計科目…")
        self.jnl_kw.setClearButtonEnabled(True)
        self.jnl_kw.setFixedWidth(300)
        self.jnl_kw.textChanged.connect(lambda _: self.refresh_journal(*self.range()))
        top.addWidget(self.jnl_kw)
        add_j = button("新增分錄", "Primary", icon("plus", "#FFFFFF"))
        add_j.clicked.connect(self.new_journal)
        top.addWidget(add_j)
        top.addStretch()
        self.jnl_sum = QLabel()
        self.jnl_sum.setStyleSheet("font-weight:700;")
        top.addWidget(self.jnl_sum)
        lay.addLayout(top)
        self.jnl = DataTable([
            Column("日期", lambda r: fmt_date(r["date"]) if r.get("first") else "", width=118),
            Column("傳票號碼", lambda r: r["voucher"] if r.get("first") else "", align="center",
                   width=110, color=lambda r: C.faint),
            Column("摘要", lambda r: r["summary"] if r.get("first") else "", stretch=True),
            Column("科目代號", lambda r: r["code"], align="center", width=84, color=lambda r: C.muted),
            Column("會計科目", lambda r: ("　　" if r["credit"] and not r["debit"] else "") + r["name"],
                   stretch=True),
            Column("借方金額", lambda r: fmt_num(r["debit"], ctx.base) if r["debit"] else "",
                   align="right", width=140, color=lambda r: C.income),
            Column("貸方金額", lambda r: fmt_num(r["credit"], ctx.base) if r["credit"] else "",
                   align="right", width=140, color=lambda r: C.expense),
        ], sortable=False)
        self.jnl.setAlternatingRowColors(False)
        self.jnl.rowActivated.connect(self._ledger_open)
        lay.addWidget(self.jnl, 1)
        hint = QLabel("依日期列出每張傳票的借貸分錄（以本位幣表示，貸方科目內縮）。"
                      "按兩下可開啟傳票；系統自動產生的投資評價分錄也會列在這裡。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tabs.addTab(w, "日記帳")

        # 分類帳
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("帳戶（科目）"))
        self.ledger_acc = QComboBox()
        self.ledger_acc.setMinimumWidth(260)
        self.ledger_acc.currentIndexChanged.connect(self.refresh_ledger)
        top.addWidget(self.ledger_acc)
        top.addStretch()
        self.ledger_sum = QLabel()
        self.ledger_sum.setStyleSheet("font-weight:700;")
        top.addWidget(self.ledger_sum)
        lay.addLayout(top)
        self.ledger = DataTable([
            Column("日期", lambda r: fmt_date(r["date"]), width=118),
            Column("傳票號碼", lambda r: r["voucher"], align="center", width=110,
                   color=lambda r: C.faint),
            Column("摘要", lambda r: r["summary"], stretch=True),
            Column("對方科目", lambda r: r["counter"], width=170),
            Column("借方", lambda r: fmt_num(r["debit"], r.get("_cur", "TWD")) if r["debit"] else "",
                   align="right", width=140, color=lambda r: C.income),
            Column("貸方", lambda r: fmt_num(r["credit"], r.get("_cur", "TWD")) if r["credit"] else "",
                   align="right", width=140, color=lambda r: C.expense),
            Column("餘額", lambda r: fmt_num(r["balance"], r.get("_cur", "TWD")), align="right",
                   bold=True, width=150),
        ], sortable=False)
        self.ledger.rowActivated.connect(self._ledger_open)
        lay.addWidget(self.ledger, 1)
        hint = QLabel("借方：資產增加／負債減少；貸方：資產減少／負債增加。資產帳戶餘額在借方，負債帳戶餘額在貸方。")
        hint.setObjectName("Hint")
        lay.addWidget(hint)
        self.tabs.addTab(w, "分類帳")

        # 試算表
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        self.tb = DataTable([
            Column("科目代號", lambda r: r["code"], align="center", width=110),
            Column("會計科目", lambda r: r["name"], stretch=True, bold=True),
            Column("科目類別", lambda r: r["group"], align="center", width=120,
                   color=lambda r: C.muted),
            Column("借方餘額", lambda r: fmt_num(r["debit"], ctx.base) if r["debit"] else "",
                   align="right", width=170, sort=lambda r: r["debit"]),
            Column("貸方餘額", lambda r: fmt_num(r["credit"], ctx.base) if r["credit"] else "",
                   align="right", width=170, sort=lambda r: r["credit"]),
        ])
        lay.addWidget(self.tb, 1)
        self.tb_sum = QLabel()
        self.tb_sum.setStyleSheet("font-weight:700; padding:8px 4px;")
        lay.addWidget(self.tb_sum)
        hint = QLabel("資產、負債科目為期末餘額；收入、支出等損益科目為本期發生額；"
                      "期初淨值 = 期初前一日淨資產 + 期間內新開帳戶之期初金額。借貸合計相等即表示帳務平衡。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tabs.addTab(w, "試算表")

        # 報稅彙總
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        tr = QHBoxLayout()
        tr.addWidget(QLabel("所得年度"))
        self.tax_year = QComboBox()
        self.tax_year.currentIndexChanged.connect(self.refresh)
        tr.addWidget(self.tax_year)
        tr.addStretch()
        lay.addLayout(tr)
        self.tax = StatementTree(["項目", "", f"金額（{ctx.base}）", ""])
        self.tax.setWordWrap(True)
        self.tax.setUniformRowHeights(False)
        lay.addWidget(self.tax, 1)
        th = QLabel("依「設定 → 收支分類」中的「稅務歸類」彙總，方便每年五月申報綜合所得稅時參考。"
                    "稅法規定時有修訂，實際申報請以財政部最新規定與國稅局資料為準。")
        th.setObjectName("Hint")
        th.setWordWrap(True)
        lay.addWidget(th)
        self.tabs.addTab(w, "報稅彙總")

        self._loading = False
        self.period.setCurrentText("今年")
        self.period.currentTextChanged.connect(self._period_changed)
        self.d1.dateChanged.connect(self._custom)
        self.d2.dateChanged.connect(self._custom)
        self.tabs.currentChanged.connect(lambda _: self.refresh())

    # ------------------------------------------------------------------
    def _period_changed(self, name: str) -> None:
        if name == "自訂期間":
            return
        a, b = preset_range(name, self.db.date_range())
        self._loading = True
        self.d1.setDate(qdate(a))
        self.d2.setDate(qdate(b))
        self._loading = False
        self.refresh()

    def _custom(self) -> None:
        if self._loading:
            return
        if self.period.currentText() != "自訂期間":
            self.period.blockSignals(True)
            self.period.setCurrentText("自訂期間")
            self.period.blockSignals(False)
        self.refresh()

    def range(self) -> tuple[str, str]:
        a, b = iso(self.d1.date()), iso(self.d2.date())
        return (a, b) if a <= b else (b, a)

    def refresh(self) -> None:
        if self.period.currentText() != "自訂期間" and not self._loading:
            a, b = preset_range(self.period.currentText(), self.db.date_range())
            self._loading = True
            self.d1.setDate(qdate(a))
            self.d2.setDate(qdate(b))
            self._loading = False
        start, end = self.range()
        closed = self.db.closed_until
        self.period_note.setText(f"已結帳至 {fmt_date(closed)}" if closed else "")
        name = self.tabs.tabText(self.tabs.currentIndex())
        if name == "分類帳":
            self.refresh_ledger_accounts()
            return
        handlers = {"資產負債表": self.refresh_bs, "收支損益表": self.refresh_is,
                    "現金流量表": self.refresh_cf, "月度收支": self.refresh_monthly,
                    "分類與預算": self.refresh_categories, "試算表": self.refresh_tb,
                    "日記帳": self.refresh_journal,
                    "報稅彙總": self.refresh_tax}
        handlers[name](start, end)

    def apply_filter(self, tab=None, account_id=None, **_):
        if tab == "ledger":
            self.tabs.setCurrentIndex(self._tab_index("分類帳"))
            self.refresh_ledger_accounts(select=account_id)
        elif tab == "journal":
            self.tabs.setCurrentIndex(self._tab_index("日記帳"))

    def _tab_index(self, name: str) -> int:
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == name:
                return i
        return 0

    # ------------------------------------------------------------------ 資產負債表
    def refresh_bs(self, start: str, end: str) -> None:
        base = self.ctx.base
        bs = self.db.balance_sheet(end)
        t = self.bs
        t.clear()
        self.bs_title.setText(f"基準日：{fmt_date(end)}（報表期間的最後一天）")
        total = bs["assets"] or 1

        def group(name: str, sign: int):
            accs = bs["groups"][name]
            t.row([name, "", "", ""], 1, "subtotal")
            for a in sorted(accs, key=lambda a: -abs(a["base_value"])):
                v = a["base_value"] * sign
                orig = fmt_money(a["balance"], a["currency"]) if a["currency"] != base else ""
                t.row([f"{a['name']}（{a['category']}）", orig, fmt_num(v, base),
                       pct(v / total)], 2)
            v = bs["totals"][name]
            t.row([f"{name}合計", "", fmt_num(v, base), pct(v / total)], 1, "subtotal")

        t.row(["資產", "", "", ""], 0, "section")
        group("流動資產", 1)
        group("非流動資產", 1)
        t.row(["資產總計", "", fmt_num(bs["assets"], base), "100.0%"], 0, "total")
        t.row(["", "", "", ""], 0)
        t.row(["負債及淨值", "", "", ""], 0, "section")
        group("流動負債", -1)
        group("非流動負債", -1)
        t.row(["負債總計", "", fmt_num(bs["liabilities"], base), pct(bs["liabilities"] / total)], 0,
              "total")
        t.row(["淨資產（業主權益）", "", fmt_num(bs["net"], base), pct(bs["net"] / total)], 0, "total",
              C.primary)
        t.row(["負債及淨值總計", "", fmt_num(bs["liabilities"] + bs["net"], base), ""], 0, "grand")
        t.row(["", "", "", ""], 0)
        r = self.db.ratios(end)
        t.row(["財務比率分析", "", "", ""], 0, "section")
        t.row(["負債比率（負債 ÷ 資產）", "", pct(r["debt_ratio"]) or "—", ""], 1)
        t.row(["流動比率（流動資產 ÷ 流動負債）", "",
               "無流動負債" if r["current_ratio"] is None else f"{r['current_ratio']:.2f} 倍", ""], 1)
        t.row(["流動資產占比", "", pct(r["liquid_ratio"]) or "—", ""], 1)
        t.row(["緊急預備金（現金及約當現金 ÷ 平均月支出）", "",
               "—" if r["emergency_months"] is None else f"{r['emergency_months']:.1f} 個月", ""], 1)
        t.row(["近 12 個月儲蓄率", "", pct(r["savings_rate"]) or "—", ""], 1)

    # ------------------------------------------------------------------ 損益表
    def refresh_is(self, start: str, end: str) -> None:
        base = self.ctx.base
        s = self.db.income_statement(start, end)
        cmp = self.compare.isChecked()
        for col in (4, 5, 6):
            self.is_.setColumnHidden(col, not cmp)
        p = None
        if cmp:
            p = self.db.income_statement(_shift_year(start), _shift_year(end))
            self.is_.headerItem().setText(4, f"去年同期（{_shift_year(start)[:4]}）")
        prev_inc = {c["id"]: c["total"] for c in p["income"]} if p else {}
        prev_exp = {c["id"]: c["total"] for c in p["expense"]} if p else {}
        t = self.is_
        t.clear()
        ti = s["total_income"] or None

        def cols(cur, prev):
            if not cmp:
                return ["", "", ""]
            d = cur - prev
            return [fmt_num(prev, base), fmt_num(d, base, signed=True),
                    pct(d / prev) if prev else "—"]

        def line(name, count, cur, prev, level=2, style="", color=None):
            t.row([name, count, fmt_num(cur, base), pct(cur / ti) if ti else ""] + cols(cur, prev),
                  level, style, color)

        t.row(["收入", "", "", "", "", "", ""], 0, "section")
        seen = set()
        for c in s["income"]:
            seen.add(c["id"])
            line(c["name"], str(c["count"]), c["total"], prev_inc.get(c["id"], 0))
        for c in (p["income"] if p else []):
            if c["id"] not in seen:
                line(c["name"], "0", 0, c["total"])
        line("收入合計", "", s["total_income"], p["total_income"] if p else 0, 1, "subtotal", C.income)
        t.row(["支出（費用）", "", "", "", "", "", ""], 0, "section")
        seen = set()
        for c in s["expense"]:
            seen.add(c["id"])
            line(c["name"], str(c["count"]), c["total"], prev_exp.get(c["id"], 0))
        for c in (p["expense"] if p else []):
            if c["id"] not in seen:
                line(c["name"], "0", 0, c["total"])
        line("支出合計", "", s["total_expense"], p["total_expense"] if p else 0, 1, "subtotal", C.expense)
        line("本期收支結餘", "", s["operating"], p["operating"] if p else 0, 0, "total")
        t.row(["業外損益", "", "", "", "", "", ""], 0, "section")
        line(f"{REALIZED_ACCOUNT}（證券買賣）", "", s["realized"], p["realized"] if p else 0)
        line(f"{ADJUST_ACCOUNT}（市值變動）", "", s["adjust"], p["adjust"] if p else 0)
        line(f"{FX_ACCOUNT}（匯率變動）", "", s["fx"], p["fx"] if p else 0)
        line("本期綜合損益（淨資產增減）", "", s["comprehensive"], p["comprehensive"] if p else 0, 0,
             "grand", C.primary if s["comprehensive"] >= 0 else C.expense)

    # ------------------------------------------------------------------ 現金流量表
    def refresh_cf(self, start: str, end: str) -> None:
        from ..analytics import cash_flow
        base = self.ctx.base
        cf = cash_flow(self.db, start, end)
        t = self.cf
        t.clear()
        t.row(["期初現金及約當現金", "", fmt_num(cf["opening"], base), ""], 0, "total")
        for title, key, total_key in (("一、生活（營業）活動之現金流量", "operating", "op_total"),
                                      ("二、投資活動之現金流量", "investing", "inv_total"),
                                      ("三、籌資活動之現金流量", "financing", "fin_total"),
                                      ("四、其他", "other", "other_total")):
            if key == "other" and not cf["other"]:
                continue
            t.row([title, "", "", ""], 0, "section")
            for r in cf[key]:
                t.row([r["name"], "", fmt_num(r["amount"], base), ""], 2,
                      color=C.income if r["amount"] > 0 else C.expense)
            if not cf[key]:
                t.row(["（本期無）", "", "", ""], 2)
            t.row(["淨現金流入（流出）", "", fmt_num(cf[total_key], base), ""], 1, "subtotal")
        t.row(["本期現金及約當現金淨增減", "", fmt_num(cf["net"], base, signed=True), ""], 0, "total",
              C.income if cf["net"] >= 0 else C.expense)
        t.row(["期末現金及約當現金", "", fmt_num(cf["closing"], base), ""], 0, "grand", C.primary)
        ok = abs(cf["check"]) < 0.05
        t.row(["勾稽：期初 ＋ 淨增減 ＝ 期末", "", "✓ 相符" if ok else f"差額 {fmt_num(cf['check'], base)}", ""],
              1, color=C.income if ok else C.expense)

    # ------------------------------------------------------------------ 報稅
    def refresh_tax(self, start: str, end: str) -> None:
        from ..analytics import tax_summary
        base = self.ctx.base
        lo, hi = self.db.date_range()
        years = [str(y) for y in range(int(hi[:4]), int(lo[:4]) - 1, -1)]
        cur = self.tax_year.currentText() or end[:4]
        self.tax_year.blockSignals(True)
        self.tax_year.clear()
        self.tax_year.addItems(years)
        self.tax_year.setCurrentText(cur if cur in years else years[0])
        self.tax_year.blockSignals(False)
        y = int(self.tax_year.currentText())
        ts = tax_summary(self.db, y)
        t = self.tax
        t.clear()
        t.row([f"{y} 年度所得（民國 {y - 1911} 年）", "", "", ""], 0, "section")
        for it in ts["incomes"]:
            t.row([it["label"], "", fmt_num(it["amount"], base), ""], 1, "subtotal")
            t.row(["來源：" + "、".join(it["categories"]), "", "", ""], 2).setFirstColumnSpanned(True)
            if it["note"]:
                n = t.row(["說明：" + it["note"], "", "", ""], 2, color=C.muted)
                n.setFirstColumnSpanned(True)
                n.setForeground(0, QBrush(QColor(C.muted)))
        if not ts["incomes"]:
            t.row(["（無已歸類的所得）", "", "", ""], 1)
        t.row(["可列舉扣除與相關支出", "", "", ""], 0, "section")
        for it in ts["deductions"]:
            t.row([it["label"], "", fmt_num(it["amount"], base), ""], 1, "subtotal")
            t.row(["來源：" + "、".join(it["categories"]), "", "", ""], 2).setFirstColumnSpanned(True)
            if it["note"]:
                n = t.row(["說明：" + it["note"], "", "", ""], 2, color=C.muted)
                n.setFirstColumnSpanned(True)
                n.setForeground(0, QBrush(QColor(C.muted)))
        if not ts["deductions"]:
            t.row(["（無已歸類的扣除項目）", "", "", ""], 1)
        t.row(["證券交易", "", "", ""], 0, "section")
        t.row(["處分投資損益（參考）", "", fmt_num(ts["realized"], base), ""], 1)
        n = t.row(["說明：" + ts["realized_note"], "", "", ""], 2, color=C.muted)
        n.setFirstColumnSpanned(True)
        n.setForeground(0, QBrush(QColor(C.muted)))

    # ------------------------------------------------------------------ 月度
    def refresh_monthly(self, start: str, end: str) -> None:
        mt = self.db.monthly_totals(start, end)
        keys = month_keys(start, end)
        rows = [{"ym": k, "label": fmt_month(k), **mt[k]} for k in keys]
        ti = sum(r["income"] for r in rows)
        te = sum(r["expense"] for r in rows)
        n = max(1, len(rows))
        rows.append({"label": "合計", "income": ti, "expense": te, "_bold": True})
        rows.append({"label": "月平均", "income": ti / n, "expense": te / n, "_bold": True})
        self.mon_table.set_rows(rows)
        many_years = len({k[:4] for k in keys}) > 1
        labels = [(k[2:4] + "/" + k[5:]) if many_years else fmt_month_short(k) for k in keys]
        self.mon_chart.set_data(labels, [("收入", [mt[k]["income"] for k in keys], C.income),
                                         ("支出", [mt[k]["expense"] for k in keys], C.expense)])

    # ------------------------------------------------------------------ 分類
    def refresh_categories(self, start: str, end: str) -> None:
        kind = self.cat_kind.currentData()
        rows = self.db.category_totals(start, end, kind)
        months = len(month_keys(start, end))
        total = sum(r["total"] for r in rows) or 1
        for r in rows:
            r["_pct"] = r["total"] / total
            r["_budget"] = (r["budget"] or 0) * months if kind == "expense" else 0
        self.cat_table.set_rows(rows)
        top = rows[:8]
        rest = sum(r["total"] for r in rows[8:])
        items = [(r["name"], r["total"]) for r in top]
        if rest:
            items.append(("其他", rest))
        self.cat_chart.set_data(items)

    # ------------------------------------------------------------------ 分類帳
    def refresh_ledger_accounts(self, start=None, end=None, select=None) -> None:
        cur = select if select is not None else self.ledger_acc.currentData()
        self.ledger_acc.blockSignals(True)
        self.ledger_acc.clear()
        codes = self.db.account_codes()
        for a in sorted(self.db.list_accounts(include_archived=True), key=lambda a: codes[a["id"]]):
            self.ledger_acc.addItem(f"{codes[a['id']]}　{a['name']}", a["id"])
        i = self.ledger_acc.findData(cur)
        self.ledger_acc.setCurrentIndex(i if i >= 0 else 0)
        self.ledger_acc.blockSignals(False)
        self.refresh_ledger()

    def refresh_ledger(self) -> None:
        aid = self.ledger_acc.currentData()
        if aid is None:
            self.ledger.set_rows([])
            self.ledger_sum.setText("")
            return
        start, end = self.range()
        lg = self.db.ledger(aid, start, end)
        cur = lg["account"]["currency"]
        rows = [{"date": start, "voucher": "", "summary": "期初餘額（上期結轉）", "counter": "",
                 "debit": 0, "credit": 0, "balance": lg["opening"], "_bold": True, "_cur": cur}]
        for r in lg["rows"]:
            r["_cur"] = cur
            rows.append(r)
        rows.append({"date": end, "voucher": "", "summary": "本期合計", "counter": "",
                     "debit": lg["debit_total"], "credit": lg["credit_total"], "balance": lg["closing"],
                     "_bold": True, "_cur": cur})
        self.ledger.set_rows(rows)
        side = lg["normal_side"]
        self.ledger_sum.setText(f"期初 {fmt_money(lg['opening'], cur)}　→　期末 {fmt_money(lg['closing'], cur)}"
                                f"（{side}餘）")

    def _ledger_open(self, row: dict) -> None:
        if row.get("id"):
            from ..dialogs import open_voucher
            open_voucher(self.ctx, row["id"], self.window())

    # ------------------------------------------------------------------ 日記帳
    def refresh_journal(self, start: str, end: str) -> None:
        base = self.ctx.base
        kw = self.jnl_kw.text().strip()
        entries = self.db.journal(start, end)
        if kw:
            entries = [e for e in entries if kw in e["summary"] or kw in e["voucher"]
                       or any(kw in ln["name"] or kw in ln["code"] for ln in e["lines"])]
        rows = []
        d = c = 0.0
        for n, e in enumerate(entries):
            bg = C.surface if n % 2 == 0 else "#F2F6FC"
            for i, ln in enumerate(e["lines"]):
                rows.append({"id": e["id"], "date": e["date"], "voucher": e["voucher"],
                             "summary": e["summary"], "code": ln["code"], "name": ln["name"],
                             "debit": ln["debit"], "credit": ln["credit"], "first": i == 0, "_bg": bg})
                d += ln["debit"]
                c += ln["credit"]
        self.jnl.set_rows(rows)
        ok = abs(d - c) < 1
        self.jnl_sum.setText(f"傳票 {len(entries)} 張　｜　借方合計 {fmt_money(d, base)}　｜　"
                             f"貸方合計 {fmt_money(c, base)}　"
                             + ("✓ 借貸平衡" if ok else f"✗ 差額 {fmt_money(d - c, base)}"))
        self.jnl_sum.setStyleSheet(f"font-weight:700; color:{C.income if ok else C.expense};")

    def new_journal(self) -> None:
        from ..dialogs_more import JournalDialog
        JournalDialog(self.ctx, parent=self.window()).exec()

    # ------------------------------------------------------------------ 試算表
    def refresh_tb(self, start: str, end: str) -> None:
        base = self.ctx.base
        rows = self.db.trial_balance(start, end)
        d = round(sum(r["debit"] for r in rows), 2)
        c = round(sum(r["credit"] for r in rows), 2)
        self.tb.set_rows(rows)
        ok = abs(d - c) < 1
        self.tb_sum.setText(f"借方合計 {fmt_money(d, base)}　｜　貸方合計 {fmt_money(c, base)}　｜　"
                            + ("✓ 借貸平衡" if ok else f"✗ 差額 {fmt_money(d - c, base)}"))
        self.tb_sum.setStyleSheet(f"font-weight:700; padding:8px 4px; color:{C.income if ok else C.expense};")

    def export(self) -> None:
        a, b = self.range()
        ExportDialog(self.ctx, self.window(), a, b).exec()


def _shift_year(iso_date: str) -> str:
    y, m, d = int(iso_date[:4]), int(iso_date[5:7]), int(iso_date[8:10])
    if m == 2 and d == 29:
        d = 28
    return f"{y - 1:04d}-{m:02d}-{d:02d}"
