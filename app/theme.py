"""外觀：配色、字型大小、樣式表、向量圖示與數字格式。"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .database import CURRENCIES, ZERO_DECIMAL_CURRENCIES

FONT_FAMILY = "Microsoft JhengHei UI"
FONT_FALLBACKS = ["Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC",
                  "Noto Sans CJK TC", "Noto Sans TC", "sans-serif"]

FONT_SCALES = {
    "normal": ("標準", 11),
    "large": ("大", 12.5),
    "xlarge": ("特大", 14),
}


class C:
    bg = "#F3F5F9"
    surface = "#FFFFFF"
    surface_alt = "#F8FAFC"
    border = "#E3E8EF"
    border_strong = "#CBD3DF"
    text = "#1E293B"
    muted = "#64748B"
    faint = "#94A3B8"
    sidebar = "#1C2840"
    sidebar_hover = "#26355A"
    sidebar_active = "#2F4372"
    sidebar_text = "#C3CDE2"
    primary = "#2563EB"
    primary_hover = "#1D4FD8"
    primary_soft = "#E8F0FE"
    income = "#0F9D6E"
    income_soft = "#E3F6EF"
    expense = "#E0464B"
    expense_soft = "#FDECEC"
    transfer = "#5B6B82"
    transfer_soft = "#EDF1F6"
    adjust = "#7C4DDB"
    adjust_soft = "#F1EBFD"
    gold = "#D99A1E"
    chart = ["#2563EB", "#0F9D6E", "#F59E0B", "#E0464B", "#7C4DDB", "#0EA5B7",
             "#EC4899", "#84CC16", "#64748B", "#F97316", "#14B8A6", "#A855F7"]


TYPE_COLORS = {
    "income": (C.income, C.income_soft),
    "expense": (C.expense, C.expense_soft),
    "transfer": (C.transfer, C.transfer_soft),
    "adjust": (C.adjust, C.adjust_soft),
    "journal": (C.primary, C.primary_soft),
}


def stylesheet(pt: float, arrow: str = "") -> str:
    s = pt
    big = s * 1.15
    return f"""
    * {{ font-family: "{FONT_FAMILY}", "Microsoft JhengHei"; font-size: {s}pt; color: {C.text}; }}
    QMainWindow, QDialog, #PageRoot {{ background: {C.bg}; }}
    QToolTip {{ background: {C.text}; color: white; border: none; padding: 6px 8px; border-radius: 6px; }}

    /* ---------- 側邊欄 ---------- */
    #Sidebar {{ background: {C.sidebar}; }}
    #Sidebar QLabel {{ color: {C.sidebar_text}; background: transparent; }}
    #AppTitle {{ color: white; font-size: {s * 1.35}pt; font-weight: 700; }}
    #AppSubtitle {{ color: {C.faint}; font-size: {s * 0.85}pt; }}
    #NavButton {{
        background: transparent; color: {C.sidebar_text}; border: none; text-align: left;
        padding: 12px 18px; border-radius: 10px; font-size: {big}pt;
    }}
    #NavButton:hover {{ background: {C.sidebar_hover}; color: white; }}
    #NavButton:checked {{ background: {C.sidebar_active}; color: white; font-weight: 700; }}
    #SidebarExport {{
        background: {C.income}; color: white; border: none; border-radius: 10px;
        padding: 12px 14px; font-weight: 700; font-size: {s}pt;
    }}
    #SidebarExport:hover {{ background: #0B8A60; }}
    #SidebarFoot {{ color: {C.faint}; font-size: {s * 0.8}pt; }}

    /* ---------- 頁面 ---------- */
    #PageTitle {{ font-size: {s * 1.75}pt; font-weight: 700; color: {C.text}; }}
    #PageSubtitle {{ color: {C.muted}; font-size: {s}pt; }}
    #SectionTitle {{ font-size: {s * 1.2}pt; font-weight: 700; color: {C.text}; }}
    #Muted {{ color: {C.muted}; }}
    #Hint {{ color: {C.muted}; font-size: {s * 0.9}pt; }}

    #Card {{ background: {C.surface}; border: 1px solid {C.border}; border-radius: 14px; }}
    #Card QLabel {{ background: transparent; }}
    #StatTitle {{ color: {C.muted}; font-size: {s * 0.95}pt; }}
    #StatValue {{ font-size: {s * 1.7}pt; font-weight: 700; }}
    #StatSub {{ color: {C.faint}; font-size: {s * 0.85}pt; }}

    /* ---------- 按鈕 ---------- */
    QPushButton {{
        background: {C.surface}; border: 1px solid {C.border_strong}; border-radius: 9px;
        padding: 8px 16px; min-height: 22px;
    }}
    QPushButton:hover {{ background: {C.surface_alt}; border-color: {C.primary}; }}
    QPushButton:pressed {{ background: {C.primary_soft}; }}
    QPushButton:disabled {{ color: {C.faint}; background: {C.surface_alt}; border-color: {C.border}; }}
    QPushButton#Primary {{ background: {C.primary}; color: white; border: none; font-weight: 700; }}
    QPushButton#Primary:hover {{ background: {C.primary_hover}; }}
    QPushButton#Income {{ background: {C.income}; color: white; border: none; font-weight: 700; }}
    QPushButton#Income:hover {{ background: #0B8A60; }}
    QPushButton#Expense {{ background: {C.expense}; color: white; border: none; font-weight: 700; }}
    QPushButton#Expense:hover {{ background: #C93A3F; }}
    QPushButton#Transfer {{ background: {C.transfer}; color: white; border: none; font-weight: 700; }}
    QPushButton#Transfer:hover {{ background: #4A586C; }}
    QPushButton#Adjust {{ background: {C.adjust}; color: white; border: none; font-weight: 700; }}
    QPushButton#Adjust:hover {{ background: #6A3CC8; }}
    QPushButton#Danger {{ color: {C.expense}; border-color: #F3B7B9; }}
    QPushButton#Danger:hover {{ background: {C.expense_soft}; border-color: {C.expense}; }}
    QPushButton#Link {{ background: transparent; border: none; color: {C.primary}; padding: 4px 6px; }}
    QPushButton#Link:hover {{ text-decoration: underline; }}

    QPushButton#Segment {{
        background: {C.surface_alt}; border: 1px solid {C.border}; border-radius: 10px;
        padding: 10px 6px; font-size: {big}pt; color: {C.muted};
    }}
    QPushButton#Segment:checked {{ color: white; font-weight: 700; border: none; }}
    QPushButton#Segment[ttype="expense"]:checked {{ background: {C.expense}; }}
    QPushButton#Segment[ttype="income"]:checked {{ background: {C.income}; }}
    QPushButton#Segment[ttype="transfer"]:checked {{ background: {C.transfer}; }}

    QPushButton#Chip {{
        background: {C.surface}; border: 1px solid {C.border}; border-radius: 16px;
        padding: 7px 10px; color: {C.text};
    }}
    QPushButton#Chip:hover {{ border-color: {C.primary}; }}
    QPushButton#Chip:checked {{ background: {C.primary_soft}; border: 2px solid {C.primary};
        color: {C.primary}; font-weight: 700; }}

    /* ---------- 輸入 ---------- */
    QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
        background: {C.surface}; border: 1px solid {C.border_strong}; border-radius: 8px;
        padding: 7px 10px; min-height: 22px; selection-background-color: {C.primary};
        selection-color: white;
    }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QPlainTextEdit:focus {{ border: 2px solid {C.primary}; padding: 6px 9px; }}
    QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled {{ background: {C.surface_alt}; color: {C.muted}; }}
    QLineEdit#AmountEdit {{ font-size: {s * 1.6}pt; font-weight: 700; padding: 8px 12px; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button,
    QDoubleSpinBox::down-button {{ width: 0; border: none; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 30px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({arrow}); width: 14px; height: 14px; }}
    QComboBox::down-arrow:on {{ top: 1px; }}
    QComboBox QAbstractItemView {{
        background: white; border: 1px solid {C.border_strong}; outline: none;
        selection-background-color: {C.primary_soft}; selection-color: {C.text}; padding: 4px;
    }}
    QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 2px 8px; }}
    QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; padding: 4px 10px 4px 0; }}
    QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 10px;
        border: 2px solid {C.border_strong}; background: white; }}
    QRadioButton::indicator:hover {{ border-color: {C.primary}; }}
    QRadioButton::indicator:checked {{ border: 6px solid {C.primary}; width: 8px; height: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px;
        border: 2px solid {C.border_strong}; background: white; }}
    QCheckBox::indicator:hover {{ border-color: {C.primary}; }}
    QCheckBox::indicator:checked {{ background: {C.primary}; border: 4px solid {C.primary_soft};
        width: 12px; height: 12px; }}

    QCalendarWidget QWidget {{ alternate-background-color: {C.surface_alt}; }}
    QCalendarWidget QToolButton {{ color: {C.text}; background: transparent; padding: 6px;
        font-weight: 700; border-radius: 6px; }}
    QCalendarWidget QToolButton:hover {{ background: {C.primary_soft}; }}
    QCalendarWidget #qt_calendar_navigationbar {{ background: {C.surface}; border-bottom: 1px solid {C.border}; }}
    QCalendarWidget QAbstractItemView {{ selection-background-color: {C.primary}; selection-color: white;
        font-size: {s}pt; }}

    /* ---------- 表格 ---------- */
    QTableView, QTreeWidget, QListWidget {{
        background: {C.surface}; border: 1px solid {C.border}; border-radius: 12px;
        gridline-color: transparent; alternate-background-color: {C.surface_alt};
        selection-background-color: {C.primary_soft}; selection-color: {C.text}; outline: none;
    }}
    QTableView::item, QTreeWidget::item {{ padding: 6px 8px; border-bottom: 1px solid #EEF1F5; }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
    QListWidget::item:selected {{ background: {C.primary_soft}; color: {C.text}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        background: {C.surface_alt}; color: {C.muted}; border: none;
        border-bottom: 1px solid {C.border}; padding: 9px 8px; font-weight: 700;
    }}
    QTableCornerButton::section {{ background: {C.surface_alt}; border: none; }}

    /* ---------- 分頁 ---------- */
    QTabWidget::pane {{ border: none; background: transparent; top: -1px; }}
    QTabBar::tab {{
        background: transparent; color: {C.muted}; padding: 10px 16px; margin-right: 2px;
        border: none; border-bottom: 3px solid transparent; font-size: {big}pt;
    }}
    QTabBar::tab:selected {{ color: {C.primary}; border-bottom: 3px solid {C.primary}; font-weight: 700; }}
    QTabBar::tab:hover {{ color: {C.text}; }}

    /* ---------- 捲軸 ---------- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {C.border_strong}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {C.faint}; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {C.border_strong}; border-radius: 4px; min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QProgressBar {{ background: {C.surface_alt}; border: none; border-radius: 6px; height: 12px;
        text-align: center; font-size: {s * 0.8}pt; color: transparent; }}
    QProgressBar::chunk {{ background: {C.primary}; border-radius: 6px; }}
    QProgressBar[over="true"]::chunk {{ background: {C.expense}; }}

    QMessageBox {{ background: {C.surface}; }}
    QMessageBox QLabel {{ font-size: {big}pt; }}
    QMenu {{ background: white; border: 1px solid {C.border_strong}; padding: 6px; border-radius: 8px; }}
    QMenu::item {{ padding: 8px 24px 8px 14px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {C.primary_soft}; color: {C.text}; }}
    QMenu::separator {{ height: 1px; background: {C.border}; margin: 4px 8px; }}
    QGroupBox {{ background: {C.surface}; border: 1px solid {C.border}; border-radius: 12px;
        margin-top: 14px; padding: 18px 14px 14px 14px; font-weight: 700; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 6px; color: {C.text}; }}
    """


# ---------------------------------------------------------------------- 圖示
_ICONS = {
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20h5v-6h4v6h5V9.5"/>',
    "list": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "wallet": '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18"/>'
              '<path d="M16 15h2"/><path d="M6 6l9-3 2 3"/>',
    "chart": '<path d="M4 20V4"/><path d="M4 20h16"/><rect x="7" y="11" width="3" height="6"/>'
             '<rect x="12" y="7" width="3" height="10"/><rect x="17" y="13" width="3" height="4"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/>'
                '<circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "download": '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M4 19h16"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "transfer": '<path d="M4 8h14l-3-3"/><path d="M20 16H6l3 3"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="m13 7 4 4"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
    "refresh": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
    "folder": '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><rect x="8" y="13" width="8" height="5"/>',
    "restore": '<path d="M4 12a8 8 0 1 0 2.3-5.7"/><path d="M4 5v6h6"/><path d="M12 8v4l3 2"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v11h14V9"/><path d="M10 13h4"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "up": '<path d="m6 15 6-6 6 6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "excel": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="m9 8 6 8M15 8l-6 8"/>',
}


def icon(name: str, color: str = C.text, size: int = 64) -> QIcon:
    body = _ICONS.get(name, "")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
           f'{body}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pm)


def arrow_file() -> str:
    """將下拉箭頭圖示存成暫存檔，供樣式表使用。"""
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "my_ledger_arrow_v1.png")
    if not os.path.exists(path):
        icon("down", C.muted, 32).pixmap(32, 32).save(path, "PNG")
    return path.replace("\\", "/")


def app_icon() -> QIcon:
    size = 256
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C.primary))
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 56, 56)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(QRectF(58, 96, 140, 98), 16, 16)
    p.setBrush(QColor(C.gold))
    p.drawEllipse(QRectF(150, 128, 34, 34))
    p.setBrush(QColor("#BFD3FB"))
    p.drawRoundedRect(QRectF(70, 64, 116, 26), 10, 10)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------- 格式
def currency_symbol(code: str) -> str:
    return CURRENCIES.get(code, (code, code + " "))[1]


def currency_name(code: str) -> str:
    return CURRENCIES.get(code, (code, code))[0]


def decimals_for(code: str) -> int:
    return 0 if code in ZERO_DECIMAL_CURRENCIES else 2


def fmt_num(value: float, code: str = "TWD", signed: bool = False) -> str:
    d = decimals_for(code)
    v = round(value or 0.0, d) + 0.0
    text = f"{abs(v):,.{d}f}"
    if v < 0:
        return "-" + text
    if signed and v > 0:
        return "+" + text
    return text


def fmt_money(value: float, code: str = "TWD", signed: bool = False) -> str:
    v = round(value or 0.0, decimals_for(code)) + 0.0
    sym = currency_symbol(code)
    sign = "-" if v < 0 else ("+" if signed and v > 0 else "")
    return f"{sign}{sym}{fmt_num(abs(v), code)}"


WEEKDAYS = "一二三四五六日"


def fmt_date(iso: str) -> str:
    return iso.replace("-", "/") if iso else ""


def fmt_date_long(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日（民國{d.year - 1911}年）星期{WEEKDAYS[d.weekday()]}"


def fmt_month(ym: str) -> str:
    y, m = ym.split("-")
    return f"{y}年{int(m)}月"


def fmt_month_short(ym: str) -> str:
    y, m = ym.split("-")
    return f"{int(m)}"
