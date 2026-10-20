from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

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
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(inner)
            outer.addWidget(area)
        else:
            outer.addWidget(inner)
        ctx.dataChanged.connect(self.mark_dirty)
        ctx.settingsChanged.connect(self.mark_dirty)

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
