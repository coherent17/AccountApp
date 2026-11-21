"""投資管理視窗：標的、買賣、股利、市價評價、更新匯率。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QTableWidget, QTableWidgetItem)

from .context import AppContext
from .database import CURRENCIES, INVESTMENT_CATEGORIES, fmt_shares
from .dialogs import BaseDialog, fill_account_combo
from .investments import ETF_TAX, FEE_MIN, FEE_RATE, KIND_LABELS, STOCK_TAX, Investments, default_tax_rate
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
        # 手續費與證交稅：用於自動帶入費用，以及評價時估算淨售價；「類型」帶入該類型的費率
        self.kind = QComboBox()
        self.kind.setMinimumWidth(220)
        self.fee_rate = self._pct_box(4, 4.9)
        self.fee_min = QDoubleSpinBox()
        self.fee_min.setRange(0, 9999)
        self.fee_min.setDecimals(0)
        self.fee_min.setSuffix(" 元")
        self.tax_rate = self._pct_box(3, 4.9)
        self.fee_rate.setValue((sec["fee_rate"] if sec else FEE_RATE) * 100)
        self.fee_min.setValue(sec["fee_min"] if sec else FEE_MIN)
        self.tax_rate.setValue((sec["tax_rate"] if sec else default_tax_rate(self.code.text())) * 100)
        self._fill_kinds(sec["type_name"] if sec else ("ETF" if self.tax_rate.value() == ETF_TAX * 100 else "股票"))
        if not sec:
            self._kind_chosen()
        self.kind.activated.connect(self._kind_chosen)
        for w in (self.fee_rate, self.fee_min, self.tax_rate):
            w.valueChanged.connect(self._rates_edited)
        if not sec:
            self.code.textEdited.connect(self._code_typed)
        kind_row = QHBoxLayout()
        kind_row.addWidget(self.kind, 1)
        manage = button("管理類型…", tooltip="新增或修改類型（每個類型有自己的手續費率、最低手續費與證交稅率）")
        manage.clicked.connect(self.manage_kinds)
        kind_row.addWidget(manage)
        f.addRow("類型", kind_row)
        f.addRow("手續費率", self.fee_rate)
        f.addRow("最低手續費", self.fee_min)
        f.addRow("證券交易稅率", self.tax_rate)
        self.root.addLayout(f)
        fh = QLabel("手續費一般為 0.1425%，有折扣時請輸入折扣後的費率（例如 6 折為 0.0855%）。"
                    "手續費與證交稅依券商慣例無條件捨去至元。")
        fh.setObjectName("Hint")
        fh.setWordWrap(True)
        self.root.addWidget(fh)
        hint = QLabel("投資科目請先在「會計科目表」或「帳戶管理」建立（類別選「短期投資」、「長期投資」、"
                      "「股票」、「基金」或「債券」，期初餘額填 0）。持股可用「買進」登錄，"
                      "或在複式分錄中借記投資科目並選擇標的與股數；需要評價時再用「市價評價」輸入市價。")
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

    @staticmethod
    def _pct_box(decimals: int, top: float) -> QDoubleSpinBox:
        w = QDoubleSpinBox()
        w.setRange(0, top)
        w.setDecimals(decimals)
        w.setSingleStep(0.01)
        w.setSuffix(" %")
        return w

    def _fill_kinds(self, select: str) -> None:
        self.types = self.inv.security_types()
        self.kind.blockSignals(True)
        self.kind.clear()
        for t in self.types:
            self.kind.addItem(f"{t['name']}（手續費 {t['fee_rate'] * 100:.4g}%、證交稅 {t['tax_rate'] * 100:.3g}%）",
                              t["name"])
        self.kind.addItem("自訂（只用於這個標的）", "")
        i = self.kind.findData(select) if select else -1
        self.kind.setCurrentIndex(i if i >= 0 else self.kind.count() - 1)
        self.kind.blockSignals(False)

    def _type(self) -> dict | None:
        return next((t for t in self.types if t["name"] == self.kind.currentData()), None)

    def _kind_chosen(self) -> None:
        t = self._type()
        if t:
            for w, v in ((self.fee_rate, t["fee_rate"] * 100), (self.fee_min, t["fee_min"]),
                         (self.tax_rate, t["tax_rate"] * 100)):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)

    def _rates_edited(self) -> None:
        """手動改了費率、與所選類型不同時，改為「自訂」。"""
        t = self._type()
        if t and (abs(self.fee_rate.value() - t["fee_rate"] * 100) > 1e-7 or self.fee_min.value() != t["fee_min"]
                  or abs(self.tax_rate.value() - t["tax_rate"] * 100) > 1e-7):
            self.kind.setCurrentIndex(self.kind.count() - 1)

    def _code_typed(self, code: str) -> None:
        if self.kind.currentData() in ("股票", "ETF"):
            want = "ETF" if default_tax_rate(code) == ETF_TAX else "股票"
            i = self.kind.findData(want)
            if i >= 0 and i != self.kind.currentIndex():
                self.kind.setCurrentIndex(i)
                self._kind_chosen()

    def manage_kinds(self) -> None:
        cur = self.kind.currentData()
        dlg = SecurityTypesDialog(self.ctx, self)
        if dlg.exec():
            self._fill_kinds(dlg.renamed.get(cur, cur))
            self._kind_chosen()

    def save(self) -> None:
        rates = {"fee_rate": round(self.fee_rate.value() / 100, 6), "fee_min": self.fee_min.value(),
                 "tax_rate": round(self.tax_rate.value() / 100, 6), "type_name": self.kind.currentData() or ""}
        try:
            if self.sec:
                self.inv.update_security(self.sec["id"], self.code.text(), self.name.text(),
                                         self.note.text(), **rates)
            else:
                if self.account.currentData() is None:
                    raise ValueError("請先到「帳戶管理」新增投資帳戶（例如：證券戶）")
                self.new_id = self.inv.add_security(self.account.currentData(), self.code.text(),
                                                    self.name.text(), self.note.text(), **rates)
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已儲存投資標的：{self.name.text()}")
        self.accept()


class SecurityTypesDialog(BaseDialog):
    """新增、修改、刪除標的類型；每個類型有自己的手續費率、最低手續費與證交稅率。"""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("管理標的類型", parent, width=760)
        self.ctx = ctx
        self.inv = Investments(ctx.db)
        self.renamed: dict[str, str] = {}
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["類型名稱", "手續費率", "最低手續費", "證券交易稅率"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in (1, 2, 3):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, 150)
        self.table.setMinimumHeight(260)
        for t in self.inv.security_types():
            self.add_row(t)
        self.root.addWidget(self.table)
        tools = QHBoxLayout()
        add = button("新增類型", icon=icon("plus"))
        add.clicked.connect(lambda: self.add_row())
        rem = button("刪除選取類型", icon=icon("trash"))
        rem.clicked.connect(self.remove_row)
        tools.addWidget(add)
        tools.addWidget(rem)
        tools.addStretch()
        self.root.addLayout(tools)
        hint = QLabel("每個標的可選擇一個類型，新增或編輯標的時會帶入該類型的費率。"
                      "修改類型的費率後，屬於該類型的標的會一併改用新費率，市價評價分錄也會依新費率重算"
                      "（已結帳期間有評價的標的不會變更）。刪除類型時，原屬該類型的標的保留目前費率，改為「自訂」。")
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

    def add_row(self, t: dict | None = None) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QLineEdit(t["name"] if t else "")
        name.setPlaceholderText("例如 股票（6 折）")
        name.setProperty("old", t["name"] if t else "")
        fee = SecurityDialog._pct_box(4, 4.9)
        fee.setValue((t["fee_rate"] if t else FEE_RATE) * 100)
        mn = QDoubleSpinBox()
        mn.setRange(0, 9999)
        mn.setDecimals(0)
        mn.setSuffix(" 元")
        mn.setValue(t["fee_min"] if t else FEE_MIN)
        tax = SecurityDialog._pct_box(3, 4.9)
        tax.setValue((t["tax_rate"] if t else STOCK_TAX) * 100)
        for col, w in enumerate((name, fee, mn, tax)):
            self.table.setCellWidget(r, col, w)
        if not t:
            name.setFocus()

    def remove_row(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            self.show_error("請先點選要刪除的類型")
            return
        for r in rows:
            self.table.removeRow(r)

    def rows(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            name, fee, mn, tax = (self.table.cellWidget(r, c) for c in range(4))
            out.append({"name": name.text(), "old": name.property("old") or "",
                        "fee_rate": round(fee.value() / 100, 6), "fee_min": mn.value(),
                        "tax_rate": round(tax.value() / 100, 6)})
        return out

    def save(self) -> None:
        rows = self.rows()
        try:
            problems = self.inv.save_security_types(rows)
        except ValueError as e:
            self.show_error(str(e))
            return
        self.renamed = {r["old"]: r["name"].strip() for r in rows if r["old"]}
        self.ctx.changed()
        if problems:
            from .widgets import info
            info(self, "類型已儲存，但下列標的無法變更費率：\n" + "\n".join(problems))
        self.ctx.toast.emit("已儲存標的類型")
        self.accept()


class SecurityListDialog(BaseDialog):
    """標的設定：列出所有投資標的（含已無持股、已封存），可選擇並修改內容、費率與稅率。"""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("標的設定", parent, width=980)
        self.ctx = ctx
        self.inv = Investments(ctx.db)
        from .widgets import Column, DataTable
        self.table = DataTable([
            Column("代號", lambda r: r["code"], align="center", width=80, bold=True),
            Column("名稱", lambda r: r["name"] + ("（已封存）" if r["archived"] else ""), width=180, bold=True),
            Column("投資科目", lambda r: r["account_name"], width=170),
            Column("類型", lambda r: r["type_name"] or "自訂", width=110),
            Column("手續費率", lambda r: f"{r['fee_rate'] * 100:.4g}%", align="right", width=95),
            Column("最低手續費", lambda r: f"{r['fee_min']:,.0f} 元", align="right", width=100),
            Column("證交稅率", lambda r: f"{r['tax_rate'] * 100:.3g}%", align="right", width=95),
            Column("備註", lambda r: r["note"], stretch=True),
        ], sortable=False)
        self.table.setMinimumHeight(380)
        self.table.rowActivated.connect(self.edit)
        self.root.addWidget(self.table)
        bar = QHBoxLayout()
        for text, fn, ic in (("新增標的", self.add, "plus"), ("編輯選取標的", lambda: self.edit(self.table.current_row()),
                                                             "edit"),
                             ("管理類型", self.kinds, "list")):
            b = button(text, icon=icon(ic))
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.archive_btn = button("封存／取消封存")
        self.archive_btn.setToolTip("封存後不再出現在選單中（資料保留）；已無持股的標的才可封存")
        self.archive_btn.clicked.connect(self.toggle_archive)
        bar.addWidget(self.archive_btn)
        bar.addStretch()
        close = button("關閉", "Primary")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        hint = QLabel("按兩下或點選後按「編輯選取標的」，可修改代號、名稱、類型、手續費率、最低手續費與證交稅率。"
                      "費率改變時，該標的的市價評價分錄會依新費率重新計算。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.root.addWidget(self.msg)
        self.root.addLayout(bar)
        self.load()

    def load(self) -> None:
        self.table.set_rows(self.inv.list_securities(include_archived=True))

    def add(self) -> None:
        if SecurityDialog(self.ctx, parent=self).exec():
            self.load()

    def edit(self, r: dict | None) -> None:
        if not r:
            self.show_error("請先點選一個標的")
            return
        if SecurityDialog(self.ctx, self.inv.get_security(r["id"]), parent=self).exec():
            self.load()

    def kinds(self) -> None:
        if SecurityTypesDialog(self.ctx, self).exec():
            self.load()

    def toggle_archive(self) -> None:
        r = self.table.current_row()
        if not r:
            self.show_error("請先點選一個標的")
            return
        if not r["archived"] and abs(self.inv.replay(r["id"])["shares"]) > 1e-9:
            self.show_error(f"「{r['name']}」還有持股，無法封存")
            return
        self.inv.archive_security(r["id"], not r["archived"])
        self.ctx.changed()
        self.load()


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
                          f"最近評價市價 {st['price']:,.2f}")
        if self.kind in ("buy", "sell") and not self.price.text() and st["price"]:
            self.price.setValue(st["price"])
        self._auto_fees()

    def _auto_fees(self) -> None:
        if self.kind in ("buy", "sell") and not self._fee_touched:
            sid = self.sec.currentData()
            q, p = self.shares.value() or 0, self.price.value() or 0
            fee, tax = (self.inv.fees_for(sid, self.kind, q, p) if isinstance(sid, int)
                        else self.inv.suggest_fees(self.kind, q, p))
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
        super().__init__("市價評價", parent, width=820)
        self.ctx = ctx
        self.inv = Investments(ctx.db)
        top = QHBoxLayout()
        top.addWidget(QLabel("評價日期"))
        self.date = make_date_edit()
        self.date.dateChanged.connect(lambda _: self.load())
        top.addWidget(self.date)
        top.addStretch()
        if online_enabled(ctx):
            self.fetch_btn = button("從網路取得收盤價", icon=icon("download"))
            self.fetch_btn.clicked.connect(self.fetch)
            top.addWidget(self.fetch_btn)
        self.root.addLayout(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["代號", "名稱", "持股", "最近評價市價", "評價市價"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i, w in ((0, 90), (2, 120), (3, 130), (4, 170)):
            self.table.setColumnWidth(i, w)
        self.load()
        self.table.setMinimumHeight(min(10, max(3, len(self.holdings))) * 48 + 50)
        self.root.addWidget(self.table)
        hint = QLabel("選擇評價日期並輸入市價（留空表示這檔不評價）。按「產生評價分錄」後才會把帳面價值調整為"
                      "預估淨售價（市價×股數，扣除預估賣出手續費與證交稅），差額記為「未實現評價損益」；"
                      "同一天再次評價會取代先前的市價。"
                      "買進、賣出不會自動評價，賣出也不迴轉已認列的評價，所售股份的評價在這裡一併調整；"
                      "已全數賣出的標的，剩餘評價會自動歸零。輸入錯誤時，可到「交易紀錄」刪除該筆市價評價。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        ok = button("產生評價分錄", "Primary")
        ok.clicked.connect(self.save)
        bar.addWidget(c)
        bar.addWidget(ok)
        self.root.addLayout(bar)

    def load(self) -> None:
        """列出評價日當時的持股。"""
        self.holdings = self.inv.holdings(iso(self.date.date()))
        self.table.setRowCount(len(self.holdings))
        self.edits = []
        for r, h in enumerate(self.holdings):
            sold = h["shares"] <= 1e-9
            last = f"{h['price']:,.2f}" if h["price"] else ("已全數賣出" if sold else "尚未評價")
            for col, text in ((0, h["code"]), (1, h["name"]), (2, fmt_shares(h["shares"])), (3, last)):
                it = QTableWidgetItem(text)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if col >= 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, col, it)
            ed = AmountEdit()
            ed.decimals = 4
            ed.setObjectName("")
            ed.setPlaceholderText("輸入市價")
            if sold:   # 已無持股但仍有評價調整：評價時自動歸零
                ed.setPlaceholderText(f"剩餘帳面價值 {h['market_value']:,.0f} 歸零")
                ed.setEnabled(False)
            self.table.setCellWidget(r, 4, ed)
            self.edits.append(ed)

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
        self.show_ok(f"已填入 {n} 檔收盤價（來源：{PRICE_SOURCE}），請確認後按「產生評價分錄」。")

    def _failed(self, msg: str) -> None:
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText("從網路取得收盤價")
        self.show_error(msg)

    def save(self) -> None:
        prices = [(h["id"], ed.value()) for h, ed in zip(self.holdings, self.edits) if ed.value()]
        sold = [h for h in self.holdings if h["shares"] <= 1e-9]
        if not prices and not sold:
            self.show_error("請至少輸入一檔的市價")
            return
        try:
            day = iso(self.date.date())
            n = self.inv.set_prices(prices, day)
            for h in sold:   # 已全數賣出、仍有評價調整的標的：評價歸零（股數為 0，價格不影響金額）
                self.inv.add_event(h["id"], "price", day, price=self.inv.last_price(h["id"]) or 1.0,
                                   note="已全數賣出，剩餘評價歸零")
                n += 1
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已產生 {n} 檔評價分錄")
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
        self.show_ok(f"已填入 {n} 種匯率（來源：{FX_SOURCE}），請確認後按「產生評價分錄」。")

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

