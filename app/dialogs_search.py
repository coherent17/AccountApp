"""全域搜尋視窗（Ctrl+F）：一次找遍傳票、會計科目、投資標的與定期交易。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit

from .context import AppContext
from .dialogs import BaseDialog, open_voucher
from .search import GROUP_ORDER, search
from .theme import C, fmt_date, fmt_num, icon
from .widgets import Column, DataTable, info

SCOPES = ["全部", "傳票", "科目", "投資標的", "定期交易"]

HINT = ("可輸入：摘要或備註文字、金額（1500 或 1,500）、傳票號碼（V000123）、科目代號（1201）、"
        "日期或月份（2025-03、114/3/5）、股票代號或名稱、附件檔名。多個關鍵字用空白隔開，"
        "例如「全聯 2025-03」。雙擊結果即可開啟。")


def _color(r: dict) -> str | None:
    if r.get("void"):
        return C.faint
    return None


class SearchDialog(BaseDialog):
    """非強制回應視窗：搜尋時仍可操作主畫面；資料變更後自動重新搜尋。"""

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__("全域搜尋", parent, width=1080)
        self.setModal(False)
        self.ctx = ctx
        self.resize(1120, 680)

        row = QHBoxLayout()
        self.box = QLineEdit()
        self.box.setPlaceholderText("搜尋摘要、金額、傳票號碼、科目代號、日期、股票…")
        self.box.addAction(icon("search", C.muted), QLineEdit.ActionPosition.LeadingPosition)
        self.box.setClearButtonEnabled(True)
        self.box.setMinimumHeight(44)
        self.box.setStyleSheet("font-size: 12pt;")
        row.addWidget(self.box, 1)
        row.addWidget(QLabel("範圍"))
        self.scope = QComboBox()
        self.scope.addItems(SCOPES)
        row.addWidget(self.scope)
        self.root.addLayout(row)

        hint = QLabel(HINT)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)

        base = ctx.base
        self.table = DataTable([
            Column("類別", lambda r: r["group"] + ("・作廢" if r.get("void") else "")
                   + ("・系統" if r.get("system") else ""), width=120, color=_color,
                   sort=lambda r: (GROUP_ORDER[r["group"]], r["group"])),
            Column("日期", lambda r: fmt_date(r["date"]) if r["date"] else "", align="center", width=120,
                   color=_color),
            Column("編號／代號", lambda r: r["ref"], align="center", width=110, bold=True, color=_color),
            Column("內容", lambda r: r["title"], stretch=True, color=_color),
            Column("說明", lambda r: r["detail"], width=330, color=_color),
            Column("金額", lambda r: "" if r["amount"] is None else
                   fmt_num(r["amount"], r["currency"] or base), align="right", width=130, color=_color,
                   sort=lambda r: r["amount"] or 0),
        ])
        self.table.setMinimumHeight(380)
        self.table.rowActivated.connect(self.open_row)
        self.root.addWidget(self.table, 1)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self.table, activated=self._open_current,
                  context=Qt.ShortcutContext.WidgetShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_Enter), self.table, activated=self._open_current,
                  context=Qt.ShortcutContext.WidgetShortcut)

        self.summary = QLabel("")
        self.summary.setStyleSheet(f"color:{C.muted}; font-weight:700;")
        self.root.addWidget(self.summary)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.run)
        self.box.textChanged.connect(lambda *_: self._timer.start())
        self.box.returnPressed.connect(self._enter)
        self.scope.currentIndexChanged.connect(self.run)
        ctx.dataChanged.connect(self._data_changed)
        self.result: dict = {"rows": []}

    # ------------------------------------------------------------------
    def focus_box(self) -> None:
        self.box.setFocus()
        self.box.selectAll()

    def _data_changed(self) -> None:
        if self.isVisible() and self.box.text().strip():
            self.run()

    def _enter(self) -> None:
        self._timer.stop()
        self.run()
        if self.table.model_.rows:
            self.table.setFocus()
            self.table.selectRow(0)

    def run(self) -> None:
        self._timer.stop()
        text = self.box.text().strip()
        if not text:
            self.table.set_rows([])
            self.summary.setText("")
            return
        self.result = search(self.ctx.db, text)
        scope = self.scope.currentText()
        rows = [r for r in self.result["rows"] if scope == "全部" or r["group"] == scope]
        self.table.set_rows(rows)
        counts: dict[str, int] = {}
        for r in self.result["rows"]:
            counts[r["group"]] = counts.get(r["group"], 0) + 1
        if not counts:
            self.summary.setText("找不到符合的資料。可以試試較短的關鍵字，或改用金額、日期、代號搜尋。")
            return
        unit = {"傳票": "筆", "科目": "個", "投資標的": "檔", "定期交易": "項"}
        parts = []
        for g in sorted(counts, key=GROUP_ORDER.get):
            n = self.result["total_vouchers"] if g == "傳票" else counts[g]
            parts.append(f"{g} {n} {unit[g]}")
        text = "找到：" + "、".join(parts)
        if self.result.get("truncated"):
            text += f"（傳票僅列出最近 {counts['傳票']} 筆，請加上更多關鍵字縮小範圍）"
        self.summary.setText(text)

    def _open_current(self) -> None:
        r = self.table.current_row()
        if r:
            self.open_row(r)

    def open_row(self, r: dict) -> None:
        kind = r["kind"]
        if kind == "voucher":
            open_voucher(self.ctx, r["id"], self)
        elif kind == "account":
            self._go("reports", {"tab": "ledger", "account_id": r["id"]})
        elif kind == "category":
            self._go("transactions", {"category_id": r["id"], "period": "全部"})
        elif kind == "security":
            self._go("investments", {"security_id": r["id"]})
        elif kind == "special":
            # 系統科目（評價、兌換、處分損益…）沒有獨立頁面：改列出使用此科目的傳票
            self.box.setText(r["title"])
            self.scope.setCurrentText("傳票")
            self.run()
        elif kind == "recurring":
            from .dialogs_more import RecurringEditDialog
            rec = next((x for x in self.ctx.db.list_recurring() if x["id"] == r["id"]), None)
            if rec is None:
                info(self, "找不到這筆定期交易，可能已被刪除。")
                return
            RecurringEditDialog(self.ctx, rec=rec, parent=self).exec()

    def _go(self, page: str, kwargs: dict) -> None:
        """切換到主畫面的對應頁面，並收起搜尋視窗（再按 Ctrl+F 可回到原本的搜尋結果）。"""
        self.hide()
        self.ctx.navigate.emit(page, kwargs)
        if self.parent():
            self.parent().activateWindow()
