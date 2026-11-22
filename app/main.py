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
from .theme import (C, FONT_FAMILY, FONT_SCALES, app_icon, arrow_file, check_file, icon, palette, resolve_mode,
                    set_mode, stylesheet)
from .widgets import hline
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
        self.setMinimumSize(1100, 700)
        self._initial_geometry()

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
        logo.setPixmap(app_icon().pixmap(42, 42))
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
            btn.setIcon(icon(ic, C.sidebar_text))
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
        sl.addWidget(hline())
        sl.addSpacing(4)
        find = _shortcut_button("搜尋", "Ctrl+F", "search")
        find.setToolTip("一次搜尋傳票、會計科目、投資標的與定期交易（摘要、金額、傳票號碼、代號、日期…）")
        find.clicked.connect(self.open_search)
        sl.addWidget(find)
        quick = _shortcut_button("記一筆", "Ctrl+N", "plus")
        quick.setToolTip("新增一筆收入、支出或轉帳")
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
        from .netstatus import NetStatus
        self.net = NetStatus()
        self.net.changed.connect(self._net_changed)
        sl.addWidget(self.net)
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
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.open_search)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        self._changes_at_start = ctx.db.conn.total_changes
        self._search = None
        for i, (key, *_rest) in enumerate(NAV, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, activated=lambda k=key: self.go(k))
        self.go("dashboard", animate=False)

    def _initial_geometry(self) -> None:
        """開啟時恢復上次的視窗大小與位置；第一次開啟時依螢幕大小放大（約螢幕的九成）。"""
        from PySide6.QtCore import QByteArray
        saved = self.ctx.db.get_setting("window_geometry", "")
        if saved:
            try:
                if self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii"))):
                    return
            except Exception:  # noqa: BLE001
                pass
        self.resize(1380, 900)
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        w = max(self.minimumWidth(), min(int(area.width() * 0.92), 1800))
        h = max(self.minimumHeight(), min(int(area.height() * 0.92), 1100))
        w, h = min(w, area.width()), min(h, area.height())
        self.resize(w, h)
        self.move(area.left() + (area.width() - w) // 2, area.top() + max(0, (area.height() - h) // 3))

    def save_geometry(self) -> None:
        try:
            self.ctx.db.set_setting("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
        except Exception:  # noqa: BLE001
            pass

    def go(self, key: str, animate: bool = True) -> None:
        btn = self.nav_buttons[key]
        btn.setChecked(True)
        self._current_key = key
        for k, b in self.nav_buttons.items():
            b.setIcon(icon(dict((n[0], n[2]) for n in NAV)[k], C.primary if k == key else C.sidebar_text))
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

    def _net_changed(self, online: bool) -> None:
        """連上網路時，若今天還沒自動檢查新版本（且已開啟），就在背景檢查一次。"""
        if not online or os.environ.get("MY_LEDGER_SMOKE_DIR"):
            return      # 自動測試模式不檢查新版本（避免跳出視窗中斷截圖）
        from .dialogs_update import auto_check_due, check_for_updates
        if auto_check_due(self.ctx):
            check_for_updates(self.ctx, self, silent=True)

    def undo(self) -> None:
        """Ctrl+Z：復原本次開啟後的上一步（新增、修改、作廢、投資交易…）。"""
        from .undo import next_label, undo_last
        from .widgets import ask, info
        label = next_label(self.ctx.db)
        if not label:
            info(self, "目前沒有可以復原的操作。\n（復原只限這次開啟程式之後做的新增、修改與作廢。）")
            return
        if not ask(self, f"要復原上一步嗎？\n\n{label}\n\n"
                         "新增的傳票會改為「已作廢」（保留在帳上），修改會改回原來的內容。", yes="復原"):
            return
        try:
            done = undo_last(self.ctx.db)
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed()
        self.ctx.toast.emit(f"已復原：{done}")

    def open_search(self) -> None:
        from .dialogs_search import SearchDialog
        if self._search is None:
            self._search = SearchDialog(self.ctx, self)
        self._search.show()
        self._search.raise_()
        self._search.activateWindow()
        self._search.focus_box()

    def apply_theme(self) -> None:
        apply_theme(QApplication.instance(), self.ctx)

    def closeEvent(self, e):
        self.net.stop()
        changed = self.ctx.db.conn.total_changes != self._changes_at_start
        if not os.environ.get("MY_LEDGER_SMOKE_DIR"):
            if changed:        # 本次有記帳：關閉前把最新的帳本再複製到第二個備份位置（失敗不影響關閉）
                from . import backup
                backup.try_run(self.ctx.db, self.ctx.folder)
            self.save_geometry()
        self.ctx.db.close()
        super().closeEvent(e)


def _shortcut_button(text: str, keys: str, ic: str) -> QPushButton:
    """側邊欄按鈕：左邊圖示與名稱，右邊以較小的字顯示快速鍵（字型放大時也不會被截斷）。"""
    btn = QPushButton()
    btn.setObjectName("NavButton")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setAccessibleName(f"{text} {keys}")
    row = QHBoxLayout(btn)
    row.setContentsMargins(18, 12, 14, 12)
    row.setSpacing(10)
    pic = QLabel()
    pic.setPixmap(icon(ic, C.sidebar_text).pixmap(22, 22))
    pic.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    name = QLabel(text)
    name.setObjectName("NavText")
    name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    key = QLabel(keys)
    key.setObjectName("NavKey")
    key.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    row.addWidget(pic)
    row.addWidget(name)
    row.addStretch()
    row.addWidget(key)
    return btn


def refit_layouts() -> None:
    """字型大小改變後，重新計算表格欄寬與分頁標籤（避免沿用舊字型的寬度而截斷文字）。"""
    from .pages.reports import StatementTree
    from .widgets import DataTable, FitTabWidget
    for w in QApplication.allWidgets():
        if isinstance(w, DataTable):
            w.fit_columns()
            w.viewport().update()
        elif isinstance(w, StatementTree):
            w.fit()
        elif isinstance(w, FitTabWidget):
            w._fit()


def apply_theme(app: QApplication, ctx: AppContext) -> None:
    scale = ctx.db.get_setting("font_scale", "large")
    pt = FONT_SCALES.get(scale, FONT_SCALES["large"])[1]
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(pt)
    app.setFont(f)
    app.setPalette(palette())
    app.setStyleSheet(stylesheet(pt, arrow_file(), check_file()))
    QTimer.singleShot(0, refit_layouts)
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
    from .dialogs_update import cleanup_old_exe
    cleanup_old_exe()
    set_mode(resolve_mode(ctx.db.get_setting("theme_mode", "light")))
    apply_theme(app, ctx)
    try:
        ctx.db.auto_backup(ctx.backup_dir)
    except Exception:  # noqa: BLE001
        pass
    from . import backup
    if backup.due_today(ctx.db) and not os.environ.get("MY_LEDGER_SMOKE_DIR"):
        backup.try_run(ctx.db, ctx.folder)      # 每天第一次開啟：第二份備份（隨身碟／OneDrive）
    return app, ctx


def restart_app() -> None:
    """重新開啟程式（切換深色模式後使用）：先關閉主視窗（會儲存視窗大小並做第二份備份），再啟動新的程式。"""
    import subprocess
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, os.path.abspath(sys.argv[0])]
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    app = QApplication.instance()
    for w in app.topLevelWidgets():
        if isinstance(w, MainWindow):
            w.close()
    subprocess.Popen(cmd, env=env, close_fds=True, creationflags=flags)
    app.quit()


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
        win.net.start(0)
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
    win.net.start()      # 網路狀態：開啟後檢查一次，之後每 5 分鐘；連上時順便做每日的新版本檢查
    return app.exec()
