"""各式輸入視窗：記帳、帳戶、餘額更新、歡迎與匯出。"""

from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import QDate, QStringListModel, Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QCompleter, QDialog,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                               QVBoxLayout, QWidget)

from .context import AppContext
from .database import ASSET_CATEGORIES, CURRENCIES, LIABILITY_CATEGORIES
from .theme import C, currency_name, decimals_for, fmt_money, icon
from .widgets import (AmountEdit, ChipGroup, button, error, iso, make_date_edit, qdate,
                      section_title)


class BaseDialog(QDialog):
    def __init__(self, title: str, parent=None, width: int = 560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(26, 22, 26, 22)
        self.root.setSpacing(14)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setVisible(False)

    def showEvent(self, e):
        super().showEvent(e)
        from .animations import fade_in_window
        fade_in_window(self)

    def show_error(self, text: str) -> None:
        self.msg.setStyleSheet(f"color:{C.expense}; background:{C.expense_soft};"
                               "padding:8px 12px; border-radius:8px;")
        self.msg.setText("⚠  " + text)
        self.msg.setVisible(True)

    def show_ok(self, text: str) -> None:
        self.msg.setStyleSheet(f"color:{C.income}; background:{C.income_soft};"
                               "padding:8px 12px; border-radius:8px;")
        self.msg.setText("✓  " + text)
        self.msg.setVisible(True)
        QTimer.singleShot(2500, lambda: self.msg.setVisible(False))

    def field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{C.muted}; font-weight:700;")
        return lbl


def fill_account_combo(combo: QComboBox, ctx: AppContext, selected: int | None = None,
                       exclude: int | None = None, show_balance: bool = True) -> None:
    combo.blockSignals(True)
    combo.clear()
    for acc in ctx.db.account_summaries():
        if acc["id"] == exclude:
            continue
        label = acc["name"]
        if show_balance:
            word = "欠款 " if acc["kind"] == "liability" else ""
            label += f"　（{word}{fmt_money(acc['balance'], acc['currency'])}）"
        combo.addItem(label, acc["id"])
    if selected is not None:
        i = combo.findData(selected)
        if i >= 0:
            combo.setCurrentIndex(i)
    combo.blockSignals(False)


# ====================================================================== 記帳
class TransactionDialog(BaseDialog):
    MODES = [("expense", "支出"), ("income", "收入"), ("transfer", "轉帳")]

    def __init__(self, ctx: AppContext, ttype: str = "expense", txn: dict | None = None,
                 account_id: int | None = None, parent=None, copy: bool = False):
        title = "編輯紀錄" if txn and not copy else "記一筆"
        super().__init__(title, parent, width=640)
        self.ctx = ctx
        self.db = ctx.db
        self.txn = None if copy else txn
        self.saved_any = False
        self.ttype = txn["type"] if txn else ttype
        accounts = {a["id"]: a for a in self.db.list_accounts(include_archived=True)}
        self.accounts = accounts

        # 類型切換
        self.seg_row = QHBoxLayout()
        self.seg_row.setSpacing(8)
        self.seg_group = QButtonGroup(self)
        self.seg_buttons = {}
        for key, label in self.MODES:
            b = QPushButton(label)
            b.setObjectName("Segment")
            b.setProperty("ttype", key)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self.seg_group.addButton(b)
            self.seg_buttons[key] = b
            self.seg_row.addWidget(b)
        if self.ttype == "adjust":
            adj = QLabel("餘額／市值調整")
            adj.setObjectName("SectionTitle")
            adj.setStyleSheet(f"color:{C.adjust};")
            self.root.addWidget(adj)
        else:
            self.root.addLayout(self.seg_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)

        self.date = make_date_edit(txn["date"] if txn else None)
        today_btn = button("今天", "Link")
        today_btn.clicked.connect(lambda: self.date.setDate(QDate.currentDate()))
        yday_btn = button("昨天", "Link")
        yday_btn.clicked.connect(lambda: self.date.setDate(QDate.currentDate().addDays(-1)))
        drow = QHBoxLayout()
        drow.addWidget(self.date, 1)
        drow.addWidget(today_btn)
        drow.addWidget(yday_btn)

        self.amount = AmountEdit(allow_negative=self.ttype == "adjust")
        self.amount.setMinimumHeight(52)
        self.cur_label = QLabel("")
        self.cur_label.setStyleSheet(f"color:{C.muted};")
        arow = QHBoxLayout()
        arow.addWidget(self.amount, 1)
        arow.addWidget(self.cur_label)

        self.account = QComboBox()
        self.account.setMinimumWidth(320)
        self.to_account = QComboBox()
        self.to_amount = AmountEdit()
        self.to_cur_label = QLabel("")
        self.to_cur_label.setStyleSheet(f"color:{C.muted};")
        trow = QHBoxLayout()
        trow.addWidget(self.to_amount, 1)
        trow.addWidget(self.to_cur_label)
        self.to_amount_wrap = QWidget()
        self.to_amount_wrap.setLayout(trow)
        trow.setContentsMargins(0, 0, 0, 0)

        self.chips = ChipGroup(columns=4)
        self.note = QLineEdit()
        self.note.setPlaceholderText("例如：市場買菜、全聯採買（可留空）")
        comp = QCompleter(QStringListModel(self.db.recent_notes()), self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.note.setCompleter(comp)

        self.lbl_amount = self.field_label("金額")
        self.lbl_account = self.field_label("帳戶")
        self.lbl_to_account = self.field_label("轉入帳戶")
        self.lbl_to_amount = self.field_label("轉入金額")
        self.lbl_cat = self.field_label("分類")
        r = 0
        grid.addWidget(self.field_label("日期"), r, 0)
        grid.addLayout(drow, r, 1)
        r += 1
        grid.addWidget(self.lbl_amount, r, 0)
        grid.addLayout(arow, r, 1)
        r += 1
        grid.addWidget(self.lbl_account, r, 0)
        grid.addWidget(self.account, r, 1)
        r += 1
        grid.addWidget(self.lbl_to_account, r, 0)
        grid.addWidget(self.to_account, r, 1)
        r += 1
        grid.addWidget(self.lbl_to_amount, r, 0)
        grid.addWidget(self.to_amount_wrap, r, 1)
        r += 1
        grid.addWidget(self.lbl_cat, r, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.chips, r, 1)
        r += 1
        grid.addWidget(self.field_label("說明"), r, 0)
        grid.addWidget(self.note, r, 1)
        r += 1
        from .dialogs_more import AttachmentsPanel
        self.attach = AttachmentsPanel(ctx, self.txn["id"] if self.txn else None)
        grid.addWidget(self.field_label("附件"), r, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.attach, r, 1)
        self.root.addLayout(grid)
        self.adjust_hint = QLabel("正數代表增加（例如股票上漲），負數代表減少（例如股票下跌）。")
        self.adjust_hint.setObjectName("Hint")
        self.adjust_hint.setVisible(self.ttype == "adjust")
        self.root.addWidget(self.adjust_hint)
        self.root.addWidget(self.msg)

        # 按鈕列
        bar = QHBoxLayout()
        if self.txn:
            del_btn = button("作廢這筆", "Danger", icon("trash", C.expense))
            del_btn.clicked.connect(self.delete)
            bar.addWidget(del_btn)
            hist = button("修改紀錄", "Link")
            hist.clicked.connect(self.history)
            bar.addWidget(hist)
            pr = button("列印傳票", "Link")
            pr.clicked.connect(self.print_voucher)
            bar.addWidget(pr)
        elif self.ttype != "adjust":
            split = button("改用複式分錄（分割多個科目）", "Link",
                           tooltip="一筆付款分攤到多個分類，或需要自行輸入借貸時使用")
            split.clicked.connect(self.to_journal)
            bar.addWidget(split)
        bar.addStretch()
        cancel = button("取消")
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        if not self.txn:
            again = button("儲存並再記一筆")
            again.clicked.connect(lambda: self.save(keep_open=True))
            bar.addWidget(again)
        ok = button("儲存", "Primary")
        ok.setDefault(True)
        ok.clicked.connect(lambda: self.save(keep_open=False))
        bar.addWidget(ok)
        self.root.addLayout(bar)

        # 初始值
        last = self.db.get_setting("last_account_id")
        default_acc = account_id or (txn["account_id"] if txn else (int(last) if last.isdigit() else None))
        fill_account_combo(self.account, ctx, default_acc)
        self.account.currentIndexChanged.connect(self._on_account_changed)
        self.to_account.currentIndexChanged.connect(self._update_currency)
        self.amount.valueChanged.connect(self._sync_to_amount)
        self.set_mode(self.ttype, initial=True)
        if txn:
            self.amount.setValue(txn["amount"])
            if txn.get("to_account_id"):
                i = self.to_account.findData(txn["to_account_id"])
                if i >= 0:
                    self.to_account.setCurrentIndex(i)
                self.to_amount.setValue(txn.get("to_amount"))
            if txn.get("category_id"):
                self.chips.set_value(txn["category_id"])
            self.note.setText(txn.get("note", ""))
        self._update_currency()
        self.amount.setFocus()

    # ------------------------------------------------------------------
    def set_mode(self, mode: str, initial: bool = False) -> None:
        self.ttype = mode
        if mode in self.seg_buttons:
            self.seg_buttons[mode].setChecked(True)
        is_transfer = mode == "transfer"
        has_cat = mode in ("income", "expense")
        self.lbl_account.setText("轉出帳戶" if is_transfer else ("收入存入" if mode == "income" else "帳戶"))
        for w in (self.lbl_to_account, self.to_account):
            w.setVisible(is_transfer)
        self.lbl_cat.setVisible(has_cat)
        self.chips.setVisible(has_cat)
        if has_cat:
            prev = self.chips.value()
            cats = self.db.list_categories(mode)
            self.chips.set_items([(c["id"], c["name"]) for c in cats])
            if prev is not None:
                self.chips.set_value(prev)
        if is_transfer:
            fill_account_combo(self.to_account, self.ctx,
                               self.to_account.currentData(), exclude=self.account.currentData())
        self.lbl_amount.setText({"expense": "支出金額", "income": "收入金額",
                                 "transfer": "轉出金額", "adjust": "調整金額"}[mode])
        self._update_currency()
        if not initial:
            self.adjustSize()

    def _on_account_changed(self) -> None:
        if self.ttype == "transfer":
            fill_account_combo(self.to_account, self.ctx, self.to_account.currentData(),
                               exclude=self.account.currentData())
        self._update_currency()

    def _cur(self, combo: QComboBox) -> str:
        acc = self.accounts.get(combo.currentData())
        return acc["currency"] if acc else self.ctx.base

    def _update_currency(self) -> None:
        c1 = self._cur(self.account)
        self.cur_label.setText(currency_name(c1))
        self.amount.decimals = decimals_for(c1)
        show_to_amount = False
        if self.ttype == "transfer" and self.to_account.currentData() is not None:
            c2 = self._cur(self.to_account)
            self.to_cur_label.setText(currency_name(c2))
            show_to_amount = c1 != c2
        self.lbl_to_amount.setVisible(show_to_amount)
        self.to_amount_wrap.setVisible(show_to_amount)
        self._sync_to_amount()

    def _sync_to_amount(self) -> None:
        if self.to_amount_wrap.isVisible() and not self.to_amount.hasFocus() and not self.to_amount.text():
            a1 = self.accounts.get(self.account.currentData())
            a2 = self.accounts.get(self.to_account.currentData())
            v = self.amount.value()
            if a1 and a2 and v and a2["rate"]:
                self.to_amount.setPlaceholderText(f"約 {v * a1['rate'] / a2['rate']:,.2f}")

    def collect(self) -> dict:
        amount = self.amount.value()
        if amount is None:
            raise ValueError("請輸入金額（可輸入數字或算式）")
        data = {
            "date": iso(self.date.date()),
            "type": self.ttype,
            "account_id": self.account.currentData(),
            "amount": amount,
            "note": self.note.text(),
        }
        if self.account.currentData() is None:
            raise ValueError("請先到「帳戶管理」新增至少一個帳戶")
        if self.ttype in ("income", "expense"):
            data["category_id"] = self.chips.value()
            if data["category_id"] is None:
                raise ValueError("請點選一個分類")
        if self.ttype == "transfer":
            data["to_account_id"] = self.to_account.currentData()
            if self.to_amount_wrap.isVisible():
                v = self.to_amount.value()
                if v is None:
                    raise ValueError("兩個帳戶幣別不同，請輸入轉入金額")
                data["to_amount"] = v
            else:
                data["to_amount"] = amount
        return data

    def save(self, keep_open: bool) -> None:
        try:
            data = self.collect()
            if self.txn:
                self.db.update_transaction(self.txn["id"], **data)
            else:
                tid = self.db.add_transaction(**data)
                self.attach.commit(tid)
            self.db.set_setting("last_account_id", data["account_id"])
        except ValueError as e:
            self.show_error(str(e))
            return
        self.saved_any = True
        self.ctx.changed()
        label = {"expense": "支出", "income": "收入", "transfer": "轉帳"}.get(self.ttype, "紀錄")
        self.ctx.toast.emit(f"已{'更新' if self.txn else '儲存'}{label}：{self.amount.text()}")
        if keep_open:
            self.amount.clear()
            self.note.clear()
            self.to_amount.clear()
            self.attach.reload()
            fill_account_combo(self.account, self.ctx, data["account_id"])
            self.show_ok("已儲存，可以繼續記下一筆。")
            self.amount.setFocus()
        else:
            self.accept()

    def print_voucher(self) -> None:
        from .dialogs_print import print_voucher
        print_voucher(self.ctx, self.txn["id"], self)

    def delete(self) -> None:
        from .dialogs_more import ask_void_reason
        reason = ask_void_reason(self)
        if reason is None:
            return
        try:
            self.db.void_transactions([self.txn["id"]], reason)
        except ValueError as e:
            self.show_error(str(e))
            return
        self.saved_any = True
        self.ctx.changed()
        self.ctx.toast.emit("已作廢這筆紀錄（可在收支明細勾選「顯示已作廢」查看）")
        self.accept()

    def history(self) -> None:
        from .dialogs_more import AuditDialog
        AuditDialog(self.ctx, self.txn["id"], self).exec()

    def to_journal(self) -> None:
        """把目前輸入的內容帶到複式分錄視窗。"""
        from .dialogs_more import JournalDialog
        amt = self.amount.value() or None
        acc = self.account.currentData()
        prefill = []
        if self.ttype == "expense":
            prefill = [{"key": ("category", self.chips.value()) if self.chips.value() else None,
                        "debit": amt}, {"key": None}, {"key": ("account", acc) if acc else None,
                                                       "credit": amt}]
        elif self.ttype == "income":
            prefill = [{"key": ("account", acc) if acc else None, "debit": amt}, {"key": None},
                       {"key": ("category", self.chips.value()) if self.chips.value() else None,
                        "credit": amt}]
        else:
            to = self.to_account.currentData()
            prefill = [{"key": ("account", to) if to else None, "debit": amt},
                       {"key": ("account", acc) if acc else None, "credit": amt}]
        dlg = JournalDialog(self.ctx, prefill=prefill, date=iso(self.date.date()),
                            note=self.note.text(), parent=self.parentWidget())
        self.hide()
        if dlg.exec():
            self.saved_any = True
        self.done(QDialog.DialogCode.Accepted if self.saved_any else QDialog.DialogCode.Rejected)

    def done(self, r):
        if self.saved_any and r == QDialog.DialogCode.Rejected:
            r = QDialog.DialogCode.Accepted
        super().done(r)


def open_voucher(ctx: AppContext, txn_id: int, parent=None) -> bool:
    """依傳票類型開啟對應的編輯視窗。"""
    t = ctx.db.get_transaction(txn_id)
    if not t:
        return False
    if t["type"] == "journal":
        from .dialogs_more import JournalDialog
        return bool(JournalDialog(ctx, txn=t, parent=parent).exec())
    if t["void"]:
        from .widgets import info as _info
        _info(parent, f"此傳票已作廢（原因：{t['void_reason'] or '未填寫'}）。\n"
                      "如需恢復，請在收支明細按右鍵選「取消作廢」。")
        return False
    return bool(TransactionDialog(ctx, txn=t, parent=parent).exec())


# ====================================================================== 帳戶
class AccountDialog(BaseDialog):
    def __init__(self, ctx: AppContext, account: dict | None = None, parent=None):
        super().__init__("編輯帳戶" if account else "新增帳戶", parent, width=560)
        self.ctx = ctx
        self.account = account
        base = ctx.base

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.name = QLineEdit()
        self.name.setPlaceholderText("例如：郵局活儲、台銀定存、隨身現金")
        self.code = QLineEdit(account["code"] if account else "")
        self.code.setMaxLength(6)
        self.code.setPlaceholderText("3～6 位數字")
        self.code_hint = QLabel()
        self.code_hint.setObjectName("Hint")
        self._auto_code = ""
        code_row = QHBoxLayout()
        code_row.addWidget(self.code, 1)
        code_row.addWidget(self.code_hint)
        self.kind_asset = QRadioButton("資產（存款、投資、現金…）")
        self.kind_liab = QRadioButton("負債（信用卡、貸款…）")
        kind_row = QHBoxLayout()
        kind_row.addWidget(self.kind_asset)
        kind_row.addWidget(self.kind_liab)
        kind_row.addStretch()
        self.category = QComboBox()
        self.category.setEditable(True)
        self.currency = QComboBox()
        for code, (name, sym) in CURRENCIES.items():
            self.currency.addItem(f"{name}（{code}）", code)
        self.rate = QDoubleSpinBox()
        self.rate.setDecimals(4)
        self.rate.setRange(0.0001, 100000)
        self.rate.setValue(1)
        self.rate_label = QLabel("")
        self.rate_label.setObjectName("Hint")
        rate_row = QHBoxLayout()
        rate_row.addWidget(self.rate, 1)
        rate_row.addWidget(self.rate_label)
        self.opening = AmountEdit()
        self.opening_label = QLabel("期初餘額")
        self.opening_date = make_date_edit(account["opening_date"] if account else
                                           dt.date.today().replace(month=1, day=1).isoformat())
        self.note = QLineEdit()
        self.note.setPlaceholderText("可記錄帳號末四碼等（可留空）")
        self.has_maturity = QCheckBox("設定到期日（定存、債券、保單、貸款）")
        self.maturity = make_date_edit((dt.date.today() + dt.timedelta(days=365)).isoformat())
        self.maturity.setEnabled(False)
        self.has_maturity.toggled.connect(self.maturity.setEnabled)
        mrow = QHBoxLayout()
        mrow.addWidget(self.has_maturity)
        mrow.addWidget(self.maturity, 1)
        self.interest = QDoubleSpinBox()
        self.interest.setDecimals(3)
        self.interest.setRange(0, 100)
        self.interest.setSuffix(" %")

        form.addRow("帳戶名稱", self.name)
        form.addRow("性質", kind_row)
        form.addRow("類別", self.category)
        form.addRow("科目代號", code_row)
        form.addRow("幣別", self.currency)
        form.addRow("匯率", rate_row)
        form.addRow(self.opening_label, self.opening)
        form.addRow("期初日期", self.opening_date)
        form.addRow("到期", mrow)
        form.addRow("年利率", self.interest)
        form.addRow("備註", self.note)
        self.root.addWidget(section_title("帳戶資料"))
        self.root.addLayout(form)
        hint = QLabel("「期初餘額」請填入此帳戶在「期初日期」當天的金額，之後的收支會自動累計。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
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

        self.kind_asset.toggled.connect(self._kind_changed)
        self.currency.currentIndexChanged.connect(self._currency_changed)
        self.category.currentTextChanged.connect(lambda _: self._suggest_code())

        if account:
            self.name.setText(account["name"])
            (self.kind_asset if account["kind"] == "asset" else self.kind_liab).setChecked(True)
            self._kind_changed()
            self.category.setCurrentText(account["category"])
            self.currency.setCurrentIndex(max(0, self.currency.findData(account["currency"])))
            self.rate.setValue(account["rate"])
            self.opening.setValue(account["opening_balance"])
            self.note.setText(account["note"])
            if account.get("maturity_date"):
                self.has_maturity.setChecked(True)
                self.maturity.setDate(qdate(account["maturity_date"]))
            self.interest.setValue(account.get("interest_rate") or 0)
        else:
            self.kind_asset.setChecked(True)
            self._kind_changed()
            self.currency.setCurrentIndex(max(0, self.currency.findData(base)))
        self._currency_changed()
        self._suggest_code()

    def _suggest_code(self) -> None:
        """新帳戶依性質與類別建議代號；使用者自行輸入的代號不會被覆蓋。"""
        db = self.ctx.db
        kind = "asset" if self.kind_asset.isChecked() else "liability"
        prefix = db.code_prefix(kind, self.category.currentText().strip())
        group = {"11": "流動資產", "12": "非流動資產", "21": "流動負債", "22": "非流動負債"}[prefix]
        if self.account:
            self.code_hint.setText(f"{prefix} 開頭為{group}")
            return
        suggestion = db.next_code(prefix)
        if not self.code.text().strip() or self.code.text().strip() == self._auto_code:
            self.code.setText(suggestion)
        self._auto_code = suggestion
        self.code_hint.setText(f"建議 {suggestion}（{group}）")

    def _kind_changed(self) -> None:
        current = self.category.currentText()
        cats = ASSET_CATEGORIES if self.kind_asset.isChecked() else LIABILITY_CATEGORIES
        self.category.clear()
        self.category.addItems(cats)
        if current in cats:
            self.category.setCurrentText(current)
        self.opening_label.setText("期初餘額" if self.kind_asset.isChecked() else "期初欠款")
        if hasattr(self, "code_hint"):
            self._suggest_code()

    def _currency_changed(self) -> None:
        code = self.currency.currentData()
        base = self.ctx.base
        is_base = code == base
        self.rate.setVisible(not is_base)
        if is_base:
            self.rate.setValue(1)
            self.rate_label.setText("本位幣，不需匯率")
        else:
            self.rate_label.setText(f"1 {currency_name(code)} = ? {currency_name(base)}")
        self.opening.decimals = decimals_for(code)

    def save(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.show_error("請輸入帳戶名稱")
            return
        category = self.category.currentText().strip() or "其他資產"
        opening = self.opening.value() or 0.0
        if opening < 0:
            self.show_error("期初金額請輸入正數（負債請改選「負債」性質）")
            return
        fields = dict(
            name=name,
            kind="asset" if self.kind_asset.isChecked() else "liability",
            category=category,
            currency=self.currency.currentData(),
            rate=self.rate.value(),
            opening_balance=opening,
            opening_date=iso(self.opening_date.date()),
            note=self.note.text(),
            maturity_date=iso(self.maturity.date()) if self.has_maturity.isChecked() else "",
            interest_rate=self.interest.value(),
        )
        code = self.code.text().strip()
        try:
            if self.account:
                if code != self.account["code"]:
                    fields["code"] = code
                self.ctx.db.update_account(self.account["id"], **fields)
            else:
                self.new_id = self.ctx.db.add_account(**fields, code=code)
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已{'更新' if self.account else '新增'}帳戶：{name}")
        self.accept()


# ====================================================================== 餘額更新
class AdjustDialog(BaseDialog):
    def __init__(self, ctx: AppContext, account_id: int | None = None, parent=None):
        super().__init__("更新餘額／市值", parent, width=560)
        self.ctx = ctx
        self.db = ctx.db

        intro = QLabel("適用於股票、基金等市值會變動的資產，或帳戶實際餘額與帳本不符時。"
                       "輸入「目前實際金額」，系統會自動記錄差額。")
        intro.setWordWrap(True)
        intro.setObjectName("Hint")
        self.root.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        self.account = QComboBox()
        fill_account_combo(self.account, ctx, account_id, show_balance=False)
        self.date = make_date_edit()
        self.current = QLabel("—")
        self.current.setStyleSheet("font-weight:700;")
        self.new_value = AmountEdit()
        self.new_value.setMinimumHeight(52)
        self.diff = QLabel("—")
        self.diff.setStyleSheet("font-weight:700;")
        self.note = QLineEdit("市值更新")
        form.addRow("帳戶", self.account)
        form.addRow("日期", self.date)
        form.addRow("帳本目前金額", self.current)
        form.addRow("實際最新金額", self.new_value)
        form.addRow("差額", self.diff)
        form.addRow("說明", self.note)
        self.root.addLayout(form)
        self.root.addWidget(self.msg)

        bar = QHBoxLayout()
        bar.addStretch()
        cancel = button("取消")
        cancel.clicked.connect(self.reject)
        ok = button("儲存", "Adjust")
        ok.setDefault(True)
        ok.clicked.connect(self.save)
        bar.addWidget(cancel)
        bar.addWidget(ok)
        self.root.addLayout(bar)

        self.account.currentIndexChanged.connect(self.refresh)
        self.date.dateChanged.connect(self.refresh)
        self.new_value.valueChanged.connect(self.refresh)
        self.refresh()
        self.new_value.setFocus()

    def _acc(self) -> dict | None:
        aid = self.account.currentData()
        return self.db.get_account(aid) if aid else None

    def _current_display(self) -> float:
        acc = self._acc()
        if not acc:
            return 0.0
        signed = self.db.signed_balances(iso(self.date.date())).get(acc["id"], 0.0)
        return signed if acc["kind"] == "asset" else -signed

    def refresh(self) -> None:
        acc = self._acc()
        if not acc:
            return
        cur = self._current_display()
        self.new_value.decimals = decimals_for(acc["currency"])
        prefix = "欠款 " if acc["kind"] == "liability" else ""
        self.current.setText(prefix + fmt_money(cur, acc["currency"]))
        v = self.new_value.value()
        if v is None:
            self.diff.setText("—")
            self.diff.setStyleSheet("font-weight:700;")
            return
        d = v - cur
        self.diff.setText(fmt_money(d, acc["currency"], signed=True))
        good = d >= 0 if acc["kind"] == "asset" else d <= 0
        self.diff.setStyleSheet(f"font-weight:700; color:{C.income if good else C.expense};")

    def save(self) -> None:
        acc = self._acc()
        if not acc:
            self.show_error("請選擇帳戶")
            return
        v = self.new_value.value()
        if v is None:
            self.show_error("請輸入實際最新金額")
            return
        if self.db._q1("SELECT 1 FROM securities WHERE account_id = ? AND archived = 0", (acc["id"],)):
            self.show_error("此帳戶的持股由「投資管理」維護，請到投資管理使用「市價評價」，"
                            "選擇日期並輸入市價後產生評價分錄。")
            return
        delta_display = v - self._current_display()
        if abs(delta_display) < 0.005:
            self.show_error("金額與帳本相同，不需要調整。")
            return
        delta_signed = delta_display if acc["kind"] == "asset" else -delta_display
        try:
            self.db.add_transaction(date=iso(self.date.date()), type="adjust", account_id=acc["id"],
                                    amount=delta_signed, note=self.note.text())
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已更新「{acc['name']}」金額")
        self.accept()


# ====================================================================== 歡迎
class WelcomeDialog(BaseDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("歡迎使用我的理財帳本", parent, width=620)
        self.ctx = ctx
        self.choice = None
        title = QLabel("歡迎使用「我的理財帳本」")
        title.setObjectName("PageTitle")
        sub = QLabel("清楚掌握每一筆收支與整體資產，隨時匯出 Excel 報表。\n"
                     "所有資料都只存放在這台電腦上，安全又安心。")
        sub.setObjectName("PageSubtitle")
        sub.setWordWrap(True)
        self.root.addWidget(title)
        self.root.addWidget(sub)

        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setText("游媽媽")
        self.name.setPlaceholderText("例如：游媽媽")
        form.addRow("請問怎麼稱呼您？", self.name)
        self.root.addSpacing(6)
        self.root.addLayout(form)
        self.root.addSpacing(6)

        b1 = button("建立基本帳戶，馬上開始記帳", "Primary")
        b1.setMinimumHeight(54)
        b1.clicked.connect(lambda: self.finish("basic"))
        d1 = QLabel("會先建立「現金」與「銀行存款」兩個帳戶，之後可以再自行新增或修改。")
        d1.setObjectName("Hint")
        d1.setWordWrap(True)
        b2 = button("載入範例資料，先試用看看")
        b2.setMinimumHeight(48)
        b2.clicked.connect(lambda: self.finish("sample"))
        d2 = QLabel("試用後，在「總覽」頁最上方按「清除範例資料，開始正式記帳」即可一鍵清除。")
        d2.setObjectName("Hint")
        d2.setWordWrap(True)
        self.root.addWidget(b1)
        self.root.addWidget(d1)
        self.root.addSpacing(6)
        self.root.addWidget(b2)
        self.root.addWidget(d2)

    def finish(self, choice: str) -> None:
        self.choice = choice
        self.ctx.db.set_setting("owner_name", self.name.text().strip())
        self.accept()

    def reject(self) -> None:
        # 按 ✕ 或 Esc 關閉時也保留稱呼（程式仍會建立基本帳戶）
        self.ctx.db.set_setting("owner_name", self.name.text().strip())
        super().reject()


# ====================================================================== 匯出
class ExportDialog(BaseDialog):
    def __init__(self, ctx: AppContext, parent=None, start: str | None = None,
                 end: str | None = None):
        super().__init__("匯出 Excel 報表", parent, width=600)
        self.ctx = ctx
        today = dt.date.today()
        lo, hi = ctx.db.date_range()

        self.root.addWidget(section_title("選擇報表期間"))
        self.r_year = QRadioButton("指定年度")
        self.year = QComboBox()
        for y in range(max(int(hi[:4]), today.year), int(lo[:4]) - 1, -1):
            self.year.addItem(f"{y} 年（民國 {y - 1911} 年）", y)
        self.r_custom = QRadioButton("自訂期間")
        self.d1 = make_date_edit(start or today.replace(month=1, day=1).isoformat())
        self.d2 = make_date_edit(end or today.isoformat())
        self.r_all = QRadioButton("全部資料")
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        g.addWidget(self.r_year, 0, 0)
        g.addWidget(self.year, 0, 1)
        g.addWidget(self.r_custom, 1, 0)
        rng = QHBoxLayout()
        rng.addWidget(self.d1)
        rng.addWidget(QLabel("至"))
        rng.addWidget(self.d2)
        g.addLayout(rng, 1, 1)
        g.addWidget(self.r_all, 2, 0)
        g.setColumnStretch(1, 1)
        self.root.addLayout(g)
        (self.r_custom if start else self.r_year).setChecked(True)

        from .exporter import SHEET_INFO
        head = QHBoxLayout()
        head.addWidget(section_title("選擇要匯出的報表"))
        head.addStretch()
        for text, on in (("全選", True), ("全不選", False)):
            b = button(text, "Link")
            b.clicked.connect(lambda _=False, v=on: [c.setChecked(v) for c in self.sheet_boxes.values()])
            head.addWidget(b)
        self.root.addLayout(head)
        saved = ctx.db.get_json("export_sheets", None)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        self.sheet_boxes: dict[str, QCheckBox] = {}
        for i, (name, desc) in enumerate(SHEET_INFO):
            cb = QCheckBox(name)
            cb.setToolTip(desc)
            cb.setChecked(saved is None or name in saved)
            grid.addWidget(cb, i // 3, i % 3)
            self.sheet_boxes[name] = cb
        self.root.addLayout(grid)
        sheets = QLabel("合計欄位皆使用 Excel 公式，可直接在 Excel 內稽核與修改。"
                        "未勾選、但被其他報表公式引用的工作表（例如收支明細）會以隱藏工作表保留。")
        sheets.setObjectName("Hint")
        sheets.setWordWrap(True)
        self.root.addWidget(sheets)

        self.root.addWidget(section_title("存檔位置"))
        self.path = QLineEdit()
        browse = button("瀏覽…", icon=icon("folder"))
        browse.clicked.connect(self.browse)
        prow = QHBoxLayout()
        prow.addWidget(self.path, 1)
        prow.addWidget(browse)
        self.root.addLayout(prow)
        self.open_after = QCheckBox("匯出完成後自動開啟檔案")
        self.open_after.setChecked(True)
        self.root.addWidget(self.open_after)
        self.root.addWidget(self.msg)

        bar = QHBoxLayout()
        bar.addStretch()
        cancel = button("取消")
        cancel.clicked.connect(self.reject)
        ok = button("匯出", "Income", icon("download", "#FFFFFF"))
        ok.setDefault(True)
        ok.clicked.connect(self.do_export)
        bar.addWidget(cancel)
        bar.addWidget(ok)
        self.root.addLayout(bar)

        for w in (self.r_year, self.r_custom, self.r_all):
            w.toggled.connect(self._suggest_name)
        self.year.currentIndexChanged.connect(self._suggest_name)
        self.d1.dateChanged.connect(self._suggest_name)
        self.d2.dateChanged.connect(self._suggest_name)
        self._suggest_name()

    def period(self) -> tuple[str, str, str]:
        if self.r_year.isChecked():
            y = self.year.currentData()
            return f"{y}-01-01", f"{y}-12-31", f"{y}年度"
        if self.r_custom.isChecked():
            a, b = iso(self.d1.date()), iso(self.d2.date())
            if a > b:
                a, b = b, a
            return a, b, f"{a.replace('-', '')}-{b.replace('-', '')}"
        lo, hi = self.ctx.db.date_range()
        return lo, hi, "全部資料"

    def _suggest_name(self) -> None:
        _, _, tag = self.period()
        os.makedirs(self.ctx.export_dir, exist_ok=True)
        self.path.setText(os.path.join(self.ctx.export_dir, f"理財報表_{tag}.xlsx"))

    def browse(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "另存 Excel 報表", self.path.text(),
                                              "Excel 活頁簿 (*.xlsx)")
        if path:
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            self.path.setText(path)

    def do_export(self) -> None:
        from .exporter import export_workbook
        start, end, _ = self.period()
        path = self.path.text().strip()
        if not path:
            self.show_error("請選擇存檔位置")
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        chosen = [n for n, cb in self.sheet_boxes.items() if cb.isChecked()]
        if not chosen:
            self.show_error("請至少勾選一份報表")
            return
        self.ctx.db.set_json("export_sheets", chosen)
        try:
            export_workbook(self.ctx.db, path, start, end, chosen)
        except PermissionError:
            self.show_error("無法寫入檔案，可能檔案正在 Excel 中開啟。請先關閉該檔案後再試一次。")
            return
        except Exception as e:  # noqa: BLE001
            error(self, f"匯出失敗：{e}")
            return
        if self.open_after.isChecked():
            open_path(path)
        self.exported_path = path
        self.ctx.toast.emit("Excel 報表匯出完成")
        self.accept()


def open_path(path: str) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))

