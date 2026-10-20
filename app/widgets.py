"""共用元件：金額輸入框、統計卡片、表格模型、訊息視窗等。"""

from __future__ import annotations

import ast
import datetime as dt
import operator
from typing import Any, Callable

from PySide6.QtCore import (QAbstractTableModel, QDate, QModelIndex, QSortFilterProxyModel,
                            Qt, Signal)
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QDateEdit, QFrame,
                               QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSizePolicy, QStyle, QStyledItemDelegate, QTableView, QVBoxLayout,
                               QWidget)

from .theme import C, fmt_num

# ---------------------------------------------------------------------- 金額輸入
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv}


def safe_eval(expr: str) -> float | None:
    """計算簡單算式（加減乘除與括號），失敗回傳 None。"""
    expr = (expr.replace(",", "").replace("，", "").replace("＋", "+").replace("－", "-")
            .replace("×", "*").replace("÷", "/").replace("x", "*").replace("X", "*").strip())
    if not expr:
        return None

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        raise ValueError

    try:
        return round(ev(ast.parse(expr, mode="eval")), 2)
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError, RecursionError):
        return None


class AmountEdit(QLineEdit):
    """可輸入算式（例如 120+35*2）的金額欄位，離開欄位時自動計算並加上千分位。"""

    valueChanged = Signal()

    def __init__(self, parent=None, allow_negative: bool = False, decimals: int = 2):
        super().__init__(parent)
        self.setObjectName("AmountEdit")
        self.allow_negative = allow_negative
        self.decimals = decimals
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setPlaceholderText("0")
        self.setToolTip("可直接輸入算式，例如 120+35 或 1500*3，按 Enter 自動計算")
        self.editingFinished.connect(self._normalize)
        self.textChanged.connect(lambda _: self.valueChanged.emit())

    def _normalize(self) -> None:
        v = safe_eval(self.text())
        if v is not None:
            self.blockSignals(True)
            self.setText(self._fmt(v))
            self.blockSignals(False)
            self.valueChanged.emit()

    def _fmt(self, v: float) -> str:
        if self.decimals == 0 or float(v).is_integer():
            return f"{v:,.0f}"
        return f"{v:,.{self.decimals}f}"

    def value(self) -> float | None:
        return safe_eval(self.text())

    def setValue(self, v: float | None) -> None:
        self.setText("" if v is None else self._fmt(v))

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.selectAll()


# ---------------------------------------------------------------------- 日期
def qdate(iso: str) -> QDate:
    d = dt.date.fromisoformat(iso)
    return QDate(d.year, d.month, d.day)


def iso(qd: QDate) -> str:
    return f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"


def make_date_edit(value: str | None = None) -> QDateEdit:
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("yyyy/MM/dd（ddd）")
    w.setDate(qdate(value) if value else QDate.currentDate())
    w.calendarWidget().setGridVisible(False)
    w.calendarWidget().setVerticalHeaderFormat(w.calendarWidget().VerticalHeaderFormat.NoVerticalHeader)
    w.calendarWidget().setMinimumSize(380, 300)
    return w


# ---------------------------------------------------------------------- 卡片
def shadow(widget: QWidget, blur: int = 24, alpha: int = 22) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, 4)
    eff.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(eff)


class Card(QFrame):
    def __init__(self, parent=None, padding: int = 18):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(10)
        shadow(self)


class StatCard(Card):
    def __init__(self, title: str, accent: str = C.primary, parent=None):
        super().__init__(parent, padding=16)
        self.setMinimumWidth(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top = QHBoxLayout()
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(f"background:{accent}; border-radius:5px;")
        self.dot = dot
        self.title = QLabel(title)
        self.title.setObjectName("StatTitle")
        top.addWidget(dot)
        top.addWidget(self.title)
        top.addStretch()
        self.value = QLabel("—")
        self.value.setObjectName("StatValue")
        self.sub = QLabel("")
        self.sub.setObjectName("StatSub")
        self.lay.setSpacing(6)
        self.lay.addLayout(top)
        self.lay.addWidget(self.value)
        self.lay.addWidget(self.sub)

    def set_accent(self, color: str) -> None:
        self.dot.setStyleSheet(f"background:{color}; border-radius:5px;")

    def set_money(self, amount: float, code: str, sub: str = "", color: str | None = None) -> None:
        from .animations import CountUp
        from .theme import fmt_money
        if not hasattr(self, "_counter"):
            self._counter = CountUp(self.value, lambda v: fmt_money(v, code), self)
        self._counter.formatter = lambda v: fmt_money(v, code)
        self.value.setStyleSheet(f"color:{color};" if color else "")
        self.sub.setText(sub or " ")
        self._counter.set(amount)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{color};" if color else "")
        self.sub.setText(sub or " ")


def page_header(title: str, subtitle: str = "") -> tuple[QWidget, QHBoxLayout]:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        col.addWidget(s)
    lay.addLayout(col)
    lay.addStretch()
    return w, lay


def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


def button(text: str, kind: str | None = None, icon=None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon is not None:
        b.setIcon(icon)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class ChipGroup(QWidget):
    """以按鈕方塊呈現的單選清單（用於選擇分類，比下拉選單更容易點選）。"""

    changed = Signal(object)

    def __init__(self, columns: int = 4, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.idClicked.connect(lambda i: self.changed.emit(self.value()))
        self._buttons: dict[int, QPushButton] = {}

    def set_items(self, items: list[tuple[int, str]]) -> None:
        for b in self._buttons.values():
            self.group.removeButton(b)
            b.hide()
            b.deleteLater()
        self._buttons.clear()
        for n, (key, label) in enumerate(items):
            b = QPushButton(label)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self.group.addButton(b, key)
            self.grid.addWidget(b, n // self.columns, n % self.columns)
            self._buttons[key] = b

    def value(self):
        k = self.group.checkedId()
        return None if k == -1 else k

    def set_value(self, key) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)


# ---------------------------------------------------------------------- 表格
class Column:
    def __init__(self, title: str, value: Callable[[dict], Any], align: str = "left",
                 color: Callable[[dict], str | None] | None = None,
                 sort: Callable[[dict], Any] | None = None, bold: bool = False,
                 width: int | None = None, stretch: bool = False):
        self.title = title
        self.value = value
        self.align = align
        self.color = color
        self.sort = sort
        self.bold = bold
        self.width = width
        self.stretch = stretch


_ALIGN = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
}

SORT_ROLE = Qt.ItemDataRole.UserRole + 1
ROW_ROLE = Qt.ItemDataRole.UserRole + 2


class RowModel(QAbstractTableModel):
    def __init__(self, columns: list[Column], parent=None):
        super().__init__(parent)
        self.columns = columns
        self.rows: list[dict] = []
        self._bold = QFont()
        self._bold.setBold(True)

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            col = self.columns[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return col.title
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return _ALIGN[col.align]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            v = col.value(row)
            return "" if v is None else str(v)
        if role == Qt.ItemDataRole.ToolTipRole:
            v = col.value(row)
            return None if v is None else str(v)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGN[col.align]
        if role == Qt.ItemDataRole.ForegroundRole and col.color:
            c = col.color(row)
            return QBrush(QColor(c)) if c else None
        if role == Qt.ItemDataRole.FontRole and (col.bold or row.get("_bold")):
            return self._bold
        if role == Qt.ItemDataRole.BackgroundRole and row.get("_bg"):
            return QBrush(QColor(row["_bg"]))
        if role == SORT_ROLE:
            return col.sort(row) if col.sort else col.value(row)
        if role == ROW_ROLE:
            return row
        return None


class SortProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)

    def lessThan(self, left, right):
        a = self.sourceModel().data(left, SORT_ROLE)
        b = self.sourceModel().data(right, SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


class _RowDelegate(QStyledItemDelegate):
    """樣式表會忽略資料列的底色，這裡先自行填上（例如日記帳以傳票分組底色）。"""

    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        if bg is not None and not option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, bg)
        super().paint(painter, option, index)


class DataTable(QTableView):
    """美化過的表格，含排序與欄寬設定。"""

    rowActivated = Signal(dict)

    def __init__(self, columns: list[Column], parent=None, sortable: bool = True):
        super().__init__(parent)
        self.model_ = RowModel(columns, self)
        self.proxy = SortProxy(self)
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)
        self.setItemDelegate(_RowDelegate(self))
        self.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setSortingEnabled(sortable)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(44)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(False)
        for i, col in enumerate(columns):
            if col.stretch:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            elif col.width:
                self.setColumnWidth(i, col.width)
        self.doubleClicked.connect(self._activated)

    def set_rows(self, rows: list[dict]) -> None:
        self.model_.set_rows(rows)

    def _activated(self, index) -> None:
        row = self.proxy.data(index, ROW_ROLE)
        if row is not None:
            self.rowActivated.emit(row)

    def selected_rows(self) -> list[dict]:
        out = []
        for idx in self.selectionModel().selectedRows():
            row = self.proxy.data(idx, ROW_ROLE)
            if row is not None:
                out.append(row)
        return out

    def current_row(self) -> dict | None:
        rows = self.selected_rows()
        return rows[0] if rows else None


def amount_color(v: float) -> str | None:
    if v > 0:
        return C.income
    if v < 0:
        return C.expense
    return None


def num_cell(v: float, code: str = "TWD") -> str:
    return fmt_num(v, code)


class EmptyState(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lbl = QLabel(text)
        lbl.setObjectName("Muted")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lay.addStretch()
        lay.addWidget(lbl)
        lay.addStretch()


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(f"color:{C.border}; background:{C.border}; max-height:1px; border:none;")
    return f


# ---------------------------------------------------------------------- 訊息視窗
def _box(parent, icon, title, text, buttons):
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    made = []
    for label, role in buttons:
        made.append(box.addButton(label, role))
    box.setDefaultButton(made[0])
    box.exec()
    return box.clickedButton(), made


def info(parent, text: str, title: str = "提示") -> None:
    _box(parent, QMessageBox.Icon.Information, title, text,
         [("確定", QMessageBox.ButtonRole.AcceptRole)])


def warn(parent, text: str, title: str = "注意") -> None:
    _box(parent, QMessageBox.Icon.Warning, title, text,
         [("確定", QMessageBox.ButtonRole.AcceptRole)])


def error(parent, text: str, title: str = "發生錯誤") -> None:
    _box(parent, QMessageBox.Icon.Critical, title, text,
         [("確定", QMessageBox.ButtonRole.AcceptRole)])


def ask(parent, text: str, title: str = "請確認", yes: str = "確定", no: str = "取消",
        danger: bool = False) -> bool:
    clicked, made = _box(parent,
                         QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question,
                         title, text,
                         [(no, QMessageBox.ButtonRole.RejectRole),
                          (yes, QMessageBox.ButtonRole.AcceptRole)])
    return clicked is made[1]


# ---------------------------------------------------------------------- 期間
PERIOD_PRESETS = ["本月", "上月", "近 3 個月", "今年", "去年", "全部", "自訂期間"]


def preset_range(name: str, data_range: tuple[str, str]) -> tuple[str, str]:
    today = dt.date.today()
    first = today.replace(day=1)
    if name == "本月":
        nxt = (first + dt.timedelta(days=32)).replace(day=1)
        return first.isoformat(), (nxt - dt.timedelta(days=1)).isoformat()
    if name == "上月":
        last_end = first - dt.timedelta(days=1)
        return last_end.replace(day=1).isoformat(), last_end.isoformat()
    if name == "近 3 個月":
        m = today.month - 2
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        return dt.date(y, m, 1).isoformat(), today.isoformat()
    if name == "今年":
        return dt.date(today.year, 1, 1).isoformat(), dt.date(today.year, 12, 31).isoformat()
    if name == "去年":
        return dt.date(today.year - 1, 1, 1).isoformat(), dt.date(today.year - 1, 12, 31).isoformat()
    return data_range
