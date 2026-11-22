"""會計科目表：檢視全部科目、新增與修改會計科目（含自訂科目代號）。"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QRadioButton, QWidget)

from .context import AppContext
from .database import (ASSET_CATEGORIES, CURRENCIES, EQUITY_ACCOUNT, EQUITY_CODE,
                       EXPENSE_TAX_TAGS, INCOME_TAX_TAGS, INVESTMENT_CATEGORIES,
                       LIABILITY_CATEGORIES, NATURE_LABELS, SPECIALS, TAX_TAGS)
from .dialogs import BaseDialog
from .theme import C, fmt_num, icon
from .widgets import AmountEdit, Column, DataTable, button, info, iso, make_date_edit

INVEST_HINT = ("投資科目（短期投資、長期投資等）可在複式分錄中連結投資標的與股數，"
               "評價請到「投資管理 → 市價評價」選日期並輸入市價，差額列「未實現評價損益」。")


class SubjectDialog(BaseDialog):
    """新增會計科目（資產、負債、收入、費用），或修改收入／費用科目。"""

    def __init__(self, ctx: AppContext, nature: str | None = None, category: dict | None = None,
                 parent=None):
        super().__init__("修改會計科目" if category else "新增會計科目", parent, width=600)
        self.ctx = ctx
        self.db = ctx.db
        self.edit_cat = category
        self.created_key: tuple | None = None
        self._auto = ""

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.form = form

        nat = QWidget()
        nl = QHBoxLayout(nat)
        nl.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        for key in ("asset", "liability", "income", "expense"):
            rb = QRadioButton(f"{NATURE_LABELS[key]}")
            self.group.addButton(rb)
            self.radios[key] = rb
            nl.addWidget(rb)
            rb.toggled.connect(lambda on: on and self._nature_changed())
        nl.addStretch()
        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：短期投資、長期投資、應收帳款、顧問收入")
        self.code = QLineEdit()
        self.code.setMaxLength(6)
        self.code.setPlaceholderText("3～6 位數字")
        self.code_hint = QLabel()
        self.code_hint.setObjectName("Hint")
        crow = QHBoxLayout()
        crow.addWidget(self.code, 1)
        crow.addWidget(self.code_hint)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.currentTextChanged.connect(lambda _: self._update_code())
        self.currency = QComboBox()
        for code, (name, _) in CURRENCIES.items():
            self.currency.addItem(f"{name}（{code}）", code)
        self.currency.setCurrentIndex(max(0, self.currency.findData(ctx.base)))
        self.opening = AmountEdit()
        self.opening_date = make_date_edit(dt.date.today().replace(month=1, day=1).isoformat())
        self.budget = AmountEdit()
        self.tax = QComboBox()

        form.addRow("科目性質", nat)
        form.addRow("科目代號", crow)
        form.addRow("科目名稱", self.name)
        form.addRow("科目類別", self.category)
        form.addRow("幣別", self.currency)
        form.addRow("期初餘額", self.opening)
        form.addRow("期初日期", self.opening_date)
        form.addRow("每月預算", self.budget)
        form.addRow("稅務歸類", self.tax)
        self.root.addLayout(form)
        self.hint = QLabel()
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        self.root.addWidget(self.hint)
        self.root.addWidget(self.msg)

        bar = QHBoxLayout()
        bar.addStretch()
        cancel = button("取消")
        cancel.clicked.connect(self.reject)
        ok = button("儲存", "Primary")
        ok.setDefault(True)
        ok.clicked.connect(self.save)
        bar.addWidget(cancel)
        bar.addWidget(ok)
        self.root.addLayout(bar)

        if category:
            self.radios[category["kind"]].setChecked(True)
            for rb in self.radios.values():
                rb.setEnabled(False)
            self.name.setText(category["name"])
            self.code.setText(category["code"])
            self.budget.setValue(category["budget"] or None)
            self.tax.setCurrentIndex(max(0, self.tax.findData(category["tax_tag"])))
        else:
            self.radios[nature or "asset"].setChecked(True)
        self.name.setFocus()

    def nature(self) -> str:
        return next(k for k, rb in self.radios.items() if rb.isChecked())

    def _set_row_visible(self, widget, visible: bool) -> None:
        self.form.setRowVisible(widget, visible)

    def _nature_changed(self) -> None:
        n = self.nature()
        acc = n in ("asset", "liability")
        if acc:
            cur = self.category.currentText()
            cats = ASSET_CATEGORIES if n == "asset" else LIABILITY_CATEGORIES
            self.category.blockSignals(True)
            self.category.clear()
            self.category.addItems(cats)
            self.category.setCurrentText(cur if cur in cats else cats[0])
            self.category.blockSignals(False)
        for w in (self.category, self.currency, self.opening, self.opening_date):
            self._set_row_visible(w, acc and not self.edit_cat)
        self._set_row_visible(self.budget, n == "expense")
        self._set_row_visible(self.tax, n in ("income", "expense"))
        if n in ("income", "expense"):
            cur = self.tax.currentData()
            self.tax.clear()
            for tag in (INCOME_TAX_TAGS if n == "income" else EXPENSE_TAX_TAGS):
                self.tax.addItem(TAX_TAGS[tag], tag)
            self.tax.setCurrentIndex(max(0, self.tax.findData(cur)))
        self.form.labelForField(self.opening).setText("期初餘額" if n == "asset" else "期初欠款")
        self._update_code()

    def _update_code(self) -> None:
        if self.edit_cat:
            return
        n = self.nature()
        cat = self.category.currentText().strip()
        prefix = self.db.code_prefix(n, cat)
        suggestion = self.db.next_code(prefix)
        if not self.code.text().strip() or self.code.text().strip() == self._auto:
            self.code.setText(suggestion)
        self._auto = suggestion
        group = {"11": "流動資產", "12": "非流動資產", "21": "流動負債", "22": "非流動負債",
                 "41": "收入", "51": "費用"}[prefix]
        self.code_hint.setText(f"建議 {suggestion}（{prefix} {group}）")
        if n == "asset" and cat in INVESTMENT_CATEGORIES:
            self.hint.setText(INVEST_HINT)
        elif n in ("asset", "liability"):
            self.hint.setText("資產、負債科目會出現在「帳戶管理」與資產負債表；"
                              "流動或非流動依科目類別自動判斷。")
        else:
            self.hint.setText("收入、費用科目會出現在收支損益表，記帳時可直接選用。")

    def save(self) -> None:
        n = self.nature()
        name = self.name.text().strip()
        code = self.code.text().strip()
        try:
            if self.edit_cat:
                if not name:
                    raise ValueError("請輸入科目名稱")
                dup = self.db.find_category(n, name)
                if dup and dup["id"] != self.edit_cat["id"]:
                    raise ValueError(f"已有同名的{NATURE_LABELS[n]}科目「{name}」")
                fields = {"name": name, "tax_tag": self.tax.currentData() or ""}
                if code != self.edit_cat["code"]:
                    fields["code"] = code
                if n == "expense":
                    fields["budget"] = max(0.0, self.budget.value() or 0)
                self.db.update_category(self.edit_cat["id"], **fields)
            elif n in ("asset", "liability"):
                if (self.opening.value() or 0) < 0:
                    raise ValueError("期初金額請輸入正數")
                aid = self.db.add_account(
                    name, n, self.category.currentText().strip() or ("其他資產" if n == "asset" else "其他負債"),
                    currency=self.currency.currentData(), rate=1.0,
                    opening_balance=self.opening.value() or 0,
                    opening_date=iso(self.opening_date.date()), code=code)
                self.created_key = ("account", aid)
            else:
                cid = self.db.add_category(name, n, budget=self.budget.value() or 0 if n == "expense" else 0,
                                           tax_tag=self.tax.currentData() or "", code=code)
                self.created_key = ("category", cid)
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已{'更新' if self.edit_cat else '新增'}會計科目：{code} {name}")
        self.accept()


class ChartOfAccountsDialog(BaseDialog):
    """完整會計科目表（依代號排列，分組小計標題）。"""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("會計科目表", parent, width=980)
        self.ctx = ctx
        self.db = ctx.db
        self.setMinimumHeight(680)
        top = QHBoxLayout()
        intro = QLabel("資產 1、負債 2、權益 3、收入 4、費用 5、業外損益 7。"
                       "按兩下科目可修改；新增的科目可立即用於記帳與複式分錄。")
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        top.addWidget(intro, 1)
        self.show_arch = QCheckBox("顯示已封存／隱藏的科目")
        self.show_arch.toggled.connect(self.load)
        top.addWidget(self.show_arch)
        self.root.addLayout(top)
        base = ctx.base
        self.table = DataTable([
            Column("科目代號", lambda r: r.get("code", ""), align="center", width=110,
                   color=lambda r: C.primary if r.get("_section") else C.muted),
            Column("會計科目", lambda r: r["name"] + ("（已封存）" if r.get("archived") else ""),
                   stretch=True, color=lambda r: C.primary if r.get("_section") else
                   (C.faint if r.get("archived") else None)),
            Column("科目類別", lambda r: r.get("label", ""), width=240, color=lambda r: C.muted),
            Column(f"餘額／本年累計（{base}）", lambda r: "" if r.get("amount") is None
                   else fmt_num(r["amount"], base), align="right", width=240),
        ], sortable=False)
        self.table.setAlternatingRowColors(False)
        self.table.rowActivated.connect(self.edit)
        self.root.addWidget(self.table, 1)
        self.root.addWidget(self.msg)

        bar = QHBoxLayout()
        add = button("新增會計科目", "Primary", "plus")
        add.clicked.connect(self.add)
        edit = button("修改", icon="edit")
        edit.clicked.connect(lambda: self.edit(self.table.current_row()))
        arch = button("封存／取消封存", icon="archive")
        arch.clicked.connect(self.toggle_archive)
        bar.addWidget(add)
        bar.addWidget(edit)
        bar.addWidget(arch)
        bar.addStretch()
        close = button("關閉")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        self.root.addLayout(bar)
        self.load()

    def load(self) -> None:
        arch = self.show_arch.isChecked()
        chart = self.db.chart_of_accounts(include_archived=arch)
        bal = {a["id"]: a["base_value"] for a in self.db.account_summaries(include_archived=True)}
        y0 = dt.date.today().replace(month=1, day=1).isoformat()
        today = dt.date.today().isoformat()
        ytd = {}
        for kind in ("income", "expense"):
            for c in self.db.category_totals(y0, today, kind):
                ytd[c["id"]] = c["total"]
        cats = {c["id"]: c for c in self.db.list_categories(include_archived=True)}
        rows: list[dict] = []

        def section(code: str, name: str) -> None:
            rows.append({"code": code, "name": name, "_section": True, "_bold": True,
                         "_bg": C.primary_soft})

        def sub(name: str) -> None:
            rows.append({"code": "", "name": name, "_bold": True, "_bg": C.surface_alt})

        def add_rows(items: list[dict]) -> None:
            for a in items:
                kind, ident = a["key"]
                r = {"code": a["code"], "name": "　" + a["name"], "key": a["key"],
                     "archived": a["archived"]}
                if kind == "account":
                    r["label"] = a["category"] + ("・可連結投資" if a["investment"] else "")
                    v = bal.get(ident, 0.0)
                    r["amount"] = v if a["kind"] == "asset" else -v
                elif kind == "category":
                    c = cats[ident]
                    r["label"] = TAX_TAGS.get(c["tax_tag"], "") if c["tax_tag"] else ""
                    r["amount"] = ytd.get(ident, 0.0)
                else:
                    r["label"] = "系統科目"
                rows.append(r)

        accs = [a for a in chart if a["key"][0] == "account"]
        section("1", "資產")
        for label, kind, current in (("流動資產", "asset", True), ("非流動資產", "asset", False)):
            sub(label)
            add_rows([a for a in accs if a["kind"] == kind and a["current"] == current])
        section("2", "負債")
        for label, kind, current in (("流動負債", "liability", True), ("非流動負債", "liability", False)):
            sub(label)
            add_rows([a for a in accs if a["kind"] == kind and a["current"] == current])
        section("3", "權益")
        rows.append({"code": EQUITY_CODE, "name": "　" + EQUITY_ACCOUNT, "label": "系統科目",
                     "key": ("special", "opening")})
        add_rows([a for a in chart if a["key"] == ("special", "equity")])
        section("4", "收入")
        add_rows([a for a in chart if a["kind"] == "income"])
        section("5", "費用")
        add_rows([a for a in chart if a["kind"] == "expense"])
        section("7", "業外損益")
        add_rows([a for a in chart if a["kind"] == "special" and SPECIALS[a["key"][1]][2] == "業外損益"])
        self.table.set_rows(rows)

    def add(self) -> None:
        if SubjectDialog(self.ctx, parent=self).exec():
            self.load()

    def edit(self, row: dict | None) -> None:
        if not row or not row.get("key"):
            if row is None:
                info(self, "請先點選一個會計科目。")
            return
        kind, ident = row["key"]
        if kind == "special":
            info(self, "這是系統科目，由程式自動使用（例如評價損益、兌換損益），不需要也不能修改。")
            return
        if kind == "account":
            from .dialogs import AccountDialog
            dlg = AccountDialog(self.ctx, self.db.get_account(ident), self)
        else:
            dlg = SubjectDialog(self.ctx, category=self.db.get_category(ident), parent=self)
        if dlg.exec():
            self.load()

    def toggle_archive(self) -> None:
        row = self.table.current_row()
        if not row or not row.get("key") or row["key"][0] == "special":
            info(self, "請先點選一個可封存的科目（系統科目不可封存）。")
            return
        kind, ident = row["key"]
        if kind == "account":
            acc = self.db.get_account(ident)
            if not acc["archived"] and abs(row.get("amount") or 0) >= 0.005:
                info(self, "此科目仍有餘額，請先將餘額轉出再封存。")
                return
            self.db.update_account(ident, archived=0 if acc["archived"] else 1)
        else:
            c = self.db.get_category(ident)
            self.db.update_category(ident, archived=0 if c["archived"] else 1)
        self.ctx.changed()
        self.load()
