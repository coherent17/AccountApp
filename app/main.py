"""主視窗與程式進入點。"""

from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QLibraryInfo, QLocale, Qt, QTimer, QTranslator
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .animations import NavIndicator, RippleFilter, Toast, page_transition
from .context import APP_NAME, APP_VERSION, AppContext
from .dialogs import ExportDialog, TransactionDialog, WelcomeDialog
from .pages.accounts import AccountsPage
from .pages.dashboard import DashboardPage
from .pages.investments import InvestmentsPage
from .pages.reports import ReportsPage
from .pages.settings import SettingsPage
from .pages.transactions import TransactionsPage
from .sample_data import load_sample_data
from .theme import FONT_FAMILY, FONT_SCALES, app_icon, arrow_file, icon, stylesheet
from .widgets import error

NAV = [
    ("dashboard", "總覽", "home", DashboardPage),
    ("transactions", "收支明細", "list", TransactionsPage),
    ("accounts", "帳戶管理", "wallet", AccountsPage),
    ("investments", "投資管理", "chart", InvestmentsPage),
    ("reports", "財務報表", "excel", ReportsPage),
    ("settings", "設定", "settings", SettingsPage),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1380, 900)
        self.setMinimumSize(1100, 700)

        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 側邊欄
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 24, 16, 18)
        sl.setSpacing(6)
        logo_row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(40, 40))
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        t = QLabel(APP_NAME)
        t.setObjectName("AppTitle")
        st = QLabel("個人資產與記帳管理")
        st.setObjectName("AppSubtitle")
        title_col.addWidget(t)
        title_col.addWidget(st)
        logo_row.addWidget(logo)
        logo_row.addLayout(title_col)
        logo_row.addStretch()
        sl.addLayout(logo_row)
        sl.addSpacing(22)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        for key, label, ic, cls in NAV:
            btn = QPushButton("  " + label)
            btn.setObjectName("NavButton")
            btn.setIcon(icon(ic, "#C3CDE2"))
            btn.setIconSize(btn.iconSize() * 1.3)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.go(k))
            group.addButton(btn)
            sl.addWidget(btn)
            self.nav_buttons[key] = btn
            page = cls(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
        sl.addStretch()
        quick = QPushButton("＋ 記一筆　Ctrl+N")
        quick.setObjectName("NavButton")
        quick.setCursor(Qt.CursorShape.PointingHandCursor)
        quick.clicked.connect(self.quick_add)
        sl.addWidget(quick)
        sl.addSpacing(6)
        exp = QPushButton("  匯出 Excel 報表")
        exp.setObjectName("SidebarExport")
        exp.setIcon(icon("excel", "#FFFFFF"))
        exp.setCursor(Qt.CursorShape.PointingHandCursor)
        exp.clicked.connect(self.export)
        sl.addWidget(exp)
        sl.addSpacing(10)
        foot = QLabel(f"版本 {APP_VERSION}\n資料僅存於本機")
        foot.setObjectName("SidebarFoot")
        sl.addWidget(foot)

        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self.indicator = NavIndicator(side)
        self.toast = Toast(root)
        ctx.toast.connect(self.toast.show_message)

        ctx.navigate.connect(self._navigate)
        ctx.settingsChanged.connect(self.apply_theme)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.quick_add)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self.export)
        for i, (key, *_rest) in enumerate(NAV, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self.go(k))
        self.go("dashboard", animate=False)

    def go(self, key: str, animate: bool = True) -> None:
        btn = self.nav_buttons[key]
        btn.setChecked(True)
        self._current_key = key
        for k, b in self.nav_buttons.items():
            b.setIcon(icon(dict((n[0], n[2]) for n in NAV)[k], "#FFFFFF" if k == key else "#C3CDE2"))
        if animate:
            page_transition(self.stack, self.pages[key], self)
        else:
            self.stack.setCurrentWidget(self.pages[key])
        QTimer.singleShot(0, lambda: self.indicator.move_to(btn, animate))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, lambda: self.indicator.move_to(
            self.nav_buttons[getattr(self, "_current_key", "dashboard")], False))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "indicator"):
            self.indicator.move_to(self.nav_buttons[getattr(self, "_current_key", "dashboard")], False)

    def _navigate(self, key: str, kwargs: dict) -> None:
        self.go(key)
        if kwargs:
            self.pages[key].apply_filter(**kwargs)

    def quick_add(self) -> None:
        TransactionDialog(self.ctx, "expense", parent=self).exec()

    def export(self) -> None:
        ExportDialog(self.ctx, self).exec()

    def apply_theme(self) -> None:
        apply_theme(QApplication.instance(), self.ctx)

    def closeEvent(self, e):
        self.ctx.db.close()
        super().closeEvent(e)


def apply_theme(app: QApplication, ctx: AppContext) -> None:
    scale = ctx.db.get_setting("font_scale", "large")
    pt = FONT_SCALES.get(scale, FONT_SCALES["large"])[1]
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(pt)
    app.setFont(f)
    app.setStyleSheet(stylesheet(pt, arrow_file()))
    from . import animations
    animations.set_enabled(ctx.db.get_setting("animations", "1") == "1")


def _install_excepthook(log_dir: str) -> None:
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(os.path.join(log_dir, "錯誤紀錄.log"), "a", encoding="utf-8") as fh:
                import datetime as dt
                fh.write(f"\n==== {dt.datetime.now():%Y-%m-%d %H:%M:%S} ====\n{text}")
        except OSError:
            pass
        error(QApplication.activeWindow(), f"程式發生未預期的錯誤，但您的資料已安全保存。\n\n{exc}")
    sys.excepthook = hook


def create_app(argv=None, db_path: str | None = None):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MyLedger.Desktop.1")
        except Exception:  # noqa: BLE001
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv or sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale("zh_TW"))
    tr = QTranslator(app)
    if tr.load(QLocale("zh_TW"), "qtbase", "_",
               QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)
    app._ripple = RippleFilter(app)
    app.installEventFilter(app._ripple)
    ctx = AppContext(db_path)
    _install_excepthook(ctx.folder)
    apply_theme(app, ctx)
    try:
        ctx.db.auto_backup(ctx.backup_dir)
    except Exception:  # noqa: BLE001
        pass
    return app, ctx


def _smoke_test(app: QApplication, ctx: AppContext, win: MainWindow, out: str) -> None:
    """自動測試模式：載入範例資料、逐頁截圖後結束（供打包後驗證用）。"""
    from PySide6.QtCore import QTimer
    if not ctx.db.list_accounts(include_archived=True):
        load_sample_data(ctx.db)
        ctx.changed()
    keys = [n[0] for n in NAV]

    def step(i: int = 0) -> None:
        if i > 0:
            win.grab().save(os.path.join(out, f"exe_{keys[i - 1]}.png"))
        if i == len(keys):
            app.quit()
            return
        win.go(keys[i])
        QTimer.singleShot(1500, lambda: step(i + 1))
    QTimer.singleShot(1500, step)


def main() -> int:
    app, ctx = create_app()
    win = MainWindow(ctx)
    win.show()
    shot_dir = os.environ.get("MY_LEDGER_SMOKE_DIR")
    if shot_dir:
        _smoke_test(app, ctx, win, shot_dir)
        return app.exec()
    if ctx.db.get_setting("first_run_done") != "1" and not ctx.db.list_accounts(include_archived=True):
        dlg = WelcomeDialog(ctx, win)
        dlg.exec()
        if dlg.choice == "sample":
            load_sample_data(ctx.db)
        else:
            ctx.db.start_fresh()
        ctx.db.set_setting("first_run_done", "1")
        ctx.changed()
        ctx.settingsChanged.emit()
    else:
        due = ctx.db.due_recurring()
        if due:
            from PySide6.QtCore import QTimer as _T
            from .dialogs_more import DueRecurringDialog
            _T.singleShot(600, lambda: DueRecurringDialog(ctx, due, win).exec())
    return app.exec()
