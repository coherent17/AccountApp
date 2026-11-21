from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..context import AppContext


class Page(QWidget):
    """所有頁面的基底：資料變更時標記，等頁面顯示時才重新整理。"""

    title = ""

    def __init__(self, ctx: AppContext, scroll: bool = True, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.db = ctx.db
        self._dirty = True
        self.setObjectName("PageRoot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setObjectName("PageRoot")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(32, 26, 32, 26)
        self.body.setSpacing(18)
        self._scroll = scroll
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(inner)
            outer.addWidget(area)
        else:
            outer.addWidget(inner)
        ctx.dataChanged.connect(self.mark_dirty)
        ctx.settingsChanged.connect(self.mark_dirty)

    COMPACT_HEIGHT = 760     # 頁面比這個矮時，較長的說明文字收成一行（滑鼠移上去看全文）

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self._scroll:
            QTimer.singleShot(0, self._fit_hints)

    def _fit_hints(self, again: bool = True) -> None:
        """視窗較矮時，表格下方的長說明只顯示一行（以「…」結尾，滑鼠提示顯示全文），讓表格有足夠空間。"""
        compact = self.height() < self.COMPACT_HEIGHT
        if again:      # 版面重新排列後再算一次實際寬度
            QTimer.singleShot(50, lambda: self._fit_hints(False))
        for lbl in self.findChildren(QLabel, "Hint"):
            full = lbl.property("fullText")
            if full is None:
                if not lbl.wordWrap() or len(lbl.text()) < 60:
                    continue
                full = lbl.text()
                lbl.setProperty("fullText", full)
            if compact:
                if not lbl.property("compactHook"):
                    lbl.setProperty("compactHook", True)
                    lbl.installEventFilter(self)     # 分頁切換、版面改變時依實際寬度重新縮短
                lbl.setWordWrap(False)
                lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                self._elide(lbl)
                lbl.setToolTip(full)
            elif not lbl.wordWrap():
                lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
                lbl.setWordWrap(True)
                lbl.setText(full)
                lbl.setToolTip("")

    @staticmethod
    def _elide(lbl: QLabel) -> None:
        full = lbl.property("fullText")
        width = lbl.contentsRect().width() if lbl.width() > 50 else 600
        text = lbl.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, max(80, width - 6))
        if text != lbl.text():
            lbl.setText(text)

    def eventFilter(self, obj, e):
        if isinstance(obj, QLabel) and e.type() in (QEvent.Type.Resize, QEvent.Type.Show) \
                and not obj.wordWrap() and obj.property("fullText"):
            self._elide(obj)
        return super().eventFilter(obj, e)

    def mark_dirty(self) -> None:
        self._dirty = True
        if self.isVisible():
            self.refresh()
            self._dirty = False

    def showEvent(self, e):
        super().showEvent(e)
        if self._dirty:
            self.refresh()
            self._dirty = False

    def refresh(self) -> None:  # pragma: no cover - 由子類別實作
        pass

    def apply_filter(self, **kwargs) -> None:
        pass
