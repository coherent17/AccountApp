"""動畫效果：按鈕漣漪、頁面轉場、側邊欄指示條、數字滾動、提示訊息。"""

from __future__ import annotations

import math

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint,
                            QPointF, QPropertyAnimation, QRect, QRectF,
                            QSequentialAnimationGroup, Qt, QTimer, QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QWidget)

from .theme import C

ENABLED = True


def set_enabled(on: bool) -> None:
    """設定是否啟用動畫（設定頁的「動畫效果」開關）。"""
    global ENABLED
    ENABLED = bool(on)


_DARK_BUTTONS = {"Primary", "Income", "Expense", "Transfer", "Adjust", "SidebarExport",
                 "NavButton"}


# ---------------------------------------------------------------------- 漣漪
class Ripple(QWidget):
    """按下按鈕時，自點擊位置擴散的半透明圓形。"""

    def __init__(self, target: QWidget, pos: QPoint):
        super().__init__(target)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(target.rect())
        self.center = QPointF(pos)
        name = target.objectName()
        dark = name in _DARK_BUTTONS or (name == "Segment" and target.isChecked())
        self.color = QColor("#FFFFFF") if dark else QColor(C.primary)
        self.peak = 0.32 if dark else 0.18
        self.radius_corner = 16 if name == "Chip" else (10 if name in ("NavButton", "Segment",
                                                                       "SidebarExport") else 9)
        corners = [QPointF(0, 0), QPointF(self.width(), 0), QPointF(0, self.height()),
                   QPointF(self.width(), self.height())]
        self.max_r = max(math.hypot(c.x() - self.center.x(), c.y() - self.center.y()) for c in corners)
        self.t = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setDuration(520)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._tick)
        self.anim.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self.anim.start()

    def _tick(self, v) -> None:
        self.t = float(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.radius_corner, self.radius_corner)
        p.setClipPath(clip)
        c = QColor(self.color)
        c.setAlphaF(self.peak * (1 - self.t) ** 1.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        r = 6 + self.max_r * self.t
        p.drawEllipse(self.center, r, r)


class RippleFilter(QObject):
    """安裝在 QApplication 上，所有按鈕都會有漣漪效果。"""

    def eventFilter(self, obj, ev):
        if ENABLED and ev.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QAbstractButton) \
                and obj.isEnabled() and ev.button() == Qt.MouseButton.LeftButton:
            Ripple(obj, ev.position().toPoint())
        return False


# ---------------------------------------------------------------------- 頁面轉場
def page_transition(stack, new: QWidget, owner: QObject) -> None:
    """「淡出再淡入」轉場：舊頁面快速淡出，新頁面由右側滑入並淡入。

    轉場過程使用畫面快照，結束後才顯示真正的頁面，確保流暢不閃爍。
    """
    old = stack.currentWidget()
    if not ENABLED or old is None or old is new or not stack.isVisible():
        stack.setCurrentWidget(new)
        return
    prev = getattr(owner, "_page_anim", None)
    if prev is not None:
        prev.stop()
        for w in getattr(owner, "_page_overlays", []):
            w.deleteLater()
    old_pm = old.grab()
    stack.setCurrentWidget(new)
    new.setGeometry(stack.rect())
    QApplication.sendPostedEvents(None, 0)
    if new.layout():
        new.layout().activate()
    QApplication.sendPostedEvents(None, 0)
    new_pm = new.grab()
    geo = new.geometry()

    cover = QFrame(stack)
    cover.setStyleSheet(f"background: {C.bg};")
    cover.setGeometry(geo)
    old_lbl = QLabel(cover)
    old_lbl.setPixmap(old_pm)
    old_lbl.setGeometry(0, 0, geo.width(), geo.height())
    new_lbl = QLabel(cover)
    new_lbl.setPixmap(new_pm)
    new_lbl.setGeometry(0, 0, geo.width(), geo.height())
    for w in (cover, old_lbl, new_lbl):
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    e_old = QGraphicsOpacityEffect(old_lbl)
    old_lbl.setGraphicsEffect(e_old)
    e_new = QGraphicsOpacityEffect(new_lbl)
    e_new.setOpacity(0.0)
    new_lbl.setGraphicsEffect(e_new)
    cover.show()
    cover.raise_()

    fade_out = QPropertyAnimation(e_old, b"opacity")
    fade_out.setDuration(130)
    fade_out.setStartValue(1.0)
    fade_out.setEndValue(0.0)
    fade_out.setEasingCurve(QEasingCurve.Type.OutQuad)
    fade_in = QPropertyAnimation(e_new, b"opacity")
    fade_in.setDuration(300)
    fade_in.setStartValue(0.0)
    fade_in.setEndValue(1.0)
    fade_in.setEasingCurve(QEasingCurve.Type.OutQuad)
    slide = QPropertyAnimation(new_lbl, b"pos")
    slide.setDuration(340)
    slide.setStartValue(QPoint(40, 0))
    slide.setEndValue(QPoint(0, 0))
    slide.setEasingCurve(QEasingCurve.Type.OutCubic)
    enter = QParallelAnimationGroup()
    enter.addAnimation(fade_in)
    enter.addAnimation(slide)
    seq = QSequentialAnimationGroup(owner)
    seq.addAnimation(fade_out)
    seq.addAnimation(enter)

    def done():
        cover.deleteLater()
        owner._page_overlays = []
    seq.finished.connect(done)
    owner._page_anim = seq
    owner._page_overlays = [cover]
    seq.start()


# ---------------------------------------------------------------------- 側邊欄指示條
class NavIndicator(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("NavIndicator")
        self.setStyleSheet(f"#NavIndicator {{ background: {C.primary}; border-radius: 2px; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.anim = QPropertyAnimation(self, b"geometry", self)
        self.anim.setDuration(420)
        self.anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self.hide()

    def move_to(self, button: QWidget, animate: bool = True) -> None:
        g = button.geometry()
        if g.height() <= 0:
            return
        target = QRect(g.x() + 2, g.y() + 10, 4, g.height() - 20)
        self.raise_()
        if not self.isVisible() or not animate or not ENABLED:
            self.setGeometry(target)
            self.show()
            return
        self.anim.stop()
        self.anim.setStartValue(self.geometry())
        self.anim.setEndValue(target)
        self.anim.start()


# ---------------------------------------------------------------------- 數字滾動
class CountUp(QObject):
    """讓數字由舊值平滑滾動到新值。"""

    def __init__(self, label: QLabel, formatter, parent=None):
        super().__init__(parent or label)
        self.label = label
        self.formatter = formatter
        self.value: float | None = None
        self.delay = 420  # 等頁面轉場結束後才開始滾動
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(900)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(lambda v: self.label.setText(self.formatter(float(v))))

    def set(self, value: float) -> None:
        start = self.value if self.value is not None else 0.0
        self.value = value
        if abs(start - value) < 0.005 or not ENABLED:
            self.anim.stop()
            self.label.setText(self.formatter(value))
            return
        self.anim.stop()
        self.anim.setStartValue(float(start))
        self.anim.setEndValue(float(value))
        self.label.setText(self.formatter(start))
        QTimer.singleShot(self.delay, self.anim.start)


# ---------------------------------------------------------------------- 視窗淡入
def fade_in_window(w: QWidget, duration: int = 200) -> None:
    if not ENABLED:
        w.setWindowOpacity(1.0)
        return
    w.setWindowOpacity(0.0)
    anim = QPropertyAnimation(w, b"windowOpacity", w)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutQuad)
    w._fade_anim = anim
    anim.start()


def animate_progress(bar, target: int, owner: QObject, delay: int = 0) -> None:
    if not ENABLED:
        bar.setValue(target)
        return
    bar.setValue(0)
    anim = QPropertyAnimation(bar, b"value", owner)
    anim.setDuration(900)
    anim.setStartValue(0)
    anim.setEndValue(target)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    owner._bar_anims = getattr(owner, "_bar_anims", [])
    owner._bar_anims.append(anim)
    QTimer.singleShot(delay, anim.start)


# ---------------------------------------------------------------------- 提示訊息
class Toast(QFrame):
    """右上角滑入、自動淡出的成功提示。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setStyleSheet(
            f"#Toast {{ background: {C.toast}; border-radius: 12px; }}"
            f"#Toast QLabel {{ color: white; background: transparent; font-weight: 700; }}"
            f"#ToastIcon {{ background: {C.income}; border-radius: 13px; color: white; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 20, 10)
        lay.setSpacing(10)
        self.icon = QLabel("✓")
        self.icon.setObjectName("ToastIcon")
        self.icon.setFixedSize(26, 26)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel()
        lay.addWidget(self.icon)
        lay.addWidget(self.text)
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.hide()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._out)
        self.group: QParallelAnimationGroup | None = None

    def show_message(self, text: str) -> None:
        self.text.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        x = par.width() - self.width() - 28
        end = QPoint(x, 24)
        self.move(end - QPoint(0, 30))
        self.show()
        self.raise_()
        if not ENABLED:
            self.move(end)
            self.eff.setOpacity(1.0)
            self.timer.start(2200)
            return
        self._animate(end - QPoint(0, 30), end, 0.0, 1.0, 380, QEasingCurve.Type.OutBack)
        self.timer.start(2200)

    def _out(self) -> None:
        if not ENABLED:
            self.hide()
            return
        self._animate(self.pos(), self.pos() - QPoint(0, 16), 1.0, 0.0, 300,
                      QEasingCurve.Type.InQuad, hide=True)

    def _animate(self, p1, p2, o1, o2, ms, curve, hide=False) -> None:
        if self.group:
            self.group.stop()
        g = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"pos", g)
        a.setDuration(ms)
        a.setStartValue(p1)
        a.setEndValue(p2)
        a.setEasingCurve(curve)
        b = QPropertyAnimation(self.eff, b"opacity", g)
        b.setDuration(ms)
        b.setStartValue(o1)
        b.setEndValue(o2)
        g.addAnimation(a)
        g.addAnimation(b)
        if hide:
            g.finished.connect(self.hide)
        self.group = g
        g.start()
