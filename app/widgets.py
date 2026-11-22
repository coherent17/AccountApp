"""共用元件：金額輸入框、統計卡片、表格模型、訊息視窗等。"""

from __future__ import annotations

import ast
import datetime as dt
import operator
import re
import unicodedata
from typing import Any, Callable

from PySide6.QtCore import (QAbstractTableModel, QDate, QEvent, QModelIndex, QPoint, QRectF,
                            QSortFilterProxyModel, Qt, QTimer, Signal)
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCalendarWidget, QComboBox, QFrame,
                               QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSizePolicy, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
                               QTabWidget, QVBoxLayout, QWidget)

from .theme import C, fmt_num

# ---------------------------------------------------------------------- 金額輸入
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv}


def safe_eval(expr: str, digits: int = 2) -> float | None:
    """計算簡單算式（加減乘除與括號），四捨五入至 digits 位小數，失敗回傳 None。"""
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
        return round(ev(ast.parse(expr, mode="eval")), digits)
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
        v = safe_eval(self.text(), self.decimals)
        if v is not None:
            self.blockSignals(True)
            self.setText(self._fmt(v))
            self.blockSignals(False)
            self.valueChanged.emit()

    def _fmt(self, v: float) -> str:
        if self.decimals == 0 or float(v).is_integer():
            return f"{v:,.0f}"
        if self.decimals > 2:   # 股數、單價：顯示到需要的位數（0.866，不顯示成 0.8660）
            text = f"{v:,.{self.decimals}f}".rstrip("0")
            return text + "0" * max(0, 2 - len(text.split(".")[1])) if "." in text else text
        return f"{v:,.{self.decimals}f}"

    def value(self) -> float | None:
        return safe_eval(self.text(), max(self.decimals, 2))

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


def parse_date_text(text: str) -> QDate | None:
    """解析手動輸入的日期：西元或民國年皆可，例如 2026/11/5、115/11/5、20261105、1151105、11/5。"""
    t = unicodedata.normalize("NFKC", text).split("(")[0].strip()
    if t.isdigit():
        n = len(t)
        if n not in (4, 7, 8):
            return None
        parts = [t[:-4], t[-4:-2], t[-2:]] if n > 4 else [t[:2], t[2:]]
    else:
        parts = [p for p in re.split(r"[/\-.\s年月日]+", t) if p]
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None
    nums = [int(p) for p in parts]
    if len(nums) == 2:
        nums.insert(0, QDate.currentDate().year())
    if nums[0] < 1000:
        nums[0] += 1911
    d = QDate(*nums)
    return d if d.isValid() and 1900 <= d.year() <= 2200 else None


class DateEdit(QComboBox):
    """可直接打字的日期欄（Enter 或離開欄位時生效），也可按箭頭開月曆；↑↓ 前後一天。"""
    dateChanged = Signal(QDate)
    FORMAT = "yyyy/MM/dd（ddd）"

    def __init__(self, value: str | None = None):
        super().__init__()
        self.setEditable(True)
        self.setCompleter(None)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumContentsLength(19)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setToolTip("可直接輸入，例如 2026/11/5、115/11/5、1151105 或 11/5，也可按右側箭頭開月曆")
        self._date = qdate(value) if value else QDate.currentDate()
        self._calendar: QCalendarWidget | None = None
        self.lineEdit().installEventFilter(self)
        self.lineEdit().editingFinished.connect(self._commit)
        self._show_date()

    def date(self) -> QDate:
        self._commit()
        return self._date

    def setDate(self, d: QDate) -> None:
        if d.isValid() and d != self._date:
            self._date = d
            self._show_date()
            self.dateChanged.emit(d)
        else:
            self._show_date()

    def minimumSizeHint(self):
        # 版面變窄時也要完整顯示「2026/12/31（週四）」，不可被壓縮成「/31（週四）」
        h = super().minimumSizeHint()
        h.setWidth(self.fontMetrics().horizontalAdvance("2026/12/31") + 48)   # 窄時省略星期
        return h

    def calendarWidget(self) -> QCalendarWidget:
        if self._calendar is None:
            cal = QCalendarWidget(self)
            cal.setWindowFlags(Qt.WindowType.Popup)
            cal.setGridVisible(False)
            cal.setVerticalHeaderFormat(cal.VerticalHeaderFormat.NoVerticalHeader)
            cal.setMinimumSize(380, 300)
            cal.clicked.connect(self._picked)
            cal.activated.connect(self._picked)
            self._calendar = cal
        return self._calendar

    def showPopup(self) -> None:
        self._commit()
        cal = self.calendarWidget()
        cal.setSelectedDate(self._date)
        cal.adjustSize()
        pos = self.mapToGlobal(QPoint(0, self.height()))
        screen = self.screen().availableGeometry()
        if pos.y() + cal.height() > screen.bottom():
            pos.setY(self.mapToGlobal(QPoint(0, 0)).y() - cal.height())
        pos.setX(max(screen.left(), min(pos.x(), screen.right() - cal.width())))
        cal.move(pos)
        cal.show()
        cal.setFocus()

    def hidePopup(self) -> None:
        if self._calendar is not None:
            self._calendar.hide()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.lineEdit():
            if event.type() == QEvent.Type.FocusIn:
                QTimer.singleShot(0, obj.selectAll)
            elif event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._commit()
                    obj.selectAll()
                    return True
                if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    self._commit()
                    self.setDate(self._date.addDays(-1 if key == Qt.Key.Key_Up else 1))
                    obj.selectAll()
                    return True
        return super().eventFilter(obj, event)

    def _picked(self, d: QDate) -> None:
        self.hidePopup()
        self.setDate(d)

    SHORT_FORMAT = "yyyy/MM/dd"

    def _fmt(self) -> str:
        return self.SHORT_FORMAT if getattr(self, "_short", False) else self.FORMAT

    def _show_date(self) -> None:
        self.lineEdit().setText(self.locale().toString(self._date, self._fmt()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 欄位太窄時省略星期，日期本身不會被截斷
        short = self.width() < self.fontMetrics().horizontalAdvance("2026/12/31（週四）") + 44
        if short != getattr(self, "_short", False) and not self.lineEdit().hasFocus():
            self._commit()
            self._short = short
            self._show_date()

    def _commit(self) -> None:
        text = self.lineEdit().text()
        if text == self.locale().toString(self._date, self._fmt()):
            return
        d = parse_date_text(text)
        if d is None:
            # 還原並以對話框提醒：對話框會攔下這次點擊，避免用舊日期直接儲存
            self._show_date()
            warn(self.window(), f"「{text}」不是有效的日期，已還原為 {self.lineEdit().text()}。\n"
                                "請重新輸入，例如 2026/11/5、115/11/5 或 1151105。")
            return
        self.setDate(d)


def make_date_edit(value: str | None = None) -> DateEdit:
    return DateEdit(value)


# ---------------------------------------------------------------------- 卡片
def shadow(widget: QWidget, blur: int = 30, alpha: int = 18) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, 6)
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


class FitLabel(QLabel):
    """單行文字放不下時自動縮小字型（最小到原本的 60%），不會被截斷。"""
    autoshrink = True

    def minimumSizeHint(self):
        h = super().minimumSizeHint()
        h.setWidth(0)
        return h

    def paintEvent(self, e):
        text = self.text()
        r = self.contentsRect()
        fm = self.fontMetrics()
        if not text or fm.horizontalAdvance(text) <= r.width():
            return super().paintEvent(e)
        f = self.font()
        size = f.pointSizeF()
        lo = size * 0.6
        while size > lo and QFontMetrics(_resized(f, size)).horizontalAdvance(text) > r.width():
            size -= 0.5
        p = QPainter(self)
        p.setFont(_resized(f, size))
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(r, int(self.alignment()) | Qt.AlignmentFlag.AlignVCenter, text)


def _resized(f: QFont, size: float) -> QFont:
    g = QFont(f)
    g.setPointSizeF(max(1.0, size))
    return g


class ResponsiveRow(QWidget):
    """左右兩組元件：寬度足夠時排成一列，不夠時右側那組換到第二列（靠右），避免文字或按鈕被壓縮截斷。"""

    def __init__(self, left: list, right: list, spacing: int = 18, parent=None, wrap_left: bool = False,
                 tail: list | None = None):
        super().__init__(parent)
        self._left, self._right = left, right
        self._tail = tail or []          # 一律放在第一列最右邊（例如「刪除」按鈕）
        self._wrap_left = wrap_left      # 換到第二列時靠左（預設靠右）
        self._spacing = spacing
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(8)
        self._row1 = QHBoxLayout()
        self._row2 = QHBoxLayout()
        self._row1.setSpacing(spacing)
        self._row2.setSpacing(spacing)
        self._v.addLayout(self._row1)
        self._v.addLayout(self._row2)
        self._two = None
        self._arrange(False)

    def _items(self, items: list, minimum: bool = False) -> int:
        ws = [w[0] if isinstance(w, tuple) else w for w in items]
        ws = [w for w in ws if isinstance(w, QWidget) and not w.isHidden()]
        return sum((w.minimumSizeHint() if minimum else w.sizeHint()).width() for w in ws) + sum(w for w in items if isinstance(w, int)) \
            + self._spacing * max(0, len(ws) - 1)

    def _arrange(self, two: bool) -> None:
        if two == self._two:
            return
        self._two = two
        for lay in (self._row1, self._row2):
            while lay.count():
                lay.takeAt(0)
        def put(lay, w):
            if isinstance(w, tuple):
                lay.addWidget(w[0], w[1])
            elif isinstance(w, QWidget):
                lay.addWidget(w)
            elif w == "stretch":
                lay.addStretch()
            else:
                lay.addSpacing(w)
        for w in self._left:
            put(self._row1, w)
        grow = any(isinstance(w, tuple) for w in self._left + self._right)
        if "stretch" not in self._left and not (grow and not two) and (two or not self._tail) \
                and not any(isinstance(w, tuple) for w in self._left):
            self._row1.addStretch()
        target = self._row2 if two else self._row1
        if two:
            if not any(isinstance(w, tuple) for w in self._right) and "stretch" not in self._right \
                    and not self._wrap_left:
                self._row2.addStretch()
        else:
            self._row1.addSpacing(self._spacing)
        for w in self._right:
            put(target, w)
        if two and self._wrap_left:
            self._row2.addStretch()
        if self._tail:
            if not two and "stretch" not in self._right:
                self._row1.addStretch()
            for w in self._tail:
                put(self._row1, w)
        self.updateGeometry()

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        w = max(self._items(self._left, True) + self._items(self._tail, True), self._items(self._right, True))
        return QSize(w, super().minimumSizeHint().height())

    def relayout(self) -> None:
        """依目前寬度決定排成一列或兩列（右側元件全部隱藏時一律一列）。"""
        right = [w[0] if isinstance(w, tuple) else w for w in self._right]
        if not any(isinstance(w, QWidget) and not w.isHidden() for w in right):
            self._arrange(False)
            return
        need = self._items(self._left) + self._items(self._right) + self._items(self._tail) + 40
        self._arrange(need > self.width())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.relayout)

    def showEvent(self, e):
        super().showEvent(e)
        self.relayout()


class FitTabWidget(QTabWidget):
    """分頁標籤太多、視窗較窄時，先縮小標籤間距，再略縮字型，盡量讓所有分頁標籤都看得到。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)
        self._style = None
        QTimer.singleShot(0, self._fit)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.FontChange:
            QTimer.singleShot(0, self._fit)

    def tabInserted(self, index):
        super().tabInserted(index)
        QTimer.singleShot(0, self._fit)

    def _fit(self) -> None:
        bar = self.tabBar()
        n = bar.count()
        if not n or self.width() <= 0:
            return
        from PySide6.QtWidgets import QApplication
        base = QApplication.font().pointSizeF()
        avail = self.width() - 8
        style = None
        for size in (base * 1.15, base, base * 0.92):
            f = QFont(QApplication.font())
            f.setPointSizeF(size)
            f.setBold(True)
            fm = QFontMetrics(f)
            text = sum(fm.horizontalAdvance(bar.tabText(i)) for i in range(n))
            pad = (avail - text - 2 * n) / (2 * n)
            if pad >= 16 and size == base * 1.15:
                style = ""
                break
            if pad >= 6:
                style = f"QTabBar::tab {{ padding: 10px {int(min(pad, 16))}px; font-size: {size:.2f}pt; }}"
                break
        if style is None:
            style = f"QTabBar::tab {{ padding: 10px 6px; font-size: {base * 0.92:.2f}pt; }}"
        if style != self._style:
            self._style = style
            bar.setStyleSheet(style)


class StatCard(Card):
    """統計卡片：左上角是彩色圖示，下方是標題、數字與補充說明。hero=True 為主色漸層的重點卡片。"""

    def __init__(self, title: str, accent: str = C.primary, parent=None, icon_name: str = "dollar",
                 hero: bool = False):
        super().__init__(parent, padding=18)
        self.hero = hero
        if hero:
            self.setObjectName("HeroCard")
            shadow(self, 34, 60)
            self.graphicsEffect().setColor(QColor(48, 86, 211, 70))
        self.setMinimumWidth(148)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.badge = QLabel()
        self.badge.setFixedSize(34, 34)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_name = icon_name
        self.title = FitLabel(title)
        self.title.setObjectName("StatTitle")
        top.addWidget(self.badge)
        top.addWidget(self.title, 1)
        self.value = FitLabel("—")
        self.value.setObjectName("StatValue")
        self.sub = FitLabel("")
        self.sub.setObjectName("StatSub")
        self.sub.setToolTip("")
        self.lay.setSpacing(6)
        self.lay.addLayout(top)
        self.lay.addSpacing(2)
        self.lay.addWidget(self.value)
        self.lay.addWidget(self.sub)
        self.set_accent(accent)

    def _fits_badge(self) -> bool:
        need = self.badge.width() + 10 + self.title.fontMetrics().horizontalAdvance(self.title.text()) + 40
        return self.width() >= need

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 卡片太窄時隱藏圖示，把空間留給標題；同一排的卡片一起顯示或隱藏，高度才一致
        par = self.parentWidget()
        row = [c for c in par.findChildren(StatCard) if c.parentWidget() is par and abs(c.y() - self.y()) < 4] \
            if par else [self]
        show = all(c._fits_badge() for c in row)
        for c in row:
            if c.badge.isVisibleTo(c) != show:
                c.badge.setVisible(show)

    def set_accent(self, color: str) -> None:
        from .theme import icon as _icon, soft
        fg, bg = ("#FFFFFF", "rgba(255, 255, 255, 46)") if self.hero else (color, soft(color, 0.12))
        self.badge.setStyleSheet(f"background:{bg}; border-radius:10px;")
        self.badge.setPixmap(_icon(self._icon_name, fg, 40).pixmap(19, 19))

    def set_money(self, amount: float, code: str, sub: str = "", color: str | None = None) -> None:
        from .animations import CountUp
        from .theme import fmt_money
        if not hasattr(self, "_counter"):
            self._counter = CountUp(self.value, lambda v: fmt_money(v, code), self)
        self._counter.formatter = lambda v: fmt_money(v, code)
        self.value.setStyleSheet(f"color:{color};" if color and not self.hero else "")
        self.sub.setText(sub or " ")
        self._counter.set(amount)

    def set(self, value: str, sub: str = "", color: str | None = None) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{color};" if color and not self.hero else "")
        self.sub.setText(sub or " ")


def page_header(title: str, subtitle: str = "") -> tuple[QWidget, QHBoxLayout]:
    """頁首：第一列是標題與（呼叫端加入的）按鈕，說明文字在下一列占滿整個寬度，按鈕多時也不會被擠壓。"""
    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(2)
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    lay.addStretch()
    outer.addLayout(lay)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        outer.addWidget(s)
    return w, lay


def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("SectionTitle")
    return lbl


def button(text: str, kind: str | None = None, icon=None, tooltip: str = "") -> QPushButton:
    """按鈕。icon 可以是圖示名稱（依按鈕樣式自動配色）或 QIcon。"""
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if isinstance(icon, str):
        from .theme import BUTTON_ICON_COLORS, icon as _icon
        icon = _icon(icon, BUTTON_ICON_COLORS.get(kind or "", C.text))
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
                 width: int | None = None, stretch: bool = False, elide: bool | None = None,
                 badge: bool = False):
        self.title = title
        self.badge = badge      # 以圓角色塊（標籤）顯示，顏色取自 color
        # 備註、說明等長文字：寬度不足時可以省略（滑鼠提示有全文）
        self.elide = elide if elide is not None else title in ("備註", "說明", "摘要", "內容", "說明／備註")
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
    """樣式表會忽略資料列的底色，這裡先自行填上（例如日記帳以傳票分組底色）；
    標籤欄（Column.badge）畫成圓角色塊。"""
    BADGE_PAD = 6

    def _badge(self, index) -> bool:
        cols = getattr(self.parent(), "columns", None)
        return bool(cols) and 0 <= index.column() < len(cols) and cols[index.column()].badge

    def sizeHint(self, option, index):
        h = super().sizeHint(option, index)
        if self._badge(index):
            h.setWidth(h.width() + 2 * self.BADGE_PAD)
        return h

    def paint(self, painter, option, index):
        bg = index.data(Qt.ItemDataRole.BackgroundRole)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if bg is not None and not selected:
            painter.fillRect(option.rect, bg)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not (text and self._badge(index)):
            return super().paint(painter, option, index)
        # 先畫底（選取色、分隔線），再畫標籤
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        w = option.widget
        (w.style() if w else QApplication.style()).drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, w)
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        color = brush.color() if brush is not None else QColor(C.muted)
        f = QFont(option.font)
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 0.88)
        fm = QFontMetrics(f)
        tw = fm.horizontalAdvance(text) + 2 * self.BADGE_PAD
        th = fm.height() + 4
        r = option.rect
        align = index.data(Qt.ItemDataRole.TextAlignmentRole) or 0
        if int(align) & int(Qt.AlignmentFlag.AlignHCenter):
            x = r.x() + (r.width() - tw) // 2
        elif int(align) & int(Qt.AlignmentFlag.AlignRight):
            x = r.right() - tw - 6
        else:
            x = r.x() + 6
        pill = QRectF(max(r.x() + 2, x), r.y() + (r.height() - th) / 2, min(tw, r.width() - 4), th)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        soft = QColor(color)
        soft.setAlpha(30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(soft)
        painter.drawRoundedRect(pill, th / 2, th / 2)
        painter.setPen(color)
        painter.setFont(f)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class DataTable(QTableView):
    """美化過的表格，含排序與欄寬設定。"""

    rowActivated = Signal(dict)
    STRETCH_CAP = 260      # 名稱類伸縮欄最多保留的寬度
    ELIDE_WIDTH = 120      # 備註、說明類伸縮欄寬度不足時的最小寬度（其餘以「…」表示）

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
        self.columns = columns
        for i, col in enumerate(columns):
            if col.stretch:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            elif col.width:
                self.setColumnWidth(i, col.width)
        self.doubleClicked.connect(self._activated)
        self.fit_columns()

    def set_rows(self, rows: list[dict]) -> None:
        self.model_.set_rows(rows)
        self.fit_columns()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self.fit_columns)

    def showEvent(self, e):
        super().showEvent(e)
        self.fit_columns()

    def fit_columns(self) -> None:
        """依目前字型計算每欄需要的寬度：日期、金額、名稱不截斷；備註類（elide）可省略並以滑鼠提示全文。"""
        self.ensurePolished()
        font = self.font()
        bold = QFont(font)
        bold.setBold(True)
        fm, bfm = QFontMetrics(font), QFontMetrics(bold)
        self.model_._bold = bold        # 粗體列跟著目前字型大小（設定 → 字型大小變更後）
        self._need: dict[int, int] = {}
        self.verticalHeader().setResizeContentsPrecision(300)   # 依前 300 列估計欄寬
        for i, col in enumerate(self.columns):
            if self.indexWidget(self.model().index(0, i)) is not None:
                continue
            # 內容寬度以 Qt 實際繪製時的需求為準（含樣式表的內距），再留 4px，避免被畫成「…」
            content = self.sizeHintForColumn(i) + 4 if self.model_.rows else 0
            need = max(bfm.horizontalAdvance(col.title) + 22, content)
            if col.stretch:
                need = max(110, min(need, self.ELIDE_WIDTH if col.elide else self.STRETCH_CAP))
            self._need[i] = need
        self.horizontalHeader().setMinimumSectionSize(36)
        self._layout_columns()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_columns()

    def _layout_columns(self) -> None:
        """寬度足夠：固定欄用設定寬度、伸縮欄占其餘空間。不夠：固定欄縮到剛好放得下內容；
        仍不夠才讓伸縮欄維持最小寬度並以水平捲動，不把文字擠到看不見。"""
        need = getattr(self, "_need", None)
        if need is None:
            return
        hh = self.horizontalHeader()
        cols = [i for i in range(len(self.columns)) if not self.isColumnHidden(i) and i in need]
        fixed = [i for i in cols if not self.columns[i].stretch]
        stretch = [i for i in cols if self.columns[i].stretch]
        pref = {i: max(self.columns[i].width or 0, need[i]) for i in fixed}
        room = self.viewport().width()
        s_need = sum(need[i] for i in stretch)
        if sum(pref.values()) + s_need <= room:
            widths = pref
        else:   # 介於「剛好放得下內容」與設定寬度之間，依可用空間等比例分配
            extra = sum(pref[i] - need[i] for i in fixed)
            f = max(0.0, min(1.0, (room - s_need - sum(need[i] for i in fixed)) / extra)) if extra else 0.0
            widths = {i: int(need[i] + (pref[i] - need[i]) * f) for i in fixed}
        for i, w in widths.items():
            if self.columnWidth(i) != w:
                self.setColumnWidth(i, w)
        squeeze = sum(widths.values()) + s_need > room
        # 同時有名稱欄與備註欄時，名稱欄固定為內容寬度，剩餘空間給備註欄（避免平分後名稱被截斷）
        notes = [i for i in stretch if self.columns[i].elide]
        for i in stretch:
            fixed_w = squeeze or (notes and i not in notes)
            mode = QHeaderView.ResizeMode.Interactive if fixed_w else QHeaderView.ResizeMode.Stretch
            if hh.sectionResizeMode(i) != mode:
                hh.setSectionResizeMode(i, mode)
            if fixed_w and self.columnWidth(i) != need[i]:
                self.setColumnWidth(i, need[i])

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
