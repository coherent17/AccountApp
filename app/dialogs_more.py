"""進階視窗：複式分錄、作廢、修改紀錄、定期交易、銀行對帳、匯入、附件。"""

from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDialog,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .context import AppContext
from .database import INVESTMENT_CATEGORIES, TYPE_LABELS, fmt_shares, voucher_no
from .dialogs import BaseDialog, fill_account_combo, open_path
from .investments import Investments
from .theme import C, fmt_date, fmt_money, fmt_num, icon
from .widgets import (AmountEdit, Column, DataTable, ask, button, error, info, iso,
                      make_date_edit, section_title)


def _key_str(key: tuple) -> str:
    return f"{key[0]}:{key[1]}"


def _parse_key(s: str) -> dict:
    kind, _, val = s.partition(":")
    if kind == "account":
        return {"account_id": int(val)}
    if kind == "category":
        return {"category_id": int(val)}
    return {"special": val}


# ====================================================================== 複式分錄
class JournalDialog(BaseDialog):
    """複式傳票：可輸入多行借貸，借貸平衡才能儲存。"""

    TEMPLATES = [
        ("（選擇常用範本）", []),
        ("房貸繳款（本金＋利息）", [("debit", "liability:房屋貸款", "本金"),
                                ("debit", "category:expense:房貸利息", "利息"),
                                ("credit", "asset:銀行存款", "")]),
        ("年繳保費（保單價值＋保險費）", [("debit", "asset:保險", "保單價值增加"),
                                    ("debit", "category:expense:保險費", "危險保費"),
                                    ("credit", "asset:銀行存款", "")]),
        ("退休金入帳（扣除健保費等）", [("debit", "asset:銀行存款", "實際入帳"),
                                   ("debit", "category:expense:保險費", "代扣健保費"),
                                   ("credit", "category:income:退休金", "應領金額")]),
        ("定存到期（本金＋利息）", [("debit", "asset:銀行存款", ""),
                                ("credit", "asset:定期存款", "本金"),
                                ("credit", "category:income:利息", "利息")]),
        ("一筆付款分攤多個費用", [("debit", "category:expense:餐飲", ""),
                              ("debit", "category:expense:日常用品", ""),
                              ("credit", "asset:現金", "")]),
        ("買進股票（借 短期投資／貸 銀行存款）", [("debit", "asset:短期投資", ""),
                                          ("credit", "asset:銀行存款", "")]),
        ("賣出股票（借 銀行存款／貸 短期投資）", [("debit", "asset:銀行存款", "實收價款"),
                                          ("credit", "asset:短期投資", "")]),
        ("淨值調整（補登漏記資產）", [("debit", "asset:", ""), ("credit", "special:equity", "")]),
    ]

    def __init__(self, ctx: AppContext, txn: dict | None = None, prefill: list[dict] | None = None,
                 date: str | None = None, note: str = "", parent=None):
        super().__init__("編輯分錄" if txn else "複式分錄（傳票）", parent, width=1200)
        self.ctx = ctx
        self.db = ctx.db
        self.inv = Investments(ctx.db)
        self.txn = txn
        self.saved = False
        self._load_chart()
        self.readonly = bool(txn and (txn["source"].startswith("inv:") or txn["void"]))

        top = QGridLayout()
        top.setHorizontalSpacing(12)
        self.date = make_date_edit(txn["date"] if txn else date)
        self.note = QLineEdit(txn["note"] if txn else note)
        self.note.setPlaceholderText("摘要，例如：房貸繳款 10 月")
        self.template = QComboBox()
        for name, _ in self.TEMPLATES:
            self.template.addItem(name)
        self.template.activated.connect(self.apply_template)
        top.addWidget(self.field_label("日期"), 0, 0)
        top.addWidget(self.date, 0, 1)
        top.addWidget(self.field_label("範本"), 0, 2)
        top.addWidget(self.template, 0, 3)
        top.addWidget(self.field_label("摘要"), 1, 0)
        top.addWidget(self.note, 1, 1, 1, 3)
        top.setColumnStretch(1, 1)
        top.setColumnStretch(3, 1)
        if txn:
            v = QLabel(f"傳票號碼：{voucher_no(txn['id'])}")
            v.setObjectName("Hint")
            top.addWidget(v, 2, 0, 1, 4)
        self.root.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["會計科目", "借方金額", "貸方金額", "投資標的／股數", "行備註"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(50)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, w in ((1, 140), (2, 140), (3, 300), (4, 150)):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, w)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(300)
        self.root.addWidget(self.table)

        tools = QHBoxLayout()
        add = button("新增一行", icon=icon("plus"))
        add.clicked.connect(lambda: self.add_row())
        rem = button("刪除選取行", icon=icon("trash"))
        rem.clicked.connect(self.remove_row)
        bal = button("自動平衡差額", icon=icon("refresh"),
                     tooltip="把借貸差額自動填入最後一行空白金額")
        bal.clicked.connect(self.auto_balance)
        subj = button("新增會計科目", "Link", icon("plus"))
        subj.clicked.connect(self.new_subject)
        tools.addWidget(add)
        tools.addWidget(rem)
        tools.addWidget(bal)
        tools.addWidget(subj)
        tools.addStretch()
        self.tot = QLabel()
        self.tot.setStyleSheet("font-weight:700;")
        tools.addWidget(self.tot)
        self.root.addLayout(tools)
        self.inv_info = QLabel()
        self.inv_info.setWordWrap(True)
        self.inv_info.setStyleSheet(f"color:{C.adjust}; background:{C.adjust_soft};"
                                    "padding:8px 12px; border-radius:8px;")
        self.inv_info.setVisible(False)
        self.root.addWidget(self.inv_info)
        hint = QLabel("借方：資產增加、費用發生、負債減少；貸方：資產減少、收入發生、負債增加。"
                      "外幣帳戶請以新台幣（本位幣）金額輸入，系統會依匯率換算。"
                      "投資科目（短期投資、長期投資等）請選擇投資標的並填股數，系統會依股價自動評價。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.root.addWidget(self.msg)

        bar = QHBoxLayout()
        if txn and not self.readonly:
            void = button("作廢這張傳票", "Danger", icon("trash", C.expense))
            void.clicked.connect(self.void)
            bar.addWidget(void)
        bar.addStretch()
        cancel = button("關閉" if self.readonly else "取消")
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        if not self.readonly:
            ok = button("儲存", "Primary")
            ok.setDefault(True)
            ok.clicked.connect(self.save)
            bar.addWidget(ok)
        self.root.addLayout(bar)

        if txn:
            for ln in self.db.get_lines(txn["id"]):
                key = ("account", ln["account_id"]) if ln["account_id"] else \
                    ("category", ln["category_id"]) if ln["category_id"] else ("special", ln["special"])
                self.add_row(key, ln["debit"], ln["credit"], ln["memo"], ln["security_id"], ln["shares"])
        elif prefill:
            for p in prefill:
                self.add_row(p.get("key"), p.get("debit"), p.get("credit"), p.get("memo", ""),
                             p.get("security_id"), p.get("shares"))
        while self.table.rowCount() < 3:
            self.add_row()
        if self.readonly:
            self.table.setEnabled(False)
            for w in (self.date, self.note, self.template):
                w.setEnabled(False)
            why = "此傳票已作廢。" if txn["void"] else "此傳票由「投資管理」自動產生，請到投資管理修改交易。"
            self.show_error(why)
        self.update_totals()

    # ------------------------------------------------------------------
    def _load_chart(self) -> None:
        self.chart = self.db.chart_of_accounts()
        self.chart_by_key = {_key_str(a["key"]): a for a in self.chart}

    def _fill_combo(self, cb: QComboBox, key_str: str) -> None:
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("", "")
        for a in self.chart:
            cb.addItem(f"{a['code']}　{a['name']}（{a['group']}）", _key_str(a["key"]))
        cb.setCurrentIndex(max(0, cb.findData(key_str)) if key_str else 0)
        cb.lineEdit().setCursorPosition(0)
        cb.blockSignals(False)

    def _combo(self, key: tuple | None) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        cb.addItem("", "")
        for a in self.chart:
            cb.addItem(f"{a['code']}　{a['name']}（{a['group']}）", _key_str(a["key"]))
        comp = cb.completer()
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        if key:
            i = cb.findData(_key_str(key))
            cb.setCurrentIndex(max(0, i))
        cb.lineEdit().setPlaceholderText("輸入代號或名稱搜尋…")
        return cb

    def add_row(self, key=None, debit=None, credit=None, memo: str = "", security_id=None,
                shares=None) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        cb = self._combo(key)
        self.table.setCellWidget(r, 0, cb)
        for col, val in ((1, debit), (2, credit)):
            ed = AmountEdit()
            ed.setStyleSheet("font-size: inherit; font-weight: 400;")
            ed.setObjectName("")
            if val:
                ed.setValue(val)
            ed.valueChanged.connect(self.update_totals)
            self.table.setCellWidget(r, col, ed)
        cell = QWidget()
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(2, 0, 2, 0)
        cl.setSpacing(6)
        sec = QComboBox()
        sec.setMinimumWidth(150)
        sh = AmountEdit(decimals=4)
        sh.setStyleSheet("font-size: inherit; font-weight: 400;")
        sh.setObjectName("")
        sh.setPlaceholderText("股數")
        sh.setFixedWidth(84)
        if shares:
            sh.setValue(shares)
        cl.addWidget(sec, 1)
        cl.addWidget(sh)
        cell.sec, cell.shares = sec, sh
        self.table.setCellWidget(r, 3, cell)
        m = QLineEdit(memo or "")
        self.table.setCellWidget(r, 4, m)
        cb.currentIndexChanged.connect(lambda _=0, c=cell, b=cb: self._refresh_sec(c, b))
        cb.currentIndexChanged.connect(lambda _=0, b=cb: b.lineEdit().setCursorPosition(0))
        cb.lineEdit().setCursorPosition(0)
        sec.activated.connect(lambda _=0, c=cell, b=cb: self._sec_chosen(c, b))
        sh.valueChanged.connect(self._update_inv_info)
        self._refresh_sec(cell, cb, security_id)

    def _row_account(self, cb: QComboBox) -> dict | None:
        a = self.chart_by_key.get(cb.currentData() or "")
        return a if a and a["key"][0] == "account" else None

    def _refresh_sec(self, cell: QWidget, cb: QComboBox, select: int | None = None) -> None:
        """會計科目為投資科目時，列出其投資標的供連結。"""
        a = self._row_account(cb)
        sec, sh = cell.sec, cell.shares
        keep = select if select is not None else sec.currentData()
        if keep == "new":
            keep = None
        sec.blockSignals(True)
        sec.clear()
        on = bool(a and a["investment"])
        if on:
            sec.addItem("（不連結標的）", None)
            for s in self.inv.list_securities(a["key"][1]):
                sec.addItem(f"{s['code']} {s['name']}".strip(), s["id"])
            sec.addItem("＋ 新增投資標的…", "new")
            sec.setCurrentIndex(max(0, sec.findData(keep)) if keep else 0)
        else:
            sec.addItem("—", None)
        sec.blockSignals(False)
        sec.setEnabled(on and not self.readonly)
        sh.setEnabled(on and not self.readonly and sec.currentData() not in (None, "new"))
        if not sh.isEnabled():
            sh.setValue(None)
        self._update_inv_info()

    def _sec_chosen(self, cell: QWidget, cb: QComboBox) -> None:
        if cell.sec.currentData() == "new":
            from .dialogs_invest import SecurityDialog
            a = self._row_account(cb)
            dlg = SecurityDialog(self.ctx, account_id=a["key"][1] if a else None, parent=self)
            ok = dlg.exec()
            self._load_chart()
            self._refresh_sec(cell, cb, getattr(dlg, "new_id", None) if ok else None)
            if ok:
                cell.shares.setFocus()
            return
        cell.shares.setEnabled(cell.sec.currentData() is not None and not self.readonly)
        if cell.shares.isEnabled():
            cell.shares.setFocus()
        else:
            cell.shares.setValue(None)
        self._update_inv_info()

    def _update_inv_info(self) -> None:
        """顯示連結標的目前持股與平均成本，方便輸入賣出成本。"""
        if not hasattr(self, "inv_info"):
            return
        parts = []
        for r in range(self.table.rowCount()):
            cell = self.table.cellWidget(r, 3)
            sid = cell.sec.currentData() if cell else None
            if not isinstance(sid, int):
                continue
            st = self.inv.replay(sid)
            s = self.inv.get_security(sid)
            if st["shares"]:
                parts.append(f"{s['code']} {s['name']}：目前持股 {fmt_shares(st['shares'])} 股，"
                             f"平均成本 {st['avg_cost']:,.2f}，帳面成本 {fmt_money(st['cost'], s['currency'])}")
            else:
                parts.append(f"{s['code']} {s['name']}：目前無持股")
        self.inv_info.setVisible(bool(parts))
        if parts:
            self.inv_info.setText("投資連結　" + "；".join(dict.fromkeys(parts)) +
                                  "。賣出時請貸記投資科目，系統會迴轉未實現評價損益，"
                                  "並依平均成本自動調整處分投資損益。")

    def new_subject(self) -> None:
        from .dialogs_chart import SubjectDialog
        dlg = SubjectDialog(self.ctx, parent=self)
        if not dlg.exec() or not dlg.created_key:
            return
        self._load_chart()
        new_key = _key_str(dlg.created_key)
        placed = False
        for r in range(self.table.rowCount()):
            cb = self.table.cellWidget(r, 0)
            cur = cb.currentData() or ""
            if not cur and not placed:
                cur, placed = new_key, True
            self._fill_combo(cb, cur)
            self._refresh_sec(self.table.cellWidget(r, 3), cb)
        if not placed:
            self.add_row(dlg.created_key)

    def remove_row(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for r in rows:
            self.table.removeRow(r)
        self.update_totals()

    def _resolve_template_key(self, spec: str):
        kind, _, rest = spec.partition(":")
        if kind == "special":
            return ("special", rest)
        if kind == "category":
            k, _, name = rest.partition(":")
            c = self.db.find_category(k, name)
            return ("category", c["id"]) if c else None
        accs = self.db.list_accounts()
        for a in accs:
            if a["kind"] == kind and (not rest or a["category"] == rest):
                return ("account", a["id"])
        if rest in INVESTMENT_CATEGORIES:
            for a in accs:
                if a["kind"] == "asset" and a["category"] in INVESTMENT_CATEGORIES:
                    return ("account", a["id"])
        return None

    def apply_template(self, idx: int) -> None:
        _, spec = self.TEMPLATES[idx]
        if not spec:
            return
        self.table.setRowCount(0)
        for side, key, memo in spec:
            self.add_row(self._resolve_template_key(key), memo=memo)
        if not self.note.text():
            self.note.setText(self.TEMPLATES[idx][0].split("（")[0])
        self.update_totals()

    def collect(self) -> list[dict]:
        lines = []
        for r in range(self.table.rowCount()):
            key = self.table.cellWidget(r, 0).currentData()
            d = self.table.cellWidget(r, 1).value() or 0
            c = self.table.cellWidget(r, 2).value() or 0
            memo = self.table.cellWidget(r, 4).text()
            if not key and not d and not c:
                continue
            if not key:
                raise ValueError(f"第 {r + 1} 行尚未選擇會計科目")
            item = _parse_key(key)
            item.update({"debit": d, "credit": c, "memo": memo})
            cell = self.table.cellWidget(r, 3)
            sid = cell.sec.currentData()
            if isinstance(sid, int) and (d or c):
                item["security_id"] = sid
                item["shares"] = cell.shares.value() or 0
                if item["shares"] <= 0:
                    raise ValueError(f"第 {r + 1} 行已選擇投資標的，請輸入股數")
            lines.append(item)
        return lines

    def _unlinked_investment_rows(self, lines: list[dict]) -> list[str]:
        """投資科目已有標的、但這一行沒有連結標的（金額將不會自動評價）。"""
        names = []
        for ln in lines:
            aid = ln.get("account_id")
            if aid and not ln.get("security_id") and self.inv.list_securities(aid):
                names.append(self.db.get_account(aid)["name"])
        return names

    def update_totals(self) -> None:
        d = c = 0.0
        for r in range(self.table.rowCount()):
            w1, w2 = self.table.cellWidget(r, 1), self.table.cellWidget(r, 2)
            d += (w1.value() or 0) if w1 else 0
            c += (w2.value() or 0) if w2 else 0
        diff = round(d - c, 2)
        base = self.ctx.base
        ok = abs(diff) < 0.005 and d > 0
        self.tot.setText(f"借方合計 {fmt_money(d, base)}　貸方合計 {fmt_money(c, base)}　"
                         + ("✓ 借貸平衡" if ok else f"差額 {fmt_money(diff, base)}"))
        self.tot.setStyleSheet(f"font-weight:700; color:{C.income if ok else C.expense};")

    def auto_balance(self) -> None:
        d = c = 0.0
        for r in range(self.table.rowCount()):
            d += self.table.cellWidget(r, 1).value() or 0
            c += self.table.cellWidget(r, 2).value() or 0
        diff = round(d - c, 2)
        if abs(diff) < 0.005:
            return
        for r in reversed(range(self.table.rowCount())):
            w1, w2 = self.table.cellWidget(r, 1), self.table.cellWidget(r, 2)
            if not w1.value() and not w2.value():
                (w2 if diff > 0 else w1).setValue(abs(diff))
                return
        self.add_row()
        r = self.table.rowCount() - 1
        (self.table.cellWidget(r, 2) if diff > 0 else self.table.cellWidget(r, 1)).setValue(abs(diff))

    def save(self) -> None:
        try:
            lines = self.collect()
            loose = self._unlinked_investment_rows(lines)
            if loose and not ask(self, f"「{'、'.join(dict.fromkeys(loose))}」已有投資標的，"
                                       "但這張分錄沒有選擇標的與股數，金額將不會計入持股、也不會自動評價。\n\n"
                                       "確定要這樣儲存嗎？", yes="仍要儲存", no="回去選擇標的"):
                return
            if self.txn:
                self.db.update_journal(self.txn["id"], iso(self.date.date()), self.note.text(), lines)
            else:
                self.db.add_journal(iso(self.date.date()), self.note.text(), lines)
        except ValueError as e:
            self.show_error(str(e))
            return
        self.saved = True
        self.ctx.changed()
        self.ctx.toast.emit("分錄已儲存，借貸平衡 ✓")
        self.accept()

    def void(self) -> None:
        reason = ask_void_reason(self)
        if reason is None:
            return
        try:
            self.db.void_transactions([self.txn["id"]], reason)
        except ValueError as e:
            self.show_error(str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit("傳票已作廢")
        self.accept()


# ====================================================================== 作廢
class VoidDialog(BaseDialog):
    REASONS = ["輸入錯誤", "重複輸入", "交易取消", "金額錯誤，將重新輸入", "其他"]

    def __init__(self, parent=None, count: int = 1):
        super().__init__("作廢傳票", parent, width=480)
        t = QLabel(f"確定要作廢{'這' if count == 1 else f'這 {count} '}張傳票嗎？")
        t.setObjectName("SectionTitle")
        d = QLabel("作廢後不再計入任何帳戶與報表，但會保留在帳上並留下修改紀錄，可隨時「取消作廢」。")
        d.setObjectName("Hint")
        d.setWordWrap(True)
        self.reason = QComboBox()
        self.reason.setEditable(True)
        self.reason.addItems(self.REASONS)
        self.root.addWidget(t)
        self.root.addWidget(d)
        f = QFormLayout()
        f.addRow("作廢原因", self.reason)
        self.root.addLayout(f)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        ok = button("作廢", "Expense")
        ok.clicked.connect(self.accept)
        bar.addWidget(c)
        bar.addWidget(ok)
        self.root.addLayout(bar)


def ask_void_reason(parent, count: int = 1) -> str | None:
    dlg = VoidDialog(parent, count)
    if dlg.exec():
        return dlg.reason.currentText().strip() or "作廢"
    return None


# ====================================================================== 修改紀錄
class AuditDialog(BaseDialog):
    def __init__(self, ctx: AppContext, txn_id: int | None = None, parent=None):
        super().__init__("修改紀錄（稽核軌跡）", parent, width=1000)
        self.db = ctx.db
        self.txn_id = txn_id
        head = QHBoxLayout()
        head.addWidget(section_title(f"{voucher_no(txn_id)} 的修改紀錄" if txn_id else "所有修改紀錄"))
        head.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜尋傳票號碼、動作或內容…")
        self.search.setMinimumWidth(280)
        self.search.textChanged.connect(self.reload)
        head.addWidget(self.search)
        self.root.addLayout(head)
        self.table = DataTable([
            Column("時間", lambda r: r["at"].replace("T", " ").replace("-", "/"), width=170),
            Column("動作", lambda r: r["action"], align="center", width=110,
                   color=lambda r: {"作廢": C.expense, "刪除": C.expense, "修改": C.adjust,
                                    "迴轉": C.adjust, "取消作廢": C.income}.get(r["action"])),
            Column("傳票號碼", lambda r: r["voucher"], align="center", width=110),
            Column("內容", lambda r: _detail_text(r), stretch=True),
        ], sortable=False)
        self.table.setMinimumHeight(460)
        self.root.addWidget(self.table)
        note = QLabel("修改紀錄由系統自動保存，無法刪除或修改，可作為帳務稽核之依據。")
        note.setObjectName("Hint")
        self.root.addWidget(note)
        bar = QHBoxLayout()
        bar.addStretch()
        close = button("關閉", "Primary")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        self.root.addLayout(bar)
        self.reload()

    def reload(self) -> None:
        rows = self.db.list_audit(self.txn_id, limit=3000)
        k = self.search.text().strip()
        if k:
            rows = [r for r in rows if k in r["voucher"] or k in r["action"] or k in r["summary"]
                    or k in r["detail"]]
        self.table.set_rows(rows)


def _detail_text(r: dict) -> str:
    import json
    text = r["summary"]
    if r["detail"]:
        try:
            d = json.loads(r["detail"])
            extra = "；".join(f"{k}：{v}" for k, v in d.items() if v)
            if extra:
                text += f"　〔{extra}〕"
        except ValueError:
            pass
    return text


# ====================================================================== 定期交易
FREQ_LABELS = {"monthly": "每月", "quarterly": "每季", "yearly": "每年"}


class RecurringEditDialog(BaseDialog):
    def __init__(self, ctx: AppContext, rec: dict | None = None, from_txn: dict | None = None,
                 parent=None):
        super().__init__("編輯定期交易" if rec else "新增定期交易", parent, width=600)
        self.ctx = ctx
        self.db = ctx.db
        self.rec = rec
        data = rec["data"] if rec else (from_txn or {})
        f = QFormLayout()
        f.setVerticalSpacing(10)
        self.name = QLineEdit(rec["name"] if rec else (data.get("note") or ""))
        self.name.setPlaceholderText("例如：月退休金、水電費、保險費")
        self.type = QComboBox()
        for k in ("expense", "income", "transfer"):
            self.type.addItem(TYPE_LABELS[k], k)
        self.type.setCurrentIndex(max(0, self.type.findData(data.get("type", "expense"))))
        self.account = QComboBox()
        fill_account_combo(self.account, ctx, data.get("account_id"), show_balance=False)
        self.to_account = QComboBox()
        fill_account_combo(self.to_account, ctx, data.get("to_account_id"), show_balance=False)
        self.category = QComboBox()
        self.amount = AmountEdit()
        if data.get("amount"):
            self.amount.setValue(data["amount"])
        self.note = QLineEdit(data.get("note") or "")
        self.freq = QComboBox()
        for k, v in FREQ_LABELS.items():
            self.freq.addItem(v, k)
        self.freq.setCurrentIndex(max(0, self.freq.findData(rec["freq"] if rec else "monthly")))
        self.day = QSpinBox()
        self.day.setRange(1, 31)
        self.day.setSuffix(" 日")
        self.day.setValue(rec["day"] if rec else int((data.get("date") or dt.date.today().isoformat())[8:]))
        self.start = make_date_edit(rec["start_date"] if rec else dt.date.today().isoformat())
        self.has_end = QCheckBox("設定結束日期")
        self.end = make_date_edit(rec["end_date"] if rec and rec["end_date"] else
                                  (dt.date.today() + dt.timedelta(days=365)).isoformat())
        self.has_end.setChecked(bool(rec and rec["end_date"]))
        self.end.setEnabled(self.has_end.isChecked())
        self.has_end.toggled.connect(self.end.setEnabled)
        self.active = QCheckBox("啟用")
        self.active.setChecked(bool(rec["active"]) if rec else True)
        self.lbl_to = QLabel("轉入帳戶")
        self.lbl_cat = QLabel("分類")
        f.addRow("名稱", self.name)
        f.addRow("類型", self.type)
        f.addRow("帳戶", self.account)
        f.addRow(self.lbl_to, self.to_account)
        f.addRow(self.lbl_cat, self.category)
        f.addRow("金額", self.amount)
        f.addRow("說明", self.note)
        rowf = QHBoxLayout()
        rowf.addWidget(self.freq)
        rowf.addWidget(self.day)
        rowf.addStretch()
        f.addRow("頻率", rowf)
        f.addRow("開始日期", self.start)
        rowe = QHBoxLayout()
        rowe.addWidget(self.has_end)
        rowe.addWidget(self.end, 1)
        f.addRow("結束", rowe)
        f.addRow("", self.active)
        self.root.addLayout(f)
        hint = QLabel("到期時程式會提醒您確認入帳（金額可在入帳前修改），不會自動記帳。"
                      "每季、每年依開始日期的月份推算。")
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
        self.type.currentIndexChanged.connect(self._type_changed)
        self._type_changed()
        if data.get("category_id"):
            self.category.setCurrentIndex(max(0, self.category.findData(data["category_id"])))

    def _type_changed(self) -> None:
        t = self.type.currentData()
        self.lbl_to.setVisible(t == "transfer")
        self.to_account.setVisible(t == "transfer")
        self.lbl_cat.setVisible(t != "transfer")
        self.category.setVisible(t != "transfer")
        cur = self.category.currentData()
        self.category.clear()
        if t != "transfer":
            for c in self.db.list_categories(t):
                self.category.addItem(c["name"], c["id"])
            i = self.category.findData(cur)
            if i >= 0:
                self.category.setCurrentIndex(i)

    def save(self) -> None:
        name = self.name.text().strip()
        amt = self.amount.value()
        t = self.type.currentData()
        if not name:
            self.show_error("請輸入名稱")
            return
        if not amt or amt <= 0:
            self.show_error("請輸入金額")
            return
        data = {"type": t, "account_id": self.account.currentData(), "amount": amt,
                "note": self.note.text().strip() or name}
        if t == "transfer":
            data["to_account_id"] = self.to_account.currentData()
            if data["to_account_id"] == data["account_id"]:
                self.show_error("轉出與轉入帳戶不可相同")
                return
        else:
            data["category_id"] = self.category.currentData()
        self.db.save_recurring(self.rec["id"] if self.rec else None, name, data,
                               self.freq.currentData(), self.day.value(), iso(self.start.date()),
                               iso(self.end.date()) if self.has_end.isChecked() else "",
                               self.active.isChecked())
        self.ctx.changed()
        self.ctx.toast.emit(f"已儲存定期交易：{name}")
        self.accept()


class RecurringManagerDialog(BaseDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("定期交易", parent, width=980)
        self.ctx = ctx
        self.db = ctx.db
        intro = QLabel("每月固定的收入或支出（退休金、水電、保費、房租…）可設為定期交易，"
                       "到期時程式會提醒您一鍵入帳。")
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        self.root.addWidget(intro)
        accs = {a["id"]: a["name"] for a in self.db.list_accounts(include_archived=True)}
        cats = {c["id"]: c["name"] for c in self.db.list_categories(include_archived=True)}
        today = dt.date.today()

        def next_date(r):
            ds = self.db.recurring_dates(r, (today + dt.timedelta(days=400)).isoformat())
            return fmt_date(ds[0]) if ds else "—"

        self.table = DataTable([
            Column("名稱", lambda r: r["name"], bold=True, width=170),
            Column("類型", lambda r: TYPE_LABELS[r["data"]["type"]], align="center", width=80),
            Column("帳戶", lambda r: accs.get(r["data"].get("account_id"), ""), width=150),
            Column("分類／轉入", lambda r: cats.get(r["data"].get("category_id"), "") or
                   accs.get(r["data"].get("to_account_id"), ""), width=130),
            Column("金額", lambda r: fmt_num(r["data"]["amount"], ctx.base), align="right", width=110),
            Column("頻率", lambda r: f"{FREQ_LABELS[r['freq']]} {r['day']} 日", align="center", width=110),
            Column("下次日期", next_date, align="center", width=120),
            Column("狀態", lambda r: "啟用" if r["active"] else "停用", align="center", width=70,
                   color=lambda r: C.income if r["active"] else C.faint),
        ], sortable=False)
        self.table.setMinimumHeight(360)
        self.table.rowActivated.connect(self.edit)
        self.root.addWidget(self.table)
        bar = QHBoxLayout()
        for text, kind, ic, fn in (("新增", "Primary", "plus", self.add),
                                   ("編輯", None, "edit", lambda: self.edit(self.table.current_row())),
                                   ("啟用／停用", None, "eye", self.toggle),
                                   ("刪除", "Danger", "trash", self.delete),
                                   ("檢查到期項目", None, "refresh", self.check_due)):
            b = button(text, kind, icon(ic, "#FFFFFF" if kind == "Primary" else
                                        (C.expense if kind == "Danger" else C.text)))
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        close = button("關閉")
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        self.root.addLayout(bar)
        self.reload()

    def reload(self) -> None:
        self.table.set_rows(self.db.list_recurring())

    def add(self) -> None:
        if RecurringEditDialog(self.ctx, parent=self).exec():
            self.reload()

    def edit(self, row) -> None:
        if row and RecurringEditDialog(self.ctx, rec=row, parent=self).exec():
            self.reload()

    def toggle(self) -> None:
        r = self.table.current_row()
        if r:
            self.db.save_recurring(r["id"], r["name"], r["data"], r["freq"], r["day"],
                                   r["start_date"], r["end_date"], not r["active"])
            self.reload()

    def delete(self) -> None:
        r = self.table.current_row()
        if r and ask(self, f"確定要刪除定期交易「{r['name']}」嗎？\n（已入帳的紀錄不受影響）",
                     yes="刪除", danger=True):
            self.db.delete_recurring(r["id"])
            self.reload()

    def check_due(self) -> None:
        due = self.db.due_recurring()
        if not due:
            info(self, "目前沒有到期的定期交易。")
            return
        DueRecurringDialog(self.ctx, due, self).exec()
        self.reload()


class DueRecurringDialog(BaseDialog):
    def __init__(self, ctx: AppContext, due: list, parent=None):
        super().__init__("定期交易到期提醒", parent, width=860)
        self.ctx = ctx
        self.db = ctx.db
        self.due = due
        t = QLabel(f"有 {len(due)} 筆定期交易已到期，請確認是否入帳：")
        t.setObjectName("SectionTitle")
        self.root.addWidget(t)
        hint = QLabel("金額若與實際不同（例如水電費），可直接修改後再入帳。")
        hint.setObjectName("Hint")
        self.root.addWidget(hint)
        self.table = QTableWidget(len(due), 5)
        self.table.setHorizontalHeaderLabels(["入帳", "日期", "名稱", "類型", "金額"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for i, w in ((0, 70), (1, 130), (3, 90), (4, 170)):
            self.table.setColumnWidth(i, w)
        self.checks = []
        self.amounts = []
        for r, (rec, date) in enumerate(due):
            cb = QCheckBox()
            cb.setChecked(True)
            wrap = QWidget()
            lay = QHBoxLayout(wrap)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(cb)
            self.table.setCellWidget(r, 0, wrap)
            self.checks.append(cb)
            for col, text in ((1, fmt_date(date)), (2, rec["name"]), (3, TYPE_LABELS[rec["data"]["type"]])):
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, col, it)
            amt = AmountEdit()
            amt.setObjectName("")
            amt.setValue(rec["data"]["amount"])
            self.table.setCellWidget(r, 4, amt)
            self.amounts.append(amt)
        self.table.setMinimumHeight(min(8, len(due)) * 48 + 50)
        self.root.addWidget(self.table)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        later = button("稍後再說")
        later.clicked.connect(self.reject)
        skip = button("略過所選（本期不入帳）")
        skip.clicked.connect(self.skip)
        post = button("入帳所選", "Primary")
        post.clicked.connect(self.post)
        bar.addWidget(later)
        bar.addStretch()
        bar.addWidget(skip)
        bar.addWidget(post)
        self.root.addLayout(bar)

    def post(self) -> None:
        n = 0
        errors = []
        for (rec, date), cb, amt in zip(self.due, self.checks, self.amounts):
            if cb.isChecked():
                try:
                    self.db.post_recurring(rec, date, amt.value())
                    n += 1
                except ValueError as e:
                    errors.append(f"{rec['name']}：{e}")
        self.ctx.changed()
        if errors:
            error(self, "以下項目無法入帳：\n" + "\n".join(errors))
        self.ctx.toast.emit(f"已入帳 {n} 筆定期交易")
        self.accept()

    def skip(self) -> None:
        for (rec, date), cb in zip(self.due, self.checks):
            if cb.isChecked():
                self.db.skip_recurring(rec, date)
        self.ctx.changed()
        self.accept()


# ====================================================================== 銀行對帳
class ReconcileDialog(BaseDialog):
    def __init__(self, ctx: AppContext, account_id: int | None = None, parent=None):
        super().__init__("銀行對帳", parent, width=980)
        self.ctx = ctx
        self.db = ctx.db
        intro = QLabel("拿出銀行存摺或對帳單，輸入對帳單日期與期末餘額，再勾選存摺上已出現的每一筆紀錄。"
                       "差額為 0 即對帳完成；未勾選的就是「未達帳項」。")
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        self.root.addWidget(intro)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.account = QComboBox()
        fill_account_combo(self.account, ctx, account_id, show_balance=False)
        self.stmt_date = make_date_edit()
        self.stmt_bal = AmountEdit()
        self.stmt_bal.setObjectName("")
        g.addWidget(self.field_label("帳戶"), 0, 0)
        g.addWidget(self.account, 0, 1)
        g.addWidget(self.field_label("對帳單日期"), 0, 2)
        g.addWidget(self.stmt_date, 0, 3)
        g.addWidget(self.field_label("對帳單期末餘額"), 1, 0)
        g.addWidget(self.stmt_bal, 1, 1)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        self.root.addLayout(g)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["✓", "日期", "傳票號碼", "摘要", "增加（存入）", "減少（提出）"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for i, w in ((0, 50), (1, 120), (2, 110), (4, 140), (5, 140)):
            self.table.setColumnWidth(i, w)
        self.table.setMinimumHeight(340)
        self.table.itemChanged.connect(lambda _: self.update_sum())
        self.root.addWidget(self.table)

        info_row = QHBoxLayout()
        self.lbl = QLabel()
        self.lbl.setStyleSheet("font-weight:700;")
        sel_all = button("全部勾選", "Link")
        sel_all.clicked.connect(lambda: self._check_all(True))
        sel_none = button("全部取消", "Link")
        sel_none.clicked.connect(lambda: self._check_all(False))
        info_row.addWidget(sel_all)
        info_row.addWidget(sel_none)
        info_row.addStretch()
        info_row.addWidget(self.lbl)
        self.root.addLayout(info_row)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        hist = button("對帳紀錄", icon=icon("list"))
        hist.clicked.connect(self.history)
        bar.addWidget(hist)
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        self.ok = button("完成對帳", "Primary")
        self.ok.clicked.connect(self.finish)
        bar.addWidget(c)
        bar.addWidget(self.ok)
        self.root.addLayout(bar)
        self.account.currentIndexChanged.connect(self.load)
        self.stmt_date.dateChanged.connect(self.load)
        self.stmt_bal.valueChanged.connect(self.update_sum)
        self.items: list[dict] = []
        self.load()

    def load(self) -> None:
        aid = self.account.currentData()
        if aid is None:
            return
        self.acc = self.db.get_account(aid)
        self.items = self.db.recon_candidates(aid, iso(self.stmt_date.date()))
        self.cleared = self.db.cleared_balance(aid)
        cur = self.acc["currency"]
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        for r, it in enumerate(self.items):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, chk)
            vals = [fmt_date(it["date"]), it["voucher"], it["note"] or TYPE_LABELS[it["type"]],
                    fmt_num(it["effect"], cur) if it["effect"] > 0 else "",
                    fmt_num(-it["effect"], cur) if it["effect"] < 0 else ""]
            for col, v in enumerate(vals, 1):
                x = QTableWidgetItem(v)
                x.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if col >= 4:
                    x.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, col, x)
        self.table.blockSignals(False)
        if self.stmt_bal.value() is None:
            book = next((a["balance"] for a in self.db.account_summaries(iso(self.stmt_date.date()), True)
                         if a["id"] == aid), 0.0)
            self.stmt_bal.setValue(book)
        self.update_sum()

    def _check_all(self, on: bool) -> None:
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _checked(self) -> list[dict]:
        return [it for r, it in enumerate(self.items)
                if self.table.item(r, 0) and self.table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def update_sum(self) -> None:
        if not hasattr(self, "acc"):
            return
        cur = self.acc["currency"]
        s = sum(i["effect"] for i in self._checked())
        after = self.cleared + s
        stmt = self.stmt_bal.value() or 0
        diff = round(stmt - after, 2)
        ok = abs(diff) < 0.005
        self.lbl.setText(f"上次對帳餘額 {fmt_money(self.cleared, cur)} ＋ 勾選 {fmt_money(s, cur)}"
                         f" ＝ {fmt_money(after, cur)}　｜　差額 {fmt_money(diff, cur)}"
                         + ("　✓" if ok else ""))
        self.lbl.setStyleSheet(f"font-weight:700; color:{C.income if ok else C.expense};")

    def finish(self) -> None:
        cur = self.acc["currency"]
        s = sum(i["effect"] for i in self._checked())
        diff = round((self.stmt_bal.value() or 0) - (self.cleared + s), 2)
        if abs(diff) >= 0.005 and not ask(
                self, f"仍有差額 {fmt_money(diff, cur)}，可能有漏記或金額不符。\n確定仍要儲存這次對帳嗎？",
                yes="仍要儲存"):
            return
        ids = [i["txn_id"] for i in self._checked()]
        self.db.save_reconciliation(self.acc["id"], iso(self.stmt_date.date()),
                                    self.stmt_bal.value() or 0, ids)
        self.ctx.changed()
        self.ctx.toast.emit(f"「{self.acc['name']}」對帳完成，核銷 {len(ids)} 筆")
        self.accept()

    def history(self) -> None:
        rows = self.db.list_reconciliations(self.acc["id"])
        dlg = BaseDialog("對帳紀錄", self, width=600)
        t = DataTable([
            Column("對帳單日期", lambda r: fmt_date(r["statement_date"]), width=140),
            Column("對帳單餘額", lambda r: fmt_num(r["statement_balance"], self.acc["currency"]),
                   align="right", width=150),
            Column("核銷筆數", lambda r: r["n"], align="right", width=100),
            Column("對帳時間", lambda r: r["created_at"].replace("T", " "), stretch=True),
        ], sortable=False)
        t.set_rows(rows)
        t.setMinimumHeight(300)
        dlg.root.addWidget(t)
        b = button("關閉", "Primary")
        b.clicked.connect(dlg.accept)
        dlg.root.addWidget(b, alignment=Qt.AlignmentFlag.AlignRight)
        dlg.exec()


# ====================================================================== 匯入
class ImportDialog(BaseDialog):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("匯入 Excel／CSV", parent, width=1080)
        self.ctx = ctx
        self.db = ctx.db
        self.rows: list[list] = []
        self.items: list[dict] = []
        top = QHBoxLayout()
        pick = button("選擇檔案…", "Primary", icon("folder", "#FFFFFF"))
        pick.clicked.connect(self.pick)
        tmpl = button("下載匯入範本", icon=icon("excel"))
        tmpl.clicked.connect(self.template)
        self.file_lbl = QLabel("尚未選擇檔案（支援 .xlsx 與 .csv，也可以直接匯入本程式匯出的報表）")
        self.file_lbl.setObjectName("Hint")
        top.addWidget(pick)
        top.addWidget(tmpl)
        top.addWidget(self.file_lbl, 1)
        self.root.addLayout(top)

        from .importer import FIELDS
        g = QGridLayout()
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        self.maps: dict[str, QComboBox] = {}
        for i, (key, label) in enumerate(FIELDS.items()):
            cb = QComboBox()
            cb.currentIndexChanged.connect(self.preview)
            self.maps[key] = cb
            g.addWidget(QLabel(label), i // 4 * 2, i % 4)
            g.addWidget(cb, i // 4 * 2 + 1, i % 4)
        self.root.addWidget(section_title("欄位對應"))
        self.root.addLayout(g)
        opt = QHBoxLayout()
        opt.addWidget(QLabel("帳戶欄空白時使用"))
        self.default_acc = QComboBox()
        fill_account_combo(self.default_acc, ctx, None, show_balance=False)
        self.default_acc.currentIndexChanged.connect(self.preview)
        opt.addWidget(self.default_acc)
        opt.addSpacing(10)
        opt.addWidget(QLabel("只有一個金額欄時"))
        self.sign = QComboBox()
        self.sign.addItem("正數為支出、負數為收入", "expense_positive")
        self.sign.addItem("正數為收入、負數為支出", "income_positive")
        self.sign.currentIndexChanged.connect(self.preview)
        opt.addWidget(self.sign)
        self.create_cat = QCheckBox("找不到的分類自動新增")
        self.create_cat.setChecked(True)
        self.create_cat.toggled.connect(self.preview)
        opt.addWidget(self.create_cat)
        opt.addStretch()
        self.root.addLayout(opt)

        self.table = DataTable([
            Column("列", lambda r: r["row"], align="right", width=55),
            Column("狀態", lambda r: r["error"] or ("新分類" if r["new_category"] else "可匯入"),
                   width=170, color=lambda r: C.expense if r["error"] else
                   (C.adjust if r["new_category"] else C.income)),
            Column("日期", lambda r: fmt_date(r["date"] or ""), width=110),
            Column("類型", lambda r: TYPE_LABELS.get(r["type"], ""), align="center", width=70),
            Column("分類", lambda r: r["category_name"], width=120),
            Column("帳戶", lambda r: r["account_name"] or "（預設帳戶）", width=130),
            Column("說明", lambda r: r["note"], stretch=True),
            Column("金額", lambda r: fmt_num(r["amount"] or 0, ctx.base), align="right", width=110),
        ], sortable=False)
        self.table.setMinimumHeight(300)
        self.root.addWidget(self.table)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-weight:700;")
        self.root.addWidget(self.summary)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(self.reject)
        self.go = button("開始匯入", "Income")
        self.go.clicked.connect(self.do_import)
        self.go.setEnabled(False)
        bar.addWidget(c)
        bar.addWidget(self.go)
        self.root.addLayout(bar)

    def template(self) -> None:
        from .importer import write_template
        path, _ = QFileDialog.getSaveFileName(self, "儲存匯入範本",
                                              os.path.join(self.ctx.folder, "匯入範本.xlsx"),
                                              "Excel 活頁簿 (*.xlsx)")
        if path:
            write_template(path)
            open_path(path)

    def pick(self) -> None:
        from .importer import find_header, guess_mapping, read_table
        path, _ = QFileDialog.getOpenFileName(self, "選擇要匯入的檔案", self.ctx.folder,
                                              "Excel 或 CSV (*.xlsx *.xlsm *.csv)")
        if not path:
            return
        try:
            self.rows = read_table(path)
        except Exception as e:  # noqa: BLE001
            error(self, f"無法讀取檔案：{e}")
            return
        self.header = find_header(self.rows)
        head = self.rows[self.header] if self.rows else []
        mapping = guess_mapping(head)
        for key, cb in self.maps.items():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("（不使用）", None)
            for i, h in enumerate(head):
                cb.addItem(f"第 {i + 1} 欄：{h if h is not None else ''}", i)
            idx = cb.findData(mapping.get(key))
            cb.setCurrentIndex(idx if mapping.get(key) is not None and idx >= 0 else 0)
            cb.blockSignals(False)
        self.file_lbl.setText(os.path.basename(path) + f"　（標題列：第 {self.header + 1} 列）")
        self.preview()

    def preview(self) -> None:
        if not self.rows:
            return
        from .importer import build_rows
        mapping = {k: cb.currentData() for k, cb in self.maps.items()}
        self.items = build_rows(self.db, self.rows, self.header, mapping, self.default_acc.currentData(),
                                self.sign.currentData(), self.create_cat.isChecked())
        self.table.set_rows(self.items[:500])
        ok = sum(1 for i in self.items if not i["error"])
        bad = len(self.items) - ok
        self.summary.setText(f"共 {len(self.items)} 筆：可匯入 {ok} 筆，無法匯入 {bad} 筆"
                             + ("（只顯示前 500 筆）" if len(self.items) > 500 else ""))
        self.go.setEnabled(ok > 0)

    def do_import(self) -> None:
        from .importer import do_import
        ok = sum(1 for i in self.items if not i["error"])
        if not ask(self, f"確定要匯入 {ok} 筆紀錄嗎？\n匯入前會自動備份帳本。", yes="匯入"):
            return
        self.db.backup_to(os.path.join(self.ctx.backup_dir,
                                       f"匯入前備份_{dt.datetime.now():%Y%m%d_%H%M%S}.db"))
        n, skipped = do_import(self.db, self.items)
        self.ctx.changed()
        self.ctx.toast.emit(f"匯入完成：{n} 筆")
        info(self, f"匯入完成！成功 {n} 筆，略過 {skipped} 筆。\n如需復原，可從「自動備份」資料夾的「匯入前備份」還原。")
        self.accept()


# ====================================================================== 附件
class AttachmentsPanel(QWidget):
    """傳票附件清單（新傳票先暫存，儲存後才寫入）。"""

    def __init__(self, ctx: AppContext, txn_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.txn_id = txn_id
        self.pending: list[str] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setMaximumHeight(84)
        self.list.itemDoubleClicked.connect(self.open)
        col = QVBoxLayout()
        add = button("新增附件", icon=icon("plus"))
        add.clicked.connect(self.add)
        rem = button("移除", icon=icon("trash"))
        rem.clicked.connect(self.remove)
        col.addWidget(add)
        col.addWidget(rem)
        lay.addWidget(self.list, 1)
        lay.addLayout(col)
        self.reload()

    def reload(self) -> None:
        self.list.clear()
        if self.txn_id:
            for a in self.ctx.db.list_attachments(self.txn_id):
                it = QListWidgetItem(icon("copy"), a["name"])
                it.setData(Qt.ItemDataRole.UserRole, ("saved", a["id"], a["path"]))
                self.list.addItem(it)
        for p in self.pending:
            it = QListWidgetItem(icon("plus"), os.path.basename(p) + "（儲存後加入）")
            it.setData(Qt.ItemDataRole.UserRole, ("pending", None, p))
            self.list.addItem(it)
        if not self.list.count():
            it = QListWidgetItem("可附上收據、帳單照片或 PDF（選填）")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)

    def add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇附件", os.path.expanduser("~"),
                                                "圖片或文件 (*.png *.jpg *.jpeg *.pdf *.heic *.xlsx *.docx);;所有檔案 (*)")
        if not paths:
            return
        if self.txn_id:
            for p in paths:
                self.ctx.db.add_attachment(self.txn_id, p, os.path.join(self.ctx.folder, "憑證附件"))
        else:
            self.pending += paths
        self.reload()

    def remove(self) -> None:
        it = self.list.currentItem()
        data = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not data:
            return
        if data[0] == "saved":
            self.ctx.db.remove_attachment(data[1])
        else:
            self.pending.remove(data[2])
        self.reload()

    def open(self, it) -> None:
        data = it.data(Qt.ItemDataRole.UserRole)
        if data and os.path.exists(data[2]):
            open_path(data[2])

    def commit(self, txn_id: int) -> None:
        for p in self.pending:
            try:
                self.ctx.db.add_attachment(txn_id, p, os.path.join(self.ctx.folder, "憑證附件"))
            except OSError:
                pass
        self.pending = []
