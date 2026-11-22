"""外觀：配色、字型大小、樣式表、向量圖示與數字格式。"""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .database import CURRENCIES, ZERO_DECIMAL_CURRENCIES  # noqa: F401
from .fmt import FONT_FAMILY

FONT_FALLBACKS = ["Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC",
                  "Noto Sans CJK TC", "Noto Sans TC", "sans-serif"]

FONT_SCALES = {
    "normal": ("標準", 11),
    "large": ("大", 12.5),
    "xlarge": ("特大", 14),
}


# 淺色（預設）與深色兩組設計配色；C 的屬性由 set_mode() 依設定填入。
LIGHT = {
    "bg": "#F4F6FA", "surface": "#FFFFFF", "surface_alt": "#F7F9FC", "popup": "#FFFFFF",
    "border": "#E4E8EF", "border_strong": "#CFD6E1", "border_hover": "#AEB8C8",
    "text": "#111827", "muted": "#5B6880", "faint": "#7D899C",
    "sidebar": "#FFFFFF", "sidebar_hover": "#F1F4F9", "sidebar_active": "#E9EFFE", "sidebar_text": "#475569",
    "primary": "#3056D3", "primary_hover": "#2546B5", "primary_soft": "#EAF0FE", "primary_deep": "#4B3CC4",
    "primary_disabled": "#A9B8E8", "on_primary": "#FFFFFF",
    "income": "#0C9A6A", "income_soft": "#E5F6EF", "income_line": "#C5EADB", "income_hover": "#D6F1E6",
    "expense": "#DC444A", "expense_soft": "#FDEEEE", "expense_line": "#F7CFD1", "expense_hover": "#FBE1E2",
    "transfer": "#55647C", "transfer_soft": "#EEF1F6", "transfer_line": "#D9DFE9", "transfer_hover": "#E3E8F0",
    "adjust": "#7350DD", "adjust_soft": "#F1EDFE", "adjust_line": "#DCD2FA", "adjust_hover": "#E7E0FD",
    "danger_line": "#F2C3C5",
    "gold": "#D4880B", "gold_soft": "#FDF4E2", "gold_line": "#F1D29A", "gold_text": "#7A4F00",
    "row_alt": "#FAFBFD", "row_line": "#EEF1F6", "row_sub": "#F6F8FC", "row_total": "#ECF1FD", "row_grand": "#E1E9FC",
    "tooltip": "#1F2937", "toast": "#111827", "shadow": (15, 23, 42), "chart_edge": "#FFFFFF",
    "chart": ["#3056D3", "#0C9A6A", "#F0A020", "#DC444A", "#7350DD", "#0EA5B7",
              "#E45FA2", "#7CB518", "#64748B", "#F07A2E", "#14B8A6", "#A35BE8"],
}
DARK = {
    "bg": "#0E131B", "surface": "#161C26", "surface_alt": "#1C2330", "popup": "#1C2330",
    "border": "#273041", "border_strong": "#364154", "border_hover": "#55637C",
    "text": "#E7EBF3", "muted": "#9CA8BC", "faint": "#7F8BA0",
    "sidebar": "#121821", "sidebar_hover": "#1C2330", "sidebar_active": "#1D2A4C", "sidebar_text": "#AAB5C7",
    "primary": "#5B7CF0", "primary_hover": "#7591F5", "primary_soft": "#1D2A4C", "primary_deep": "#5B4BD3",
    "primary_disabled": "#2E3B63", "on_primary": "#FFFFFF",
    "income": "#3CC48F", "income_soft": "#13302A", "income_line": "#1E4A3E", "income_hover": "#183B33",
    "expense": "#F2696E", "expense_soft": "#3A1D22", "expense_line": "#5A2A31", "expense_hover": "#45222A",
    "transfer": "#9DAAC1", "transfer_soft": "#222A37", "transfer_line": "#323C4E", "transfer_hover": "#2A3342",
    "adjust": "#A78DF6", "adjust_soft": "#272044", "adjust_line": "#3B3166", "adjust_hover": "#302853",
    "danger_line": "#5A2A31",
    "gold": "#F0B24A", "gold_soft": "#2E2516", "gold_line": "#5A4520", "gold_text": "#F3C877",
    "row_alt": "#19202B", "row_line": "#222A37", "row_sub": "#1B2230", "row_total": "#1E2945", "row_grand": "#253259",
    "tooltip": "#2C3546", "toast": "#2C3546", "shadow": (0, 0, 0), "chart_edge": "#161C26",
    "chart": ["#6E8EF7", "#3CC48F", "#F5B342", "#F2696E", "#A78DF6", "#2CC3D5",
              "#F07DB8", "#9BD13A", "#8A97AD", "#F7914F", "#2DD4BF", "#C084FC"],
}
THEME_MODES = {"light": "淺色", "dark": "深色", "system": "跟隨 Windows 設定"}


class C:
    """設計配色（v2.10.0）：沉穩的墨藍為主色，收入綠、支出紅、轉帳灰藍、評價紫；
    每個顏色都有淡色底（*_soft），用於標籤、按鈕底色與圖示底。v2.11.0 起另有深色模式（DARK）。
    頁面一律讀取 C.xxx，不要寫死色碼。"""
    dark = False


for _k, _v in LIGHT.items():
    setattr(C, _k, _v)


def soft(color: str, alpha: float = 0.12) -> str:
    """色彩的半透明版本（樣式表用），例如圖示底色。"""
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {int(alpha * 255)})"


TYPE_COLORS: dict[str, tuple[str, str]] = {}
# 按鈕樣式（objectName）→ 圖示顏色
BUTTON_ICON_COLORS: dict[str, str] = {}


def _derive() -> None:
    """依目前的 C 重新填入衍生的對照表（就地更新，已匯入的模組也會看到新顏色）。"""
    TYPE_COLORS.update({
        "income": (C.income, C.income_soft), "expense": (C.expense, C.expense_soft),
        "transfer": (C.transfer, C.transfer_soft), "adjust": (C.adjust, C.adjust_soft),
        "journal": (C.primary, C.primary_soft),
    })
    BUTTON_ICON_COLORS.update({
        "Primary": C.on_primary, "Income": C.income, "Expense": C.expense, "Transfer": C.transfer,
        "Adjust": C.adjust, "Danger": C.expense, "Link": C.primary,
    })


def system_prefers_dark() -> bool:
    try:
        from PySide6.QtGui import QGuiApplication
        hints = QGuiApplication.styleHints()
        return hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:  # noqa: BLE001
        return False


def resolve_mode(mode: str) -> bool:
    """設定值（light／dark／system）→ 是否使用深色。"""
    if mode == "dark":
        return True
    if mode == "system":
        return system_prefers_dark()
    return False


def set_mode(dark: bool) -> None:
    """切換淺色／深色配色。須在建立視窗之前呼叫（已建立的視窗不會全部重畫，切換時程式會重新開啟）。"""
    for k, v in (DARK if dark else LIGHT).items():
        setattr(C, k, list(v) if isinstance(v, list) else v)
    C.dark = dark
    _derive()


_derive()


def palette():
    """Fusion 樣式的調色盤（樣式表沒有涵蓋的元件，例如預覽列印視窗、文字瀏覽框）。"""
    from PySide6.QtGui import QPalette
    pal = QPalette()
    R = QPalette.ColorRole
    for role, color in ((R.Window, C.bg), (R.WindowText, C.text), (R.Base, C.surface), (R.AlternateBase, C.row_alt),
                        (R.Text, C.text), (R.Button, C.surface), (R.ButtonText, C.text),
                        (R.ToolTipBase, C.tooltip), (R.ToolTipText, "#FFFFFF"), (R.PlaceholderText, C.faint),
                        (R.Highlight, C.primary), (R.HighlightedText, C.on_primary), (R.Link, C.primary),
                        (R.BrightText, "#FFFFFF"), (R.Mid, C.border_strong), (R.Dark, C.border_hover),
                        (R.Light, C.surface_alt), (R.Midlight, C.surface_alt), (R.Shadow, "#000000")):
        pal.setColor(role, QColor(color))
    for role in (R.Text, R.WindowText, R.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(C.faint))
    return pal


def _tinted(name: str, fg: str, bg: str, line: str, hover: str) -> str:
    return (f"QPushButton#{name} {{ background: {bg}; color: {fg}; border: 1px solid {line}; font-weight: 700; }}"
            f"QPushButton#{name}:hover {{ background: {hover}; border-color: {fg}; }}"
            f"QPushButton#{name}:pressed {{ background: {line}; }}")


def stylesheet(pt: float, arrow: str = "", check: str = "") -> str:
    s = pt
    big = s * 1.12
    gb_top = int(s * 2.6)
    return f"""
    * {{ font-family: "{FONT_FAMILY}", "Microsoft JhengHei"; font-size: {s}pt; color: {C.text}; }}
    QMainWindow, QDialog, #PageRoot {{ background: {C.bg}; }}
    QToolTip {{ background: {C.tooltip}; color: #FFFFFF; border: none; padding: 7px 10px; border-radius: 8px; }}

    /* ---------- 側邊欄 ---------- */
    #Sidebar {{ background: {C.sidebar}; border: none; border-right: 1px solid {C.border}; }}
    #Sidebar QLabel {{ color: {C.sidebar_text}; background: transparent; }}
    #Sidebar QLabel#AppTitle {{ color: {C.text}; font-size: {s * 1.3}pt; font-weight: 700; }}
    #Sidebar QLabel#AppSubtitle {{ color: {C.faint}; font-size: {s * 0.82}pt; }}
    #Sidebar QLabel#SidebarSection {{ color: {C.faint}; font-size: {s * 0.8}pt; font-weight: 700;
        padding: 0 0 0 14px; }}
    #NavButton {{
        background: transparent; color: {C.sidebar_text}; border: none; text-align: left;
        padding: 11px 16px; border-radius: 10px; font-size: {big}pt;
    }}
    #NavButton:hover {{ background: {C.sidebar_hover}; color: {C.text}; }}
    #NavButton:checked {{ background: {C.sidebar_active}; color: {C.primary}; font-weight: 700; }}
    #Sidebar QLabel#NavText {{ font-size: {big}pt; color: {C.sidebar_text}; }}
    #Sidebar QLabel#NavKey {{ color: {C.faint}; font-size: {s * 0.78}pt; background: {C.surface_alt};
        border: 1px solid {C.border}; border-radius: 5px; padding: 1px 5px; }}
    #SidebarExport {{
        background: {C.primary}; color: {C.on_primary}; border: none; border-radius: 10px;
        padding: 11px 14px; font-weight: 700; font-size: {s}pt;
    }}
    #SidebarExport:hover {{ background: {C.primary_hover}; }}
    #Sidebar QLabel#SidebarFoot {{ color: {C.faint}; font-size: {s * 0.78}pt; }}

    /* ---------- 頁面 ---------- */
    #PageTitle {{ font-size: {s * 1.7}pt; font-weight: 700; color: {C.text}; }}
    #PageSubtitle {{ color: {C.muted}; font-size: {s * 0.95}pt; }}
    #SectionTitle {{ font-size: {s * 1.12}pt; font-weight: 700; color: {C.text}; }}
    #Muted {{ color: {C.muted}; }}
    #Hint {{ color: {C.muted}; font-size: {s * 0.88}pt; }}

    #Card {{ background: {C.surface}; border: 1px solid {C.border}; border-radius: 16px; }}
    #Card QLabel {{ background: transparent; }}
    #StatTitle {{ color: {C.muted}; font-size: {s * 0.92}pt; }}
    #StatValue {{ font-size: {s * 1.65}pt; font-weight: 700; }}
    #StatSub {{ color: {C.faint}; font-size: {s * 0.84}pt; }}
    #HeroCard {{ border: none; border-radius: 16px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {C.primary}, stop:1 {C.primary_deep}); }}
    #HeroCard QLabel {{ background: transparent; color: white; }}
    #HeroCard QLabel#StatTitle, #HeroCard QLabel#StatSub {{ color: rgba(255, 255, 255, 200); }}
    #RatioValue {{ font-size: {s * 1.3}pt; font-weight: 700; }}
    #RemindCard {{ background: {C.gold_soft}; border: 1px solid {C.gold_line}; border-radius: 16px; }}
    #RemindCard QLabel {{ background: transparent; }}
    #SampleBanner {{ background: {C.gold_soft}; border: 1px solid {C.gold_line}; border-radius: 14px; }}
    #SampleBanner QLabel {{ background: transparent; color: {C.gold_text}; font-weight: 700; }}

    /* ---------- 按鈕 ---------- */
    QPushButton {{
        background: {C.surface}; border: 1px solid {C.border_strong}; border-radius: 10px;
        padding: 8px 16px; min-height: 22px; color: {C.text};
    }}
    QPushButton:hover {{ background: {C.surface_alt}; border-color: {C.border_hover}; }}
    QPushButton:pressed {{ background: {C.row_line}; }}
    QPushButton:disabled {{ color: {C.faint}; background: {C.surface_alt}; border-color: {C.border}; }}
    QPushButton#Primary {{ background: {C.primary}; color: {C.on_primary}; border: 1px solid {C.primary}; font-weight: 700; }}
    QPushButton#Primary:hover {{ background: {C.primary_hover}; border-color: {C.primary_hover}; }}
    QPushButton#Primary:disabled {{ background: {C.primary_disabled}; border-color: {C.primary_disabled}; }}
    {_tinted("Income", C.income, C.income_soft, C.income_line, C.income_hover)}
    {_tinted("Expense", C.expense, C.expense_soft, C.expense_line, C.expense_hover)}
    {_tinted("Transfer", C.transfer, C.transfer_soft, C.transfer_line, C.transfer_hover)}
    {_tinted("Adjust", C.adjust, C.adjust_soft, C.adjust_line, C.adjust_hover)}
    QPushButton#Danger {{ color: {C.expense}; border-color: {C.danger_line}; }}
    QPushButton#Danger:hover {{ background: {C.expense_soft}; border-color: {C.expense}; }}
    QPushButton#Link {{ background: transparent; border: none; color: {C.primary}; padding: 4px 6px; }}
    QPushButton#Link:hover {{ text-decoration: underline; }}
    QPushButton::menu-indicator {{ subcontrol-origin: padding; subcontrol-position: right center;
        right: 6px; image: url({arrow}); width: 12px; height: 12px; }}

    QPushButton#Segment {{
        background: {C.surface}; border: 1px solid {C.border}; border-radius: 10px;
        padding: 10px 6px; font-size: {big}pt; color: {C.muted};
    }}
    QPushButton#Segment:hover {{ border-color: {C.border_hover}; color: {C.text}; }}
    QPushButton#Segment:checked {{ color: {C.on_primary}; font-weight: 700; border: none; }}
    QPushButton#Segment[ttype="expense"]:checked {{ background: {C.expense}; }}
    QPushButton#Segment[ttype="income"]:checked {{ background: {C.income}; }}
    QPushButton#Segment[ttype="transfer"]:checked {{ background: {C.transfer}; }}

    QPushButton#Chip {{
        background: {C.surface}; border: 1px solid {C.border}; border-radius: 17px;
        padding: 7px 10px; color: {C.text};
    }}
    QPushButton#Chip:hover {{ border-color: {C.primary}; background: {C.primary_soft}; }}
    QPushButton#Chip:checked {{ background: {C.primary}; border: 2px solid {C.primary};
        color: {C.on_primary}; font-weight: 700; }}

    /* ---------- 輸入 ---------- */
    QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
        background: {C.surface}; border: 1px solid {C.border_strong}; border-radius: 10px;
        padding: 7px 11px; min-height: 22px; selection-background-color: {C.primary};
        selection-color: {C.on_primary};
    }}
    QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover,
    QPlainTextEdit:hover {{ border-color: {C.border_hover}; }}
    QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QPlainTextEdit:focus {{ border: 2px solid {C.primary}; padding: 6px 10px; }}
    QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled {{ background: {C.surface_alt}; color: {C.muted}; border-color: {C.border}; }}
    QLineEdit[readOnly="true"] {{ background: {C.surface_alt}; }}
    QLineEdit#AmountEdit {{ font-size: {s * 1.6}pt; font-weight: 700; padding: 8px 12px; }}
    QLineEdit#AmountEdit:focus {{ padding: 7px 11px; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button,
    QDoubleSpinBox::down-button {{ width: 0; border: none; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 30px; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({arrow}); width: 14px; height: 14px; }}
    QComboBox::down-arrow:on {{ top: 1px; }}
    QComboBox QAbstractItemView {{
        background: {C.popup}; border: 1px solid {C.border_strong}; outline: none; border-radius: 8px;
        selection-background-color: {C.primary_soft}; selection-color: {C.text}; padding: 4px;
    }}
    QComboBox QAbstractItemView::item {{ min-height: 32px; padding: 2px 8px; border-radius: 6px; }}
    QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; padding: 4px 10px 4px 0; }}
    QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 10px;
        border: 2px solid {C.border_strong}; background: {C.surface}; }}
    QRadioButton::indicator:hover {{ border-color: {C.primary}; }}
    QRadioButton::indicator:checked {{ border: 6px solid {C.primary}; width: 8px; height: 8px; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px;
        border: 2px solid {C.border_strong}; background: {C.surface}; }}
    QCheckBox::indicator:hover {{ border-color: {C.primary}; }}
    QCheckBox::indicator:checked {{ background: {C.primary}; border: 2px solid {C.primary};
        image: url({check}); }}
    QCheckBox::indicator:disabled {{ background: {C.surface_alt}; border-color: {C.border}; }}

    QCalendarWidget QWidget {{ alternate-background-color: {C.surface_alt}; }}
    QCalendarWidget QToolButton {{ color: {C.text}; background: transparent; padding: 6px;
        font-weight: 700; border-radius: 6px; }}
    QCalendarWidget QToolButton:hover {{ background: {C.primary_soft}; }}
    QCalendarWidget #qt_calendar_navigationbar {{ background: {C.surface}; border-bottom: 1px solid {C.border}; }}
    QCalendarWidget QAbstractItemView {{ selection-background-color: {C.primary}; selection-color: {C.on_primary};
        font-size: {s}pt; }}

    /* ---------- 表格 ---------- */
    QTableView, QTreeWidget, QListWidget {{
        background: {C.surface}; border: 1px solid {C.border}; border-radius: 14px;
        gridline-color: transparent; alternate-background-color: {C.row_alt};
        selection-background-color: {C.primary_soft}; selection-color: {C.text}; outline: none;
    }}
    QTableView::item, QTreeWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {C.row_line}; }}
    QTableView::item:selected, QTreeWidget::item:selected {{ background: {C.primary_soft}; color: {C.text}; }}
    QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
    QListWidget::item:selected {{ background: {C.primary_soft}; color: {C.text}; }}
    QListWidget::item:hover {{ background: {C.surface_alt}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{
        background: {C.surface_alt}; color: {C.muted}; border: none;
        border-bottom: 1px solid {C.border}; padding: 10px 8px; font-weight: 700;
    }}
    QHeaderView::section:hover {{ color: {C.text}; }}
    QTableCornerButton::section {{ background: {C.surface_alt}; border: none; }}

    /* ---------- 分頁 ---------- */
    QTabWidget::pane {{ border: none; border-top: 1px solid {C.border}; background: transparent; top: -1px; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent; color: {C.muted}; padding: 10px 16px; margin-right: 2px;
        border: none; border-bottom: 3px solid transparent; font-size: {big}pt;
    }}
    QTabBar::tab:selected {{ color: {C.primary}; border-bottom: 3px solid {C.primary}; font-weight: 700; }}
    QTabBar::tab:hover:!selected {{ color: {C.text}; border-bottom: 3px solid {C.border_strong}; }}

    /* ---------- 捲軸 ---------- */
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 3px; }}
    QScrollBar::handle:vertical {{ background: {C.border_strong}; border-radius: 3px; min-height: 36px; }}
    QScrollBar::handle:vertical:hover {{ background: {C.border_hover}; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 3px; }}
    QScrollBar::handle:horizontal {{ background: {C.border_strong}; border-radius: 3px; min-width: 36px; }}
    QScrollBar::handle:horizontal:hover {{ background: {C.border_hover}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QProgressBar {{ background: {C.row_line}; border: none; border-radius: 5px; height: 10px;
        text-align: center; font-size: {s * 0.8}pt; color: transparent; }}
    QProgressBar::chunk {{ background: {C.primary}; border-radius: 5px; }}
    QProgressBar[over="true"]::chunk {{ background: {C.expense}; }}

    QMessageBox {{ background: {C.surface}; }}
    QMessageBox QLabel {{ font-size: {big}pt; }}
    QMenu {{ background: {C.popup}; border: 1px solid {C.border}; padding: 6px; border-radius: 10px; }}
    QMenu::item {{ padding: 9px 26px 9px 14px; border-radius: 7px; }}
    QMenu::item:selected {{ background: {C.primary_soft}; color: {C.primary}; }}
    QMenu::separator {{ height: 1px; background: {C.border}; margin: 4px 8px; }}
    QGroupBox {{ background: {C.surface}; border: 1px solid {C.border}; border-radius: 16px;
        margin-top: {gb_top}px; padding: 18px 16px 16px 16px; font-weight: 700; font-size: {s * 1.08}pt; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 4px; top: 0;
        padding: 0 0 0 0; color: {C.text}; }}
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
    "tag": '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
    "book": '<path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H20v15H5.5A1.5 1.5 0 0 0 4 19.5z"/><path d="M4 19.5A1.5 1.5 0 0 0 5.5 21H20"/>'
            '<path d="M8 7h8M8 11h6"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
    "excel": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="m9 8 6 8M15 8l-6 8"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "trend_up": '<path d="m3 17 6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "trend_down": '<path d="m3 7 6 6 4-4 8 8"/><path d="M15 17h6v-6"/>',
    "scale": '<path d="M12 4v16M7 20h10M5 7h14"/><path d="m5 7-3 6a3 3 0 0 0 6 0z"/>'
             '<path d="m19 7-3 6a3 3 0 0 0 6 0z"/>',
    "bank": '<path d="M3 9.5 12 4l9 5.5z"/><path d="M5.5 10v7M10 10v7M14 10v7M18.5 10v7"/><path d="M3 20h18"/>',
    "card": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h4"/>',
    "dollar": '<path d="M12 3v18"/><path d="M16.5 7H10a3 3 0 0 0 0 6h4a3 3 0 0 1 0 6H7"/>',
    "pie": '<path d="M20.5 14A8.5 8.5 0 1 1 10 3.5V14z"/><path d="M14 3.2A8.5 8.5 0 0 1 20.8 10H14z"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "coins": '<ellipse cx="9" cy="7" rx="6" ry="3"/><path d="M3 7v4c0 1.7 2.7 3 6 3s6-1.3 6-3V7"/>'
             '<path d="M9 14v3c0 1.7 2.7 3 6 3s6-1.3 6-3v-4c0-1.7-2.7-3-6-3"/>',
    "gift": '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M5 12v8h14v-8M12 8v12"/>'
            '<path d="M12 8c-2-4-6-4-6-1.5S9 8 12 8zm0 0c2-4 6-4 6-1.5S15 8 12 8z"/>',
    "bell": '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    "heart": '<path d="M12 20s-8-4.6-8-10.2A4.3 4.3 0 0 1 12 7a4.3 4.3 0 0 1 8 2.8C20 15.4 12 20 12 20z"/>',
    "print": '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
}


def icon(name: str, color: str | None = None, size: int = 64) -> QIcon:
    color = color or C.text
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


def icon_file(name: str, color: str, tag: str) -> str:
    """將圖示存成暫存檔，供樣式表使用（例如下拉箭頭、核取方塊的勾）。"""
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"my_ledger_{tag}.png")
    if not os.path.exists(path):
        icon(name, color, 32).pixmap(32, 32).save(path, "PNG")
    return path.replace("\\", "/")


def arrow_file() -> str:
    return icon_file("down", C.muted, "arrow_v3_" + C.muted.lstrip("#"))


def check_file() -> str:
    return icon_file("check", "#FFFFFF", "check_v3")


def app_icon() -> QIcon:
    """程式圖示：墨藍漸層底、白色帳本頁與金色錢幣。"""
    from PySide6.QtGui import QLinearGradient, QPen
    size = 256
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#4169E8"))
    g.setColorAt(1, QColor(C.primary_deep))
    p.setBrush(g)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 60, 60)
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawRoundedRect(QRectF(76, 50, 120, 150), 18, 18)
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(QRectF(60, 64, 120, 150), 18, 18)
    pen = QPen(QColor("#C9D5F7"), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    for y in (104, 132, 160):
        p.drawLine(86, y, 154 if y != 160 else 124, y)
    p.setPen(QPen(QColor("#FFFFFF"), 8))
    p.setBrush(QColor("#F4B13D"))
    p.drawEllipse(QRectF(140, 146, 70, 70))
    p.setPen(QPen(QColor("#B97A06"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(175, 166, 175, 196)
    p.end()
    return QIcon(pm)


# ---------------------------------------------------------------------- 格式（實作在 app/fmt.py，這裡沿用舊名稱匯出）
from .fmt import (WEEKDAYS, currency_name, currency_symbol, decimals_for, fmt_date, fmt_date_long,  # noqa: E402,F401
                  fmt_money, fmt_month, fmt_month_short, fmt_num)
