from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QMenu

from ..dialogs import AccountDialog, AdjustDialog
from ..theme import C, fmt_date, fmt_money, fmt_num, icon
from ..widgets import Card, Column, DataTable, StatCard, ask, button, error, info, page_header, \
    section_title
from .base import Page


class AccountsPage(Page):
    title = "帳戶管理"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent=parent)
        b = self.body
        head, hl = page_header("帳戶管理", "資產與負債科目：銀行、現金、投資、信用卡、貸款等")
        add = button("新增帳戶", "Primary", icon("plus", "#FFFFFF"))
        add.setMinimumHeight(44)
        add.clicked.connect(self.add)
        adj = button("更新餘額／市值", "Adjust", icon("refresh", "#FFFFFF"))
        adj.setMinimumHeight(44)
        adj.clicked.connect(lambda: self.adjust(None))
        chart = button("會計科目表", icon=icon("list"), tooltip="檢視全部會計科目、新增科目（含自訂代號）")
        chart.setMinimumHeight(44)
        chart.clicked.connect(self.chart)
        self.more_btn = button("更多功能 ▾")
        self.more_btn.setMinimumHeight(44)
        menu = QMenu(self.more_btn)
        for text, ic, fn in (("銀行對帳（與存摺逐筆核對）", "list", lambda: self.reconcile(None)),
                             ("更新匯率", "refresh", self.rates)):
            a = QAction(icon(ic), text, menu)
            a.triggered.connect(fn)
            menu.addAction(a)
        self.more_btn.setMenu(menu)
        hl.addWidget(chart)
        hl.addWidget(self.more_btn)
        hl.addWidget(adj)
        hl.addWidget(add)
        b.addWidget(head)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        self.c_assets = StatCard("資產總計", C.income)
        self.c_liab = StatCard("負債總計", C.expense)
        self.c_net = StatCard("淨資產（業主權益）", C.primary)
        for c in (self.c_assets, self.c_liab, self.c_net):
            cards.addWidget(c)
        b.addLayout(cards)

        self.show_archived = QCheckBox("顯示已封存的帳戶")
        self.show_archived.toggled.connect(self.refresh)

        self.tables = {}
        for kind, title in (("asset", "資產"), ("liability", "負債")):
            card = Card()
            th = QHBoxLayout()
            th.addWidget(section_title(title))
            self.__dict__[f"sum_{kind}"] = QLabel()
            th.addStretch()
            th.addWidget(self.__dict__[f"sum_{kind}"])
            card.lay.addLayout(th)
            bal_title = "餘額（原幣）" if kind == "asset" else "欠款（原幣）"
            t = DataTable([
                Column("代號", lambda r: r["code"], align="center", width=64, color=lambda r: C.muted),
                Column("帳戶名稱", lambda r: r["name"] + ("（已封存）" if r["archived"] else ""),
                       bold=True, width=176,
                       color=lambda r: C.faint if r["archived"] else None),
                Column("類別", lambda r: r["category"], width=92),
                Column("流動性", lambda r: "流動" if self.db.is_current(r) else "非流動",
                       align="center", width=80, color=lambda r: C.muted),
                Column("幣別", lambda r: r["currency"], align="center", width=62),
                Column(bal_title, lambda r: fmt_num(r["balance"], r["currency"]), align="right",
                       sort=lambda r: r["balance"], width=140,
                       color=lambda r: C.expense if (r["balance"] < 0) else None),
                Column("匯率", lambda r: "" if r["rate"] == 1 else f"{r['rate']:.4f}",
                       align="right", width=72),
                Column(f"折合{ctx.base}", lambda r: fmt_num(abs(r["base_value"]), ctx.base),
                       align="right", sort=lambda r: abs(r["base_value"]), bold=True, width=140),
                Column("占比", lambda r: f"{r.get('_pct', 0):.1%}", align="right",
                       sort=lambda r: r.get("_pct", 0), width=72),
                Column("到期日", lambda r: fmt_date(r["maturity_date"]) if r["maturity_date"] else "",
                       align="center", width=110,
                       color=lambda r: C.expense if r["maturity_date"] and
                       r["maturity_date"] <= (dt.date.today() + dt.timedelta(days=60)).isoformat() else C.muted),
                Column("備註", lambda r: r["note"] + (f"（年利率 {r['interest_rate']:g}%）"
                                                     if r["interest_rate"] else ""),
                       stretch=True, color=lambda r: C.muted),
            ])
            t.sortByColumn(7, Qt.SortOrder.DescendingOrder)
            t.rowActivated.connect(self.edit)
            t.pressed.connect(lambda _idx, k=kind: setattr(self, "_last", k))
            t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            t.customContextMenuRequested.connect(lambda pos, tt=t: self.context_menu(tt, pos))
            card.lay.addWidget(t)
            self.tables[kind] = t
            b.addWidget(card)

        bar = QHBoxLayout()
        bar.addWidget(self.show_archived)
        bar.addStretch()
        for text, kind, ic, fn in (("查看分類帳", None, "list", self.view_ledger),
                                   ("編輯", None, "edit", lambda: self.edit(self._current())),
                                   ("封存／取消封存", None, "archive", self.toggle_archive),
                                   ("刪除", "Danger", "trash", self.delete)):
            btn = button(text, kind, icon(ic, C.expense if kind == "Danger" else C.text))
            btn.clicked.connect(fn)
            bar.addWidget(btn)
        b.addLayout(bar)
        tip = QLabel("說明：資產帳戶的收入會增加餘額、支出會減少餘額；信用卡等負債帳戶刷卡（支出）會增加欠款，"
                     "從銀行轉帳繳款會減少欠款。按兩下帳戶可修改，按右鍵有更多功能。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        b.addWidget(tip)
        b.addStretch()

    def chart(self) -> None:
        from ..dialogs_chart import ChartOfAccountsDialog
        ChartOfAccountsDialog(self.ctx, self.window()).exec()

    def refresh(self) -> None:
        base = self.ctx.base
        accs = self.db.account_summaries(include_archived=self.show_archived.isChecked())
        nw = self.db.net_worth()
        self.c_assets.set_money(nw["assets"], base)
        self.c_liab.set_money(nw["liabilities"], base)
        self.c_net.set_money(nw["net"], base, "", C.primary if nw["net"] >= 0 else C.expense)
        for kind, t in self.tables.items():
            rows = [a for a in accs if a["kind"] == kind]
            total = sum(abs(a["base_value"]) for a in rows) or 1
            for a in rows:
                a["_pct"] = abs(a["base_value"]) / total
            t.set_rows(rows)
            t.setMinimumHeight(min(12, max(2, len(rows))) * 44 + 50)
            t.setMaximumHeight(min(12, max(2, len(rows))) * 44 + 50)
            lbl = self.__dict__[f"sum_{kind}"]
            v = nw["assets"] if kind == "asset" else nw["liabilities"]
            lbl.setText(f"合計 {fmt_money(v, base)}　｜　{len(rows)} 個帳戶")
            lbl.setObjectName("Muted")

    def _current(self) -> dict | None:
        return self.tables[getattr(self, "_last", "asset")].current_row()

    def add(self) -> None:
        AccountDialog(self.ctx, parent=self.window()).exec()

    def edit(self, row: dict | None) -> None:
        if not row:
            info(self, "請先點選一個帳戶。")
            return
        AccountDialog(self.ctx, self.db.get_account(row["id"]), parent=self.window()).exec()

    def adjust(self, row: dict | None) -> None:
        AdjustDialog(self.ctx, row["id"] if row else None, parent=self.window()).exec()

    def reconcile(self, row: dict | None) -> None:
        from ..dialogs_more import ReconcileDialog
        row = row or self._current()
        ReconcileDialog(self.ctx, row["id"] if row else None, self.window()).exec()

    def rates(self) -> None:
        from ..dialogs_invest import RateDialog
        RateDialog(self.ctx, self.window()).exec()

    def view_txns(self, row: dict) -> None:
        self.ctx.navigate.emit("transactions", {"account_id": row["id"]})

    def view_ledger(self, row: dict | None = None) -> None:
        row = row or self._current()
        if not row:
            info(self, "請先點選一個帳戶。")
            return
        self.ctx.navigate.emit("reports", {"tab": "ledger", "account_id": row["id"]})

    def toggle_archive(self) -> None:
        row = self._current()
        if not row:
            info(self, "請先點選一個帳戶。")
            return
        if row["archived"]:
            self.db.update_account(row["id"], archived=0)
        else:
            if abs(row["balance"]) > 0.004 and not ask(
                    self, f"「{row['name']}」目前仍有餘額 {fmt_money(row['balance'], row['currency'])}，"
                          "封存後仍會計入資產負債，但不會出現在記帳選單中。確定要封存嗎？"):
                return
            self.db.update_account(row["id"], archived=1)
        self.ctx.changed()

    def delete(self) -> None:
        row = self._current()
        if not row:
            info(self, "請先點選一個帳戶。")
            return
        n = self.db.account_txn_count(row["id"])
        if n:
            error(self, f"「{row['name']}」已有 {n} 筆交易紀錄，無法刪除。\n"
                        "如果不再使用，建議改用「封存」，歷史紀錄會保留。", "無法刪除")
            return
        if ask(self, f"確定要刪除帳戶「{row['name']}」嗎？", yes="刪除", danger=True):
            self.db.delete_account(row["id"])
            self.ctx.changed()

    def context_menu(self, table: DataTable, pos) -> None:
        row = table.current_row()
        if not row:
            return
        m = QMenu(self)
        for text, ic, fn in (("編輯帳戶", "edit", lambda: self.edit(row)),
                             ("更新餘額／市值", "refresh", lambda: self.adjust(row)),
                             ("查看這個帳戶的收支明細", "eye", lambda: self.view_txns(row)),
                             ("查看分類帳（借貸與累計餘額）", "list", lambda: self.view_ledger(row)),
                             ("銀行對帳…", "list", lambda: self.reconcile(row))):
            a = QAction(icon(ic), text, m)
            a.triggered.connect(fn)
            m.addAction(a)
        m.addSeparator()
        a = QAction(icon("archive"), "取消封存" if row["archived"] else "封存", m)
        a.triggered.connect(self.toggle_archive)
        m.addAction(a)
        m.exec(table.viewport().mapToGlobal(pos))
