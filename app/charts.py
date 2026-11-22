"""QtCharts 圖表：環形圖、長條圖、折線圖。"""

from __future__ import annotations

from PySide6.QtCharts import (QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView,
                              QLineSeries, QPieSeries, QScatterSeries, QValueAxis)
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsView

from .theme import C, FONT_FAMILY


def _font(pt: float, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(pt)
    f.setBold(bold)
    return f


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1
    import math
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * exp:
            return m * exp
    return 10 * exp


class ChartView(QChartView):
    def __init__(self, parent=None, height: int = 280):
        chart = QChart()
        chart.setBackgroundVisible(False)
        chart.setMargins(QMargins(4, 4, 4, 4))
        chart.legend().setFont(_font(10.5))
        chart.legend().setLabelColor(QColor(C.muted))
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.setAnimationDuration(500)
        super().__init__(chart, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 每次都重畫整個圖表：只重畫變動區域時，改變大小後會殘留舊的座標軸（重影）
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)
        self.setMinimumHeight(height)
        self.setStyleSheet("background: transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.viewport().update()

    def reset(self) -> QChart:
        from . import animations
        ch = self.chart()
        ch.setAnimationOptions(QChart.AnimationOption.SeriesAnimations if animations.ENABLED
                               else QChart.AnimationOption.NoAnimation)
        ch.removeAllSeries()
        for ax in ch.axes():
            ch.removeAxis(ax)
            ax.deleteLater()      # 移除的座標軸要刪掉，否則重畫時會留下舊的座標軸（重影）
        return ch


class DonutChart(ChartView):
    def set_data(self, items: list[tuple[str, float]], center_text: str = "") -> None:
        ch = self.reset()
        total = sum(v for _, v in items) or 1
        series = QPieSeries()
        series.setHoleSize(0.62)
        series.setPieSize(0.88)
        for i, (name, v) in enumerate(items):
            sl = series.append(f"{name}  {v / total:.0%}", v)
            sl.setBrush(QColor(C.chart[i % len(C.chart)]))
            sl.setPen(QPen(QColor("white"), 3))
            sl.setLabelVisible(False)
        if not items:
            sl = series.append("尚無資料", 1)
            sl.setBrush(QColor(C.border))
            sl.setPen(QPen(Qt.PenStyle.NoPen))
        ch.addSeries(series)
        ch.legend().setAlignment(Qt.AlignmentFlag.AlignRight)
        ch.legend().setVisible(True)
        ch.setTitle(center_text)
        ch.setTitleFont(_font(10))
        ch.setTitleBrush(QBrush(QColor(C.muted)))


class BarChart(ChartView):
    def set_data(self, labels: list[str], series_data: list[tuple[str, list[float], str]],
                 unit: str | None = None, x_title: str = "月份") -> None:
        ch = self.reset()
        bars = QBarSeries()
        bars.setBarWidth(0.62)
        top = 0.0
        div, auto_unit = _scale([v for _, vals, _ in series_data for v in vals])
        if unit:
            div = 1
        unit = unit or auto_unit
        for name, values, color in series_data:
            values = [float(v) / div for v in values]
            s = QBarSet(name)
            s.append(values)
            s.setColor(QColor(color))
            s.setBorderColor(QColor(color))
            bars.append(s)
            top = max([top] + list(values))
        ch.addSeries(bars)
        ax = QBarCategoryAxis()
        ax.append(labels)
        _style_axis(ax, grid=False)
        if x_title:
            _axis_title(ax, x_title)
        ay = QValueAxis()
        ay.setRange(0, _nice_max(top * 1.08))
        ay.setTickCount(5)
        ay.setLabelFormat("%.0f")
        _style_axis(ay, grid=True)
        ch.addAxis(ax, Qt.AlignmentFlag.AlignBottom)
        ch.addAxis(ay, Qt.AlignmentFlag.AlignLeft)
        bars.attachAxis(ax)
        bars.attachAxis(ay)
        ch.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        ay.setLabelFormat("%.0f" if top >= 10 else "%.1f")
        ch.legend().setVisible(len(series_data) > 1)
        _axis_title(ay, unit)


class LineChart(ChartView):
    def set_data(self, labels: list[str], values: list[float], color: str = C.primary,
                 name: str = "", x_title: str = "月份") -> None:
        ch = self.reset()
        div, unit = _scale(values)
        values = [v / div for v in values]
        line = QLineSeries()
        line.setName(name)
        pen = QPen(QColor(color), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line.setPen(pen)
        dots = QScatterSeries()
        dots.setMarkerSize(9)
        dots.setColor(QColor("white"))
        dots.setBorderColor(QColor(color))
        numeric = len(labels) > 16 and all(str(lb).isdigit() for lb in labels)
        for i, v in enumerate(values):
            x = int(labels[i]) if numeric else i
            line.append(x, v)
            dots.append(x, v)
        ch.addSeries(line)
        ch.addSeries(dots)
        if numeric:
            dots.setMarkerSize(6)
            ax = QValueAxis()
            ax.setRange(int(labels[0]), int(labels[-1]))
            ax.setTickCount(min(8, len(labels)))
            ax.setLabelFormat("%d")
            _style_axis(ax, grid=False)
            _axis_title(ax, x_title)
            labels = []
        else:
            ax = QBarCategoryAxis()
        if not numeric:
            ax.append(labels)
            _style_axis(ax, grid=False)
            _axis_title(ax, x_title)
        lo = min(values) if values else 0
        hi = max(values) if values else 1
        pad = (hi - lo) * 0.15 or abs(hi) * 0.1 or 1
        ay = QValueAxis()
        ay.setRange(lo - pad if lo - pad < 0 or lo > pad * 3 else 0, hi + pad)
        ay.setTickCount(5)
        ay.setLabelFormat("%.0f")
        _style_axis(ay, grid=True)
        ch.addAxis(ax, Qt.AlignmentFlag.AlignBottom)
        ch.addAxis(ay, Qt.AlignmentFlag.AlignLeft)
        for s in (line, dots):
            s.attachAxis(ax)
            s.attachAxis(ay)
        ay.setLabelFormat("%.0f" if hi - lo >= 10 else "%.1f")
        ch.legend().setVisible(False)
        _axis_title(ay, unit)


def _scale(values: list[float]) -> tuple[float, str]:
    top = max([abs(v) for v in values] + [0])
    if top >= 1e5:
        return 1e4, "單位：萬元"
    return 1, "單位：元"


def _style_axis(axis, grid: bool) -> None:
    axis.setLabelsFont(_font(9))
    axis.setLabelsColor(QColor(C.muted))
    axis.setGridLineVisible(grid)
    if grid:
        pen = QPen(QColor(C.border), 1, Qt.PenStyle.DashLine)
        axis.setGridLinePen(pen)
        axis.setLineVisible(False)
    else:
        axis.setLinePenColor(QColor(C.border_strong))


def _axis_title(ay, text: str) -> None:
    ay.setTitleText(text)
    ay.setTitleFont(_font(9))
    ay.setTitleBrush(QBrush(QColor(C.muted)))


__all__ = ["DonutChart", "BarChart", "LineChart"]
