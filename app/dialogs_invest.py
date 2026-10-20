"""投資管理視窗：標的、買賣、股利、更新股價、更新匯率。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QTableWidget, QTableWidgetItem)

from .context import AppContext
from .database import CURRENCIES, INVESTMENT_CATEGORIES
from .dialogs import BaseDialog, fill_account_combo
from .investments import KIND_LABELS, Investments
from .theme import C, fmt_money, icon
from .widgets import AmountEdit, button, iso, make_date_edit, section_title


def online_enabled(ctx: AppContext) -> bool:
    return ctx.db.get_setting("online_updates", "0") == "1"


class SecurityDialog(BaseDialog):
    def __init__(self, ctx: AppContext, sec: dict | None = None, parent=None,
                 account_id: int | None = None):
        super().__init__("編輯投資標的" if sec else "新增投資標的", parent, width=520)
        self.ctx = ctx
        self.inv = Investments(ctx.db)
        self.sec = sec
        f = QFormLayout()
        f.setVerticalSpacing(10)
        self.account = QComboBox()
        accs = [a for a in ctx.db.list_accounts() if a["kind"] == "asset"]
        accs.sort(key=lambda a: (a["category"] not in INVESTMENT_CATEGORIES, a["id"]))
        for a in accs:
            self.account.addItem(f"{a['name']}（{a['category']}）", a["id"])
        if sec or account_id:
            self.account.setCurrentIndex(max(0, self.account.findData(sec["account_id"] if sec else account_id)))
            self.account.setEnabled(False)
        self.code = QLineEdit(sec["code"] if sec else "")
        self.code.setPlaceholderText("例如 0050、2330（基金可留空）")
        self.name = QLineEdit(sec["name"] if sec else "")
        self.name.setPlaceholderText("例如 元大台灣50")
        self.note = QLineEdit(sec["note"] if sec else "")
        f.addRow("所屬投資帳戶", self.account)
        f.addRow("代號", self.code)
        f.addRow("名稱", self.name)
        f.addRow("備註", self.note)
        self.root.addLayout(f)
        hint = QLabel("投資科目請先在「會計科目表」或「帳戶管理」建立（類別選「短期投資」、「長期投資」、"
                      "「股票」、「基金」或「債券」，期初餘額填 0）。持股可用「買進」登錄，"
                      "或在複式分錄中借記投資科目並選擇標的與股數；之後依股價自動評價。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        ok = button("儲存", "Primary")
        ok.clicked.connect(self.save)
        bar.addWidget(c)
        bar.addWidget(ok)
        self.root.addLayout(bar)

    def save(self) -> None:
        try:
            if self.sec:
                self.inv.update_security(self.sec["id"], self.code.text(), self.name.text(),
                                         self.note.text())
            else:
                if self.account.currentData() is None:
                    raise ValueError("請先到「帳戶管理」新增投資帳戶（例如：證券戶）")
                self.new_id = self.inv.add_security(self.account.currentData(), self.code.text(),
                                                    self.name.text(), self.note.text())
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已儲存投資標的：{self.name.text()}")
        self.accept()


class TradeDialog(BaseDialog):
    def __init__(self, ctx: AppContext, kind: str = "buy", security_id: int | None = None, parent=None):
        super().__init__(KIND_LABELS[kind], parent, width=600)
        self.ctx = ctx
        self.db = ctx.db
        self.inv = Investments(ctx.db)
        self.kind = kind
        colors = {"buy": C.expense, "sell": C.income, "cash_div": C.income, "stock_div": C.adjust}
        t = QLabel(KIND_LABELS[kind])
        t.setObjectName("SectionTitle")
        t.setStyleSheet(f"color:{colors[kind]};")
        self.root.addWidget(t)
        f = QFormLayout()
        f.setVerticalSpacing(10)
        self.sec = QComboBox()
        for s in self.inv.list_securities():
            self.sec.addItem(f"{s['code']}　{s['name']}（{s['account_name']}）".strip(), s["id"])
        if security_id:
            self.sec.setCurrentIndex(max(0, self.sec.findData(security_id)))
        add_sec = button("新增標的", "Link")
        add_sec.clicked.connect(self.new_security)
        srow = QHBoxLayout()
        srow.addWidget(self.sec, 1)
        srow.addWidget(add_sec)
        self.date = make_date_edit()
        self.shares = AmountEdit()
        self.shares.decimals = 4
        self.shares.setObjectName("")
        self.price = AmountEdit()
        self.price.decimals = 4
        self.price.setObjectName("")
        self.fee = AmountEdit()
        self.fee.setObjectName("")
        self.tax = AmountEdit()
        self.tax.setObjectName("")
        self.amount = AmountEdit()
        self.amount.setObjectName("")
        self.nhi = AmountEdit()
        self.nhi.setObjectName("")
        self.cash = QComboBox()
        self.note = QLineEdit()
        self.calc = QLabel()
        self.calc.setStyleSheet("font-weight:700;")
        self.calc.setWordWrap(True)
        self.held = QLabel()
        self.held.setObjectName("Hint")
        f.addRow("投資標的", srow)
        f.addRow("", self.held)
        f.addRow("日期", self.date)
        if kind in ("buy", "sell"):
            f.addRow("股數（單位）", self.shares)
            f.addRow("成交價", self.price)
            f.addRow("手續費", self.fee)
            if kind == "sell":
                f.addRow("證券交易稅", self.tax)
        elif kind == "stock_div":
            f.addRow("配發股數", self.shares)
        else:
            f.addRow("股利總額", self.amount)
            f.addRow("健保補充保費", self.nhi)
        if kind != "stock_div":
            f.addRow("交割（扣款／入帳）帳戶", self.cash)
        f.addRow("備註", self.note)
        self.root.addLayout(f)
        self.root.addWidget(self.calc)
        hints = {
            "buy": "手續費預設 0.1425%（最低 20 元），可依券商折扣修改。成本＝成交金額＋手續費。",
            "sell": "證交稅自動帶入：股票 0.3%、ETF（代號 00 開頭）0.1%，可修改。已實現損益＝淨價款－平均成本。",
            "cash_div": "單筆股利達 2 萬元時，自動帶入 2.11% 二代健保補充保費，可修改。",
            "stock_div": "股票股利（配股）只增加股數，總成本不變，平均成本自動下降。",
        }
        h = QLabel(hints[kind])
        h.setObjectName("Hint")
        h.setWordWrap(True)
        self.root.addWidget(h)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        ok = button("儲存", "Primary")
        ok.setDefault(True)
        ok.clicked.connect(self.save)
        bar.addWidget(c)
        bar.addWidget(ok)
        self.root.addLayout(bar)

        self.sec.currentIndexChanged.connect(self._sec_changed)
        for w in (self.shares, self.price):
            w.valueChanged.connect(self._auto_fees)
        for w in (self.fee, self.tax, self.amount, self.nhi):
            w.valueChanged.connect(self._recalc)
        self.amount.valueChanged.connect(self._auto_nhi)
        self.date.dateChanged.connect(self._sec_changed)
        self._fee_touched = False
        self.fee.textEdited.connect(lambda _: setattr(self, "_fee_touched", True))
        self.tax.textEdited.connect(lambda _: setattr(self, "_fee_touched", True))
        self._nhi_touched = False
        self.nhi.textEdited.connect(lambda _: setattr(self, "_nhi_touched", True))
        self._sec_changed()

    def new_security(self) -> None:
        dlg = SecurityDialog(self.ctx, parent=self)
        if dlg.exec():
            s = self.inv.get_security(dlg.new_id)
            self.sec.addItem(f"{s['code']}　{s['name']}（{s['account_name']}）".strip(), s["id"])
            self.sec.setCurrentIndex(self.sec.count() - 1)

    def _sec_changed(self) -> None:
        sid = self.sec.currentData()
        if sid is None:
            self.held.setText("請先新增投資標的")
            return
        s = self.inv.get_security(sid)
        cur = self.cash.currentData()
        self.cash.clear()
        for a in self.db.list_accounts():
            if a["currency"] == s["currency"] and a["id"] != s["account_id"] and a["kind"] == "asset" \
                    and a["category"] not in INVESTMENT_CATEGORIES:
                self.cash.addItem(a["name"], a["id"])
        i = self.cash.findData(cur if cur is not None else self.inv.last_cash_account(sid))
        if i >= 0:
            self.cash.setCurrentIndex(i)
        self.code = s["code"]
        st = self.inv.replay(sid, iso(self.date.date()))
        self.state = st
        self.currency = s["currency"]
        self.held.setText(f"目前持股 {st['shares']:,.0f}　平均成本 {st['avg_cost']:,.2f}　"
                          f"最近價格 {st['price']:,.2f}")
        if self.kind in ("buy", "sell") and not self.price.text() and st["price"]:
            self.price.setValue(st["price"])
        self._auto_fees()

    def _auto_fees(self) -> None:
        if self.kind in ("buy", "sell") and not self._fee_touched:
            fee, tax = self.inv.suggest_fees(self.kind, self.shares.value() or 0, self.price.value() or 0,
                                             getattr(self, "code", ""))
            self.fee.blockSignals(True)
            self.tax.blockSignals(True)
            self.fee.setValue(fee or None)
            self.tax.setValue(tax or None)
            self.fee.blockSignals(False)
            self.tax.blockSignals(False)
        self._recalc()

    def _auto_nhi(self) -> None:
        if not self._nhi_touched:
            self.nhi.blockSignals(True)
            self.nhi.setValue(self.inv.suggest_nhi(self.amount.value() or 0) or None)
            self.nhi.blockSignals(False)
        self._recalc()

    def _recalc(self) -> None:
        if not hasattr(self, "state"):
            return
        cur = self.currency
        q = self.shares.value() or 0
        p = self.price.value() or 0
        fee = self.fee.value() or 0
        tax = self.tax.value() or 0
        if self.kind == "buy":
            self.calc.setText(f"應付金額 {fmt_money(q * p + fee, cur)}（成本，含手續費）")
        elif self.kind == "sell":
            proceeds = q * p - fee - tax
            cost = self.state["avg_cost"] * q
            g = proceeds - cost
            self.calc.setText(f"實收金額 {fmt_money(proceeds, cur)}　｜　出售成本 {fmt_money(cost, cur)}"
                              f"　｜　預估已實現損益 {fmt_money(g, cur, signed=True)}")
            self.calc.setStyleSheet(f"font-weight:700; color:{C.income if g >= 0 else C.expense};")
        elif self.kind == "cash_div":
            a = self.amount.value() or 0
            n = self.nhi.value() or 0
            self.calc.setText(f"實際入帳 {fmt_money(a - n, cur)}")
        else:
            self.calc.setText(f"配股後持股 {self.state['shares'] + q:,.0f}")

    def save(self) -> None:
        sid = self.sec.currentData()
        if sid is None:
            self.show_error("請先新增投資標的")
            return
        try:
            self.inv.add_event(sid, self.kind, iso(self.date.date()), shares=self.shares.value() or 0,
                               price=self.price.value() or 0, fee=self.fee.value() or 0,
                               tax=self.tax.value() or 0, amount=self.amount.value() or 0,
                               nhi=self.nhi.value() or 0, cash_account_id=self.cash.currentData(),
                               note=self.note.text())
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已登錄{KIND_LABELS[self.kind]}，分錄已自動產生")
        self.accept()


class PriceDialog(BaseDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("更新股價", parent, width=820)
        self.ctx = ctx
        self.inv = Investments(ctx.db)
        top = QHBoxLayout()
        top.addWidget(QLabel("價格日期"))
        self.date = make_date_edit()
        top.addWidget(self.date)
        top.addStretch()
        if online_enabled(ctx):
            self.fetch_btn = button("從網路取得收盤價", icon=icon("download"))
            self.fetch_btn.clicked.connect(self.fetch)
            top.addWidget(self.fetch_btn)
        self.root.addLayout(top)
        self.holdings = self.inv.holdings()
        self.table = QTableWidget(len(self.holdings), 5)
        self.table.setHorizontalHeaderLabels(["代號", "名稱", "持股", "目前價格", "新價格"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w in ((0, 90), (2, 120), (3, 130), (4, 170)):
            self.table.setColumnWidth(i, w)
        self.edits = []
        for r, h in enumerate(self.holdings):
            for col, text in ((0, h["code"]), (1, h["name"]), (2, f"{h['shares']:,.0f}"),
                              (3, f"{h['price']:,.2f}")):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if col >= 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, col, it)
            ed = AmountEdit()
            ed.decimals = 4
            ed.setObjectName("")
            ed.setPlaceholderText(f"{h['price']:,.2f}")
            self.table.setCellWidget(r, 4, ed)
            self.edits.append(ed)
        self.table.setMinimumHeight(min(10, max(3, len(self.holdings))) * 48 + 50)
        self.root.addWidget(self.table)
        hint = QLabel("輸入最新價格（留空表示不變）。系統會依新價格重新評價，差額記為「未實現評價損益」。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        ok = button("儲存", "Primary")
        ok.clicked.connect(self.save)
        bar.addWidget(c)
        bar.addWidget(ok)
        self.root.addLayout(bar)

    def fetch(self) -> None:
        from . import online
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("下載中…")
        online.run_background(self, online.fetch_tw_prices, self._fetched, self._failed)

    def _fetched(self, prices: dict) -> None:
        n = 0
        for h, ed in zip(self.holdings, self.edits):
            hit = prices.get(h["code"].strip())
            if hit:
                ed.setValue(hit[1])
                n += 1
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("從網路取得收盤價")
        from .online import PRICE_SOURCE
        self.show_ok(f"已填入 {n} 檔收盤價（來源：{PRICE_SOURCE}），請確認後按「儲存」。")

    def _failed(self, msg: str) -> None:
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("從網路取得收盤價")
        self.show_error(msg)

    def save(self) -> None:
        prices = [(h["id"], ed.value()) for h, ed in zip(self.holdings, self.edits) if ed.value()]
        if not prices:
            self.show_error("請至少輸入一個新價格")
            return
        try:
            n = self.inv.set_prices(prices, iso(self.date.date()))
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已更新 {n} 檔價格並重新評價")
        self.accept()


class RateDialog(BaseDialog):
    """一次更新所有外幣帳戶匯率。"""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("更新匯率", parent, width=640)
        self.ctx = ctx
        self.db = ctx.db
        base = ctx.base
        self.accs = [a for a in self.db.list_accounts() if a["currency"] != base]
        codes = sorted({a["currency"] for a in self.accs})
        top = QHBoxLayout()
        top.addWidget(section_title("外幣匯率"))
        top.addStretch()
        if online_enabled(ctx) and codes:
            self.fetch_btn = button("從網路取得參考匯率", icon=icon("download"))
            self.fetch_btn.clicked.connect(self.fetch)
            top.addWidget(self.fetch_btn)
        self.root.addLayout(top)
        f = QFormLayout()
        f.setVerticalSpacing(10)
        self.spins: dict[str, QDoubleSpinBox] = {}
        for code in codes:
            sp = QDoubleSpinBox()
            sp.setDecimals(4)
            sp.setRange(0.0001, 100000)
            sp.setValue(next(a["rate"] for a in self.accs if a["currency"] == code))
            self.spins[code] = sp
            f.addRow(f"1 {CURRENCIES.get(code, (code,))[0]}（{code}）＝", sp)
        if not codes:
            f.addRow(QLabel("目前沒有外幣帳戶。"))
        self.root.addLayout(f)
        hint = QLabel(f"單位為{CURRENCIES.get(base, (base,))[0]}。可參考銀行牌告的「即期」買賣中價。"
                      "匯率變動造成的價值差異會列入「兌換損益」。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        ok = button("儲存", "Primary")
        ok.clicked.connect(self.save)
        ok.setEnabled(bool(codes))
        bar.addWidget(c)
        bar.addWidget(ok)
        self.root.addLayout(bar)

    def fetch(self) -> None:
        from . import online
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("下載中…")
        base = self.ctx.base
        online.run_background(self, lambda: online.fetch_fx_rates(base), self._fetched, self._failed)

    def _fetched(self, rates: dict) -> None:
        n = 0
        for code, sp in self.spins.items():
            if code in rates:
                sp.setValue(rates[code])
                n += 1
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("從網路取得參考匯率")
        from .online import FX_SOURCE
        self.show_ok(f"已填入 {n} 種匯率（來源：{FX_SOURCE}），請確認後按「儲存」。")

    def _failed(self, msg: str) -> None:
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("從網路取得參考匯率")
        self.show_error(msg)

    def save(self) -> None:
        for a in self.accs:
            sp = self.spins.get(a["currency"])
            if sp:
                self.db.update_account(a["id"], rate=sp.value())
        self.ctx.changed()
        self.ctx.toast.emit("匯率已更新")
        self.accept()

