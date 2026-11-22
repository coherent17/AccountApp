from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QWidget

from ..database import TYPE_LABELS, voucher_no
from ..dialogs import AdjustDialog, ExportDialog, TransactionDialog, open_voucher
from ..dialogs_more import (AuditDialog, ImportDialog, JournalDialog, RecurringEditDialog,
                            RecurringManagerDialog, ask_void_reason)
from ..theme import TYPE_COLORS, C, fmt_date, fmt_money, icon
from ..widgets import (PERIOD_PRESETS, Card, Column, DataTable, ResponsiveRow, button, error, info, iso,
                       make_date_edit, page_header, preset_range, qdate)
from .base import Page


def _signed(r: dict) -> float:
    return -r["amount"] if r["type"] == "expense" else r["amount"]


def _cat_text(r: dict) -> str:
    if r["category_name"]:
        return r["category_name"]
    if r["type"] == "transfer":
        return "帳戶間轉帳"
    return "未實現評價損益"


def _acc_text(r: dict) -> str:
    if r["type"] == "transfer":
        return f"{r['account_name']} → {r['to_account_name']}"
    return r["account_name"] or ""


def _amount_text(r: dict) -> str:
    if r["type"] == "journal":
        return fmt_money(r["amount"], r["currency"])
    text = fmt_money(_signed(r), r["currency"], signed=r["type"] != "transfer")
    if r["type"] == "transfer" and r["to_currency"] and r["to_currency"] != r["currency"]:
        text += f" → {fmt_money(r['to_amount'], r['to_currency'])}"
    return text


def _type_text(r: dict) -> str:
    if r["void"]:
        return "已作廢"
    if r["source"].startswith("inv:"):
        return "投資"
    return TYPE_LABELS[r["type"]]


def _note_text(r: dict) -> str:
    text = (f"〔作廢：{r['void_reason']}〕" if r["void"] else "") + r["note"]
    if r.get("tags"):        # 說明在前、標籤在後（欄寬不夠時省略的是標籤，不是說明）
        text += ("　" if text else "") + "　".join(f"#{t}" for t in r["tags"])
    return text


def _color(r: dict) -> str:
    if r["void"]:
        return C.faint
    return TYPE_COLORS.get(r["type"], (C.primary,))[0]



class TransactionsPage(Page):
    title = "收支明細"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, scroll=False, parent=parent)
        b = self.body
        head, hl = page_header("收支明細", "日記帳：逐筆記錄收入、支出、轉帳與分錄傳票")
        for text, kind, ttype, ic in (("記支出", "Expense", "expense", "minus"),
                                       ("記收入", "Income", "income", "plus"),
                                       ("轉帳", "Transfer", "transfer", "transfer")):
            btn = button(text, kind, ic)
            btn.setMinimumHeight(44)
            btn.clicked.connect(lambda _=False, t=ttype: self.new_txn(t))
            hl.addWidget(btn)
        jbtn = button("複式分錄", "Primary", "list", "多行借貸傳票，可分割到多個科目")
        jbtn.setMinimumHeight(44)
        jbtn.clicked.connect(lambda: JournalDialog(self.ctx, parent=self.window()).exec())
        hl.addWidget(jbtn)
        more = button("更多功能")
        more.setMinimumHeight(44)
        menu = QMenu(more)
        for text, ic, fn in (("復原上一步（Ctrl+Z）", "undo", lambda: self.window().undo()),
                             ("更新餘額／市值", "refresh", lambda: AdjustDialog(self.ctx, parent=self.window()).exec()),
                             ("定期交易（每月固定收支）", "restore", self.recurring),
                             ("匯入 Excel／CSV", "excel", lambda: ImportDialog(self.ctx, self.window()).exec()),
                             ("修改紀錄（稽核軌跡）", "eye", lambda: AuditDialog(self.ctx, parent=self.window()).exec()),
                             ("會計科目表（新增科目）", "list", self.chart)):
            a = QAction(icon(ic), text, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        more.setMenu(menu)
        hl.addWidget(more)
        b.addWidget(head)

        # 篩選
        fc = Card(padding=14)
        self.period = QComboBox()
        self.period.addItems(PERIOD_PRESETS)
        self.d1 = make_date_edit()
        self.d2 = make_date_edit()
        self.ttype = QComboBox()
        self.ttype.addItem("全部類型", None)
        for k, v in TYPE_LABELS.items():
            self.ttype.addItem(v, k)
        self.account = QComboBox()
        self.account.setMinimumWidth(150)
        self.category = QComboBox()
        self.category.setMinimumWidth(130)
        self.tag = QComboBox()
        self.tag.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.tag.setToolTip("只顯示有這個標籤／專案的紀錄")
        self.keyword = QLineEdit()
        self.keyword.setPlaceholderText("搜尋說明、分類、帳戶…")
        self.keyword.addAction(icon("search", C.muted), QLineEdit.ActionPosition.LeadingPosition)
        self.keyword.setClearButtonEnabled(True)
        self.show_void = QCheckBox("顯示已作廢")
        clear = button("清除篩選", "Link")
        clear.clicked.connect(self.clear_filters)
        lbl = QLabel("期間")
        lbl.setObjectName("Muted")
        lbl2 = QLabel("篩選")
        lbl2.setObjectName("Muted")
        self.keyword.setMinimumWidth(240)
        # 視窗較窄或字型較大時自動分成兩列，日期與篩選欄位不會被壓縮
        fc.lay.addWidget(ResponsiveRow([lbl, self.period, self.d1, QLabel("～"), self.d2], [self.show_void],
                                       spacing=10))
        fc.lay.addWidget(ResponsiveRow([lbl2, self.ttype, self.account, self.category, self.tag],
                                       [(self.keyword, 1), clear], spacing=10))
        b.addWidget(fc)

        # 表格
        self.table = DataTable([
            Column("日期", lambda r: fmt_date(r["date"]), sort=lambda r: (r["date"], r["id"]), width=118,
                   color=lambda r: C.faint if r["void"] else None),
            Column("傳票號碼", lambda r: voucher_no(r["id"]) + (" 📎" if r["n_attach"] else ""),
                   align="center", width=120, color=lambda r: C.faint),
            Column("類型", _type_text, align="center", color=_color, width=90, badge=True),
            Column("分類／科目", _cat_text, width=160, color=lambda r: C.faint if r["void"] else None),
            Column("帳戶", _acc_text, width=210, color=lambda r: C.faint if r["void"] else None),
            Column("說明", _note_text, stretch=True, color=lambda r: C.faint if r["void"] else None),
            Column("金額", _amount_text, align="right", sort=lambda r: _signed(r) * (r["rate"] or 1),
                   color=_color, bold=True, width=180),
        ])
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.table.rowActivated.connect(self.edit_txn)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        QShortcut(QKeySequence.StandardKey.Delete, self.table, activated=self.void_selected)
        b.addWidget(self.table, 1)

        # 合計
        foot = Card(padding=12)
        self.f_count = QLabel()
        self.f_inc = QLabel()
        self.f_exp = QLabel()
        self.f_net = QLabel()
        for w in (self.f_inc, self.f_exp, self.f_net):
            w.setStyleSheet("font-weight:700;")
        edit = button("編輯", icon="edit")
        edit.clicked.connect(lambda: self.edit_txn(self.table.current_row()))
        dele = button("作廢", "Danger", "trash")
        dele.clicked.connect(self.void_selected)
        exp = button("匯出 Excel", "Income", "download")
        exp.clicked.connect(self.export)
        # 視窗較窄或字型較大時，按鈕換到第二列，合計金額不會被截斷
        sums = QWidget()
        sl = QHBoxLayout(sums)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(18)
        for w in (self.f_inc, self.f_exp, self.f_net):
            sl.addWidget(w)
        btns = QWidget()
        bl = QHBoxLayout(btns)
        bl.setContentsMargins(0, 0, 0, 0)
        for w in (edit, dele, exp):
            bl.addWidget(w)
        foot.lay.addWidget(ResponsiveRow([self.f_count, "stretch", sums], [btns]))
        tip = QLabel("小技巧：按兩下即可修改；按右鍵可複製、迴轉、作廢或設為定期交易。"
                     "作廢的傳票保留在帳上並留有修改紀錄，不會真的刪除。"
                     "「投資」類型的傳票由投資管理自動產生，選取後按「作廢」即可刪除（一併刪除該筆投資交易）。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        foot.lay.addWidget(tip)
        b.addWidget(foot)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.reload)
        self.period.currentTextChanged.connect(self._period_changed)
        for w in (self.ttype, self.account, self.category, self.tag):
            w.currentIndexChanged.connect(self._timer.start)
        self.show_void.toggled.connect(self._timer.start)
        self.d1.dateChanged.connect(self._custom_date)
        self.d2.dateChanged.connect(self._custom_date)
        self.keyword.textChanged.connect(self._timer.start)
        self._loading = False
        self.period.setCurrentText("本月")
        self._period_changed("本月")

    # ------------------------------------------------------------------
    def _period_changed(self, name: str) -> None:
        if name == "自訂期間":
            return
        a, b = preset_range(name, self.db.date_range())
        self._loading = True
        self.d1.setDate(qdate(a))
        self.d2.setDate(qdate(b))
        self._loading = False
        self._timer.start()

    def _custom_date(self) -> None:
        if self._loading:
            return
        if self.period.currentText() != "自訂期間":
            self.period.blockSignals(True)
            self.period.setCurrentText("自訂期間")
            self.period.blockSignals(False)
        self._timer.start()

    def _fill_combos(self) -> None:
        cur_a = self.account.currentData()
        cur_c = self.category.currentData()
        cur_t = self.tag.currentData()
        for combo in (self.account, self.category, self.tag):
            combo.blockSignals(True)
            combo.clear()
        self.account.addItem("全部帳戶", None)
        for a in self.db.list_accounts(include_archived=True):
            self.account.addItem(a["name"] + ("（已封存）" if a["archived"] else ""), a["id"])
        self.category.addItem("全部分類", None)
        for c in self.db.list_categories(include_archived=True):
            prefix = "收入｜" if c["kind"] == "income" else "支出｜"
            self.category.addItem(prefix + c["name"], c["id"])
        self.tag.addItem("全部標籤", None)
        for t in self.db.all_tags():
            self.tag.addItem(icon("tag", C.primary), t["name"], t["name"])
        self.tag.setVisible(self.tag.count() > 1 or cur_t is not None)
        # 依最長的標籤名稱設定寬度（含圖示、內距與下拉箭頭），選取後不會被截斷
        fm = self.tag.fontMetrics()
        longest = max((fm.horizontalAdvance(self.tag.itemText(i)) for i in range(self.tag.count())), default=0)
        self.tag.setMinimumWidth(min(longest + 90, 320))
        for combo, val in ((self.account, cur_a), (self.category, cur_c), (self.tag, cur_t)):
            i = combo.findData(val)
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.blockSignals(False)

    def refresh(self) -> None:
        self._fill_combos()
        if self.period.currentText() != "自訂期間":
            a, b = preset_range(self.period.currentText(), self.db.date_range())
            self._loading = True
            self.d1.setDate(qdate(a))
            self.d2.setDate(qdate(b))
            self._loading = False
        self.reload()

    def reload(self) -> None:
        a, b = iso(self.d1.date()), iso(self.d2.date())
        if a > b:
            a, b = b, a
        rows = self.db.query_transactions(start=a, end=b, ttype=self.ttype.currentData(),
                                          account_id=self.account.currentData(),
                                          category_id=self.category.currentData(),
                                          keyword=self.keyword.text() or None,
                                          include_void=self.show_void.isChecked(),
                                          tag=self.tag.currentData())
        self.table.set_rows(rows)
        base = self.ctx.base
        inc = sum(r["inc"] for r in rows)
        exp = sum(r["exp"] for r in rows)
        n_void = sum(1 for r in rows if r["void"])
        self.f_count.setText(f"共 {len(rows) - n_void:,} 筆" + (f"（另有已作廢 {n_void} 筆）" if n_void else ""))
        self.f_inc.setText(f"收入 {fmt_money(inc, base)}")
        self.f_inc.setStyleSheet(f"font-weight:700; color:{C.income};")
        self.f_exp.setText(f"支出 {fmt_money(exp, base)}")
        self.f_exp.setStyleSheet(f"font-weight:700; color:{C.expense};")
        self.f_net.setText(f"結餘 {fmt_money(inc - exp, base)}")

    def apply_filter(self, account_id=None, category_id=None, period=None, tag=None, start=None, end=None, **_):
        self._fill_combos()
        self.tag.setCurrentIndex(max(0, self.tag.findData(tag)) if tag else 0)
        if start and end:
            self.period.blockSignals(True)
            self.period.setCurrentText("自訂期間")
            self.period.blockSignals(False)
            self._loading = True
            self.d1.setDate(qdate(start))
            self.d2.setDate(qdate(end))
            self._loading = False
            self._timer.start()
            return
        if account_id is not None:
            self.account.setCurrentIndex(max(0, self.account.findData(account_id)))
        if category_id is not None:
            self.category.setCurrentIndex(max(0, self.category.findData(category_id)))
        self.period.setCurrentText(period or "全部")
        self._period_changed(self.period.currentText())

    def clear_filters(self) -> None:
        for combo in (self.ttype, self.account, self.category, self.tag):
            combo.setCurrentIndex(0)
        self.keyword.clear()
        self.show_void.setChecked(False)
        self.period.setCurrentText("本月")
        self._period_changed("本月")

    # ------------------------------------------------------------------
    def new_txn(self, ttype: str) -> None:
        TransactionDialog(self.ctx, ttype, account_id=self.account.currentData(),
                          parent=self.window()).exec()

    def edit_txn(self, row: dict | None) -> None:
        if row:
            open_voucher(self.ctx, row["id"], self.window())

    def copy_txn(self, row: dict) -> None:
        txn = dict(self.db.get_transaction(row["id"]))
        if txn["source"].startswith(("inv:", "close:")):
            info(self, "系統自動產生的傳票（投資分錄、年度結帳分錄）不能複製。")
            return
        txn["date"] = dt.date.today().isoformat()
        if txn["type"] == "journal":
            prefill = []
            for ln in self.db.get_lines(row["id"]):
                key = ("account", ln["account_id"]) if ln["account_id"] else \
                    ("category", ln["category_id"]) if ln["category_id"] else ("special", ln["special"])
                prefill.append({"key": key, "debit": ln["debit"], "credit": ln["credit"], "memo": ln["memo"],
                                "orig": ln["orig"]})
            JournalDialog(self.ctx, prefill=prefill, note=txn["note"], tags=self.db.get_tags(row["id"]),
                          parent=self.window()).exec()
            return
        txn["tags"] = self.db.get_tags(row["id"])
        TransactionDialog(self.ctx, txn=txn, copy=True, parent=self.window()).exec()

    def void_selected(self) -> None:
        rows = [r for r in self.table.selected_rows() if not r["void"]]
        if not rows:
            return
        sys_rows = [r for r in rows if r["source"].startswith("inv:")]
        if sys_rows:
            if len(sys_rows) < len(rows):
                info(self, "「投資」類型的傳票是刪除而不是作廢，請將它們與其他傳票分開選取。")
                return
            self.delete_inv_vouchers(sys_rows)
            return
        reason = ask_void_reason(self.window(), len(rows))
        if reason is None:
            return
        try:
            self.db.void_transactions([r["id"] for r in rows], reason)
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已作廢 {len(rows)} 筆傳票（Ctrl+Z 可復原）")

    def delete_inv_vouchers(self, rows: list[dict]) -> None:
        """投資管理自動產生的傳票：刪除產生它的投資交易，之後的成本與分錄自動重算。"""
        from ..investments import KIND_LABELS, Investments
        from ..widgets import ask
        inv = Investments(self.db)
        desc = []
        for r in rows:
            evs = inv.voucher_events(r["id"])
            for ev in evs:
                sec = inv.get_security(ev["security_id"])
                desc.append(f"{voucher_no(r['id'])}：{fmt_date(ev['date'])} {sec['name']} "
                            f"{KIND_LABELS.get(ev['kind'], ev['kind'])}")
            if not evs:
                desc.append(f"{voucher_no(r['id'])}：{r['note']}")
        if not ask(self, "這是「投資管理」自動產生的傳票。刪除後，產生它的投資交易也會一併刪除，"
                         "系統會重算之後的成本與分錄：\n\n" + "\n".join(desc) + "\n\n確定要刪除嗎？",
                   yes="刪除", danger=True):
            return
        try:
            n = inv.delete_vouchers([r["id"] for r in rows])
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已刪除 {n} 筆投資交易及其傳票")

    def unvoid(self, row: dict) -> None:
        try:
            self.db.unvoid_transaction(row["id"])
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"{voucher_no(row['id'])} 已恢復")

    def reverse(self, row: dict) -> None:
        from ..widgets import ask
        if not ask(self, f"將以今天日期產生一張與 {voucher_no(row['id'])} 借貸相反的「迴轉分錄」，"
                         "原傳票保留不變。\n常用於已結帳期間的更正。確定嗎？", yes="產生迴轉分錄"):
            return
        try:
            new_id = self.db.reverse_transaction(row["id"])
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已產生迴轉分錄 {voucher_no(new_id)}")

    def make_recurring(self, row: dict) -> None:
        t = self.db.get_transaction(row["id"])
        data = {k: t[k] for k in ("type", "account_id", "to_account_id", "amount", "category_id",
                                  "note", "date") if t.get(k) is not None}
        RecurringEditDialog(self.ctx, from_txn=data, parent=self.window()).exec()

    def chart(self) -> None:
        from ..dialogs_chart import ChartOfAccountsDialog
        ChartOfAccountsDialog(self.ctx, self.window()).exec()

    def recurring(self) -> None:
        RecurringManagerDialog(self.ctx, self.window()).exec()

    def context_menu(self, pos) -> None:
        row = self.table.current_row()
        if not row:
            return
        m = QMenu(self)
        items = []
        if row["void"]:
            items += [("取消作廢（恢復這筆）", "restore", lambda: self.unvoid(row))]
        else:
            items += [("開啟／編輯", "edit", lambda: self.edit_txn(row)),
                      ("複製一筆（日期改為今天）", "copy", lambda: self.copy_txn(row))]
            if row["type"] in ("income", "expense", "transfer"):
                items.append(("設為定期交易…", "restore", lambda: self.make_recurring(row)))
            if row["source"].startswith("inv:"):
                items += [None, ("刪除（一併刪除投資管理的交易）", "trash", self.void_selected)]
            else:
                items += [None, ("迴轉（產生反向分錄）", "refresh", lambda: self.reverse(row)),
                          ("作廢", "trash", self.void_selected)]
        if not row["source"]:
            items += [None, ("加上標籤／專案…", "tag", self.tag_selected)]
            sel_tags = sorted({t for r in self.table.selected_rows() for t in r.get("tags") or []})
            for t in sel_tags[:8]:
                items.append((f"移除標籤「{t}」", "minus", lambda _=False, t=t: self.untag_selected(t)))
        items += [None, ("修改紀錄", "eye", lambda: AuditDialog(self.ctx, row["id"], self.window()).exec())]
        for it in items:
            if it is None:
                m.addSeparator()
                continue
            text, ic, fn = it
            a = QAction(icon(ic, C.expense if ic == "trash" else C.text), text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def tag_selected(self) -> None:
        rows = [r for r in self.table.selected_rows() if not r["source"]]
        if not rows:
            return
        from ..dialogs_more import TagPickDialog
        dlg = TagPickDialog(self.ctx, len(rows), self.window())
        if not dlg.exec():
            return
        try:
            n = self.db.add_tag([r["id"] for r in rows], dlg.tag)
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已為 {n} 筆紀錄加上標籤「{dlg.tag}」" if n else "選取的紀錄都已經有這個標籤")

    def untag_selected(self, tag: str) -> None:
        n = self.db.remove_tag_from([r["id"] for r in self.table.selected_rows()], tag)
        self.ctx.changed()
        self.ctx.toast.emit(f"已從 {n} 筆紀錄移除標籤「{tag}」")

    def export(self) -> None:
        ExportDialog(self.ctx, self.window(), iso(self.d1.date()), iso(self.d2.date())).exec()
