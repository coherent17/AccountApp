from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMenu, QTabWidget, QVBoxLayout, QWidget

from ..charts import DonutChart
from ..database import INVESTMENT_CATEGORIES, fmt_shares
from ..dialogs_invest import PriceDialog, SecurityDialog, TradeDialog
from ..investments import KIND_LABELS, Investments
from ..theme import C, fmt_date, fmt_money, fmt_num, icon
from ..widgets import (Card, Column, DataTable, StatCard, ask, button, error, info, page_header,
                       section_title)
from .base import Page


def _pct(v):
    return "—" if v is None else f"{v:+.2%}"


class InvestmentsPage(Page):
    title = "投資管理"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, scroll=False, parent=parent)
        self.inv = Investments(ctx.db)
        b = self.body
        head, hl = page_header("投資管理", "投資明細帳：持股、平均成本、已實現與未實現損益、股利")
        for text, kind, key, ic in (("買進", "Expense", "buy", "plus"), ("賣出", "Income", "sell", "minus"),
                                     ("股利", "Adjust", "div", "download")):
            btn = button(text, kind, icon(ic, "#FFFFFF"))
            btn.setMinimumHeight(44)
            if key == "div":
                menu = QMenu(btn)
                for k in ("cash_div", "stock_div"):
                    a = QAction(KIND_LABELS[k], menu)
                    a.triggered.connect(lambda _=False, kk=k: self.trade(kk))
                    menu.addAction(a)
                btn.setMenu(menu)
            else:
                btn.clicked.connect(lambda _=False, k=key: self.trade(k))
            hl.addWidget(btn)
        price = button("市價評價", "Primary", icon("refresh", "#FFFFFF"))
        price.setMinimumHeight(44)
        price.clicked.connect(self.prices)
        add = button("新增標的", icon=icon("plus"))
        add.setMinimumHeight(44)
        add.clicked.connect(self.add_security)
        hl.addWidget(price)
        hl.addWidget(add)
        b.addWidget(head)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        self.c_mv = StatCard("投資帳面價值", C.primary)
        self.c_cost = StatCard("投資成本", C.muted)
        self.c_unr = StatCard("未實現損益", C.adjust)
        self.c_real = StatCard("今年已實現損益", C.income)
        self.c_div = StatCard("今年股利收入", C.gold)
        for c in (self.c_mv, self.c_cost, self.c_unr, self.c_real, self.c_div):
            cards.addWidget(c)
        b.addLayout(cards)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        b.addWidget(self.tabs, 1)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(16)
        base = ctx.base
        self.hold = DataTable([
            Column("代號", lambda r: r["code"], align="center", width=80, bold=True),
            Column("名稱", lambda r: r["name"], width=170, bold=True),
            Column("持股", lambda r: f"{r['shares']:,.0f}", align="right", sort=lambda r: r["shares"], width=80),
            Column("平均成本", lambda r: f"{r['avg_cost']:,.2f}", align="right", width=95),
            Column("最近評價市價", lambda r: f"{r['price']:,.2f}" if r["price"] else "尚未評價", align="right",
                   width=135),
            Column("成本", lambda r: fmt_num(r["cost"], r["currency"]), align="right",
                   sort=lambda r: r["cost"], width=105),
            Column("帳面價值", lambda r: fmt_num(r["market_value"], r["currency"]), align="right",
                   sort=lambda r: r["market_value"], width=105, bold=True),
            Column("未實現損益", lambda r: fmt_num(r["unrealized"], r["currency"]), align="right",
                   sort=lambda r: r["unrealized"], width=105,
                   color=lambda r: C.income if r["unrealized"] >= 0 else C.expense),
            Column("報酬率", lambda r: _pct(r["return_pct"]), align="right",
                   sort=lambda r: r["return_pct"] or 0, stretch=True,
                   color=lambda r: C.income if (r["return_pct"] or 0) >= 0 else C.expense),
        ])
        self.hold.rowActivated.connect(lambda r: self.show_events(r["id"]))
        self.hold.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hold.customContextMenuRequested.connect(self.hold_menu)
        self.hold.setMinimumHeight(5 * 44 + 50)   # 至少顯示 5 檔持股
        lay.addWidget(self.hold, 3)
        hh = QLabel("帳面價值＝成本＋已認列的評價。評價以預估淨售價計算（市價×股數，扣除預估賣出手續費與證交稅），"
                    "成本已含買進手續費，因此未實現損益已包含買賣的手續費與稅。費率可在「編輯標的」設定。")
        hh.setObjectName("Hint")
        hh.setWordWrap(True)
        lay.addWidget(hh)
        cc = Card()
        cc.lay.addWidget(section_title("持股比重（依帳面價值）"))
        self.donut = DonutChart(height=240)
        cc.lay.addWidget(self.donut)
        lay.addWidget(cc, 2)
        self.tabs.addTab(w, "持股明細")

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("標的"))
        self.ev_filter = QComboBox()
        self.ev_filter.setMinimumWidth(240)
        self.ev_filter.currentIndexChanged.connect(self.load_events)
        top.addWidget(self.ev_filter)
        top.addStretch()
        delete = button("刪除選取交易", "Danger", icon("trash", C.expense))
        delete.clicked.connect(self.delete_event)
        top.addWidget(delete)
        lay.addLayout(top)
        self.ev = DataTable([
            Column("日期", lambda r: fmt_date(r["date"]), width=118),
            Column("標的", lambda r: f"{r['code']} {r['sec_name']}".strip(), width=170),
            Column("類別", lambda r: KIND_LABELS[r["kind"]], align="center", width=132,
                   color=lambda r: {"buy": C.expense, "sell": C.income, "cash_div": C.gold,
                                    "stock_div": C.adjust, "jbuy": C.expense,
                                    "jsell": C.income}.get(r["kind"], C.muted)),
            Column("股數", lambda r: fmt_shares(r["shares"]) if r["shares"] else "", align="right", width=90),
            Column("價格", lambda r: f"{r['price']:,.2f}" if r["price"] else "", align="right", width=90),
            Column("手續費／稅", lambda r: fmt_num(r["fee"] + r["tax"], base) if r["fee"] + r["tax"] else "",
                   align="right", width=110),
            Column("股利", lambda r: fmt_num(r["amount"], base) if r["amount"] else "", align="right", width=90),
            Column("補充保費", lambda r: fmt_num(r["nhi"], base) if r["nhi"] else "", align="right", width=90),
            Column("交割帳戶", lambda r: r["cash_name"] or "", width=150),
            Column("備註", lambda r: r["note"], stretch=True),
        ], sortable=False)
        self.ev.rowActivated.connect(self._open_event)
        lay.addWidget(self.ev, 1)
        note = QLabel("每筆買賣、股利與市價評價都會自動產生會計分錄（收支明細中類型顯示為「投資」）。買賣不會自動評價。"
                      "「買進／賣出（分錄）」是在複式分錄中連結標的的交易，按兩下可開啟該傳票。"
                      "若輸入錯誤，請刪除該筆交易（分錄請作廢該傳票），系統會自動重算之後的成本與分錄。")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        self.tabs.addTab(w, "交易紀錄")

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        top = QHBoxLayout()
        top.addWidget(QLabel("年度"))
        self.year = QComboBox()
        self.year.currentIndexChanged.connect(self.load_realized)
        top.addWidget(self.year)
        top.addStretch()
        self.real_sum = QLabel()
        self.real_sum.setStyleSheet("font-weight:700;")
        top.addWidget(self.real_sum)
        lay.addLayout(top)
        self.real = DataTable([
            Column("賣出日期", lambda r: fmt_date(r["date"]), width=118),
            Column("標的", lambda r: f"{r['code']} {r['name']}".strip(), stretch=True),
            Column("實收金額", lambda r: fmt_num(r["proceeds"], base), align="right", width=140),
            Column("出售成本", lambda r: fmt_num(r["cost"], base), align="right", width=140),
            Column("已實現損益", lambda r: fmt_num(r["gain"], base), align="right", width=140, bold=True,
                   color=lambda r: C.income if r["gain"] >= 0 else C.expense),
        ], sortable=False)
        lay.addWidget(self.real, 1)
        self.tabs.addTab(w, "已實現損益")
        self.tabs.currentChanged.connect(lambda _: self.refresh())

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        base = self.ctx.base
        hold = self.inv.holdings()
        rates = {a["id"]: a["rate"] for a in self.db.list_accounts(include_archived=True)}
        mv = sum(h["market_value"] * rates.get(h["account_id"], 1) for h in hold)
        cost = sum(h["cost"] * rates.get(h["account_id"], 1) for h in hold)
        y = dt.date.today().year
        ps = self.inv.period_summary(f"{y}-01-01", f"{y}-12-31")
        self.c_mv.set_money(mv, base)
        self.c_cost.set_money(cost, base)
        self.c_unr.set_money(mv - cost, base, f"報酬率 {(mv - cost) / cost:+.2%}" if cost else "",
                             C.income if mv >= cost else C.expense)
        self.c_real.set_money(ps["realized"], base, "", C.income if ps["realized"] >= 0 else C.expense)
        self.c_div.set_money(ps["dividends"], base,
                             f"已扣補充保費 {fmt_money(ps['nhi'], base)}" if ps["nhi"] else "", C.gold)
        self.hold.set_rows(hold)
        self.donut.set_data(sorted(((h["name"], h["market_value"] * rates.get(h["account_id"], 1))
                                    for h in hold), key=lambda x: -x[1]))
        cur = self.ev_filter.currentData()
        self.ev_filter.blockSignals(True)
        self.ev_filter.clear()
        self.ev_filter.addItem("全部標的", None)
        for s in self.inv.list_securities(include_archived=True):
            self.ev_filter.addItem(f"{s['code']} {s['name']}".strip(), s["id"])
        self.ev_filter.setCurrentIndex(max(0, self.ev_filter.findData(cur)))
        self.ev_filter.blockSignals(False)
        self.load_events()
        years = sorted({e["date"][:4] for e in self.inv.events()} | {str(y)}, reverse=True)
        cy = self.year.currentText()
        self.year.blockSignals(True)
        self.year.clear()
        self.year.addItems(years)
        if cy in years:
            self.year.setCurrentText(cy)
        self.year.blockSignals(False)
        self.load_realized()

    def load_events(self) -> None:
        rows = self.inv.events(self.ev_filter.currentData())
        self.ev.set_rows(list(reversed(rows)))

    def load_realized(self) -> None:
        y = self.year.currentText()
        if not y:
            return
        ps = self.inv.period_summary(f"{y}-01-01", f"{y}-12-31")
        self.real.set_rows(ps["realized_rows"])
        self.real_sum.setText(f"{y} 年已實現損益合計 {fmt_money(ps['realized'], self.ctx.base, signed=True)}"
                              f"　｜　股利 {fmt_money(ps['dividends'], self.ctx.base)}")

    def show_events(self, sid: int) -> None:
        self.tabs.setCurrentIndex(1)
        self.ev_filter.setCurrentIndex(max(0, self.ev_filter.findData(sid)))

    def add_security(self) -> None:
        SecurityDialog(self.ctx, parent=self.window()).exec()

    def trade(self, kind: str) -> None:
        if not self.inv.list_securities():
            if not any(a["kind"] == "asset" and a["category"] in INVESTMENT_CATEGORIES
                       for a in self.db.list_accounts()):
                info(self, "請先到「帳戶管理 → 會計科目表」新增一個投資科目（例如：短期投資，期初餘額 0），"
                           "再回來新增投資標的。")
                return
            if not SecurityDialog(self.ctx, parent=self.window()).exec():
                return
        r = self.hold.current_row()
        TradeDialog(self.ctx, kind, r["id"] if r else None, parent=self.window()).exec()

    def prices(self) -> None:
        if not self.inv.holdings():
            info(self, "目前沒有持股。")
            return
        PriceDialog(self.ctx, self.window()).exec()

    def _open_event(self, r: dict) -> None:
        if r.get("txn_id"):
            from ..dialogs import open_voucher
            open_voucher(self.ctx, r["txn_id"], self.window())

    def delete_event(self) -> None:
        r = self.ev.current_row()
        if not r:
            info(self, "請先點選一筆交易。")
            return
        if r.get("txn_id"):
            info(self, f"這筆交易來自複式分錄 {r['cash_name'].replace('分錄 ', '')}，"
                       "請按兩下開啟該傳票後「作廢」，持股與評價會自動重算。")
            return
        if not ask(self, f"確定要刪除「{fmt_date(r['date'])} {r['sec_name']} {KIND_LABELS[r['kind']]}」嗎？\n"
                         "系統會自動重算之後的成本與分錄。", yes="刪除", danger=True):
            return
        try:
            self.inv.delete_event(r["id"])
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit("已刪除並重新計算")

    def hold_menu(self, pos) -> None:
        r = self.hold.current_row()
        if not r:
            return
        m = QMenu(self)
        for text, fn in (("買進", lambda: TradeDialog(self.ctx, "buy", r["id"], self.window()).exec()),
                         ("賣出", lambda: TradeDialog(self.ctx, "sell", r["id"], self.window()).exec()),
                         ("現金股利", lambda: TradeDialog(self.ctx, "cash_div", r["id"], self.window()).exec()),
                         ("股票股利（配股）", lambda: TradeDialog(self.ctx, "stock_div", r["id"], self.window()).exec()),
                         ("查看交易紀錄", lambda: self.show_events(r["id"])),
                         ("編輯標的", lambda: SecurityDialog(self.ctx, self.inv.get_security(r["id"]),
                                                         self.window()).exec())):
            a = QAction(text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.exec(self.hold.viewport().mapToGlobal(pos))
