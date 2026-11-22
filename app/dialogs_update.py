"""檢查新版本與一鍵更新。

* 「設定 → 版本更新」可手動檢查；也可勾選「開啟程式時自動檢查」（v2.9.0 起預設開啟，一天最多檢查一次；可在設定關閉）。
* 只向 GitHub 查詢公開的版本資訊並下載新版程式，不會上傳任何資料。
* 立即更新（僅限打包好的 exe）：下載到程式所在資料夾並核對 SHA-256 → 備份帳本 →
  將目前的 exe 改名為 .old → 新檔換上原本的檔名 → 重新開啟。舊檔在下次啟動時刪除。
  任何一步失敗都會還原，不影響目前的程式與資料。
"""

from __future__ import annotations

import datetime as dt
import os
import sys

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QProgressBar, QTextBrowser

from . import online
from .context import APP_VERSION, AppContext
from .dialogs import BaseDialog
from .theme import C, fmt_date
from .updater import _download_dir, can_self_update, cleanup_old_exe, install, restart  # noqa: F401
from .widgets import button, error, info


class _Download(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, rel: dict, dest: str, parent=None):
        super().__init__(parent)
        self.rel = rel
        self.dest = dest

    def run(self):
        try:
            online.download(self.rel["url"], self.dest, self.rel.get("size", 0), self.rel.get("sha256", ""),
                            lambda got, total: self.progress.emit(got, total))
            self.done.emit(self.dest)
        except online.OfflineError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"下載失敗：{e}")


class UpdateDialog(BaseDialog):
    def __init__(self, ctx: AppContext, rel: dict, parent=None):
        super().__init__("有新版本可以更新", parent, width=720)
        self.ctx = ctx
        self.rel = rel
        self._job: _Download | None = None

        head = QLabel(f"新版本 {rel['version']} 已推出")
        head.setStyleSheet(f"font-size: 16pt; font-weight: 800; color:{C.primary};")
        self.root.addWidget(head)
        sub = QLabel(f"您目前使用的是 {APP_VERSION} 版"
                     + (f"　｜　發布日期 {fmt_date(rel['published'])}" if rel.get("published") else ""))
        sub.setStyleSheet(f"color:{C.muted}; font-weight:700;")
        self.root.addWidget(sub)

        self.root.addWidget(QLabel("這個版本的更新內容："))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(rel.get("notes") or "（沒有說明）")
        notes.setMinimumHeight(260)
        notes.setStyleSheet(f"QTextBrowser {{ background:{C.surface}; color:{C.text}; border:1px solid {C.border};"
                            " border-radius:10px; padding:10px; }")
        self.root.addWidget(notes, 1)

        safe = QLabel("更新只會換掉程式本身，您的帳本、附件與設定都保留在「文件\\我的理財帳本」，不會變動；"
                      "更新前會先自動備份一份帳本。")
        safe.setObjectName("Hint")
        safe.setWordWrap(True)
        self.root.addWidget(safe)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{C.primary}; font-weight:700;")
        self.status.setVisible(False)
        self.root.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.bar.setTextVisible(False)
        self.root.addWidget(self.bar)
        self.root.addWidget(self.msg)

        row = QHBoxLayout()
        self.skip = button("略過這個版本")
        self.skip.clicked.connect(self.skip_version)
        self.later = button("稍後再說")
        self.later.clicked.connect(self.reject)
        self.browser = button("用瀏覽器下載")
        self.browser.clicked.connect(self.open_browser)
        self.now = button("立即更新", "Primary")
        self.now.clicked.connect(self.update_now)
        row.addWidget(self.skip)
        row.addStretch()
        row.addWidget(self.later)
        row.addWidget(self.browser)
        row.addWidget(self.now)
        self.root.addLayout(row)
        auto = can_self_update() and bool(rel.get("url"))
        self.now.setVisible(auto)
        if not auto:
            self.browser.setObjectName("Primary")

    # ------------------------------------------------------------------
    def skip_version(self) -> None:
        self.ctx.db.set_setting("update_skip", self.rel["version"])
        self.ctx.toast.emit(f"已略過 {self.rel['version']} 版，有更新的版本時會再通知您")
        self.reject()

    def open_browser(self) -> None:
        QDesktopServices.openUrl(QUrl(self.rel.get("url") or self.rel.get("page") or online.RELEASE_PAGE))
        self.accept()

    def update_now(self) -> None:
        folder = _download_dir()
        dest = os.path.join(folder, f"MyLedger_{self.rel['version']}.exe")
        self._busy("正在下載新版本，請稍候…（下載完成後會自動換成新版並重新開啟）")
        self.bar.setRange(0, 0)
        self._job = _Download(self.rel, dest, self)
        self._job.progress.connect(self._progress)
        self._job.done.connect(self._downloaded)
        self._job.failed.connect(self._failed)
        self._job.start()

    def _busy(self, text: str | None) -> None:
        """下載中：顯示進度並收起按鈕；text=None 時恢復。"""
        on = text is not None
        self.status.setText(text or "")
        self.status.setVisible(on)
        self.bar.setVisible(on)
        for b in (self.skip, self.later, self.browser):
            b.setVisible(not on)
        self.now.setVisible(not on and can_self_update() and bool(self.rel.get("url")))

    def _progress(self, got: int, total: int) -> None:
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(got * 1000 / total))
            self.status.setText(f"正在下載新版本… {got / 1e6:.1f} / {total / 1e6:.1f} MB")

    def _failed(self, text: str) -> None:
        self._busy(None)
        self.show_error(text + "　也可以按「用瀏覽器下載」。")

    def _downloaded(self, path: str) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.status.setText("下載完成，正在更新…")
        exe = sys.executable
        if os.path.dirname(path) != os.path.dirname(exe):
            # 程式放在無法寫入的資料夾（例如 Program Files）：請她手動換檔
            info(self, f"新版本已下載到：\n{path}\n\n因為目前程式所在的資料夾無法直接更新，"
                       "請關閉程式後，用這個新檔案取代原本的程式。")
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
            self.accept()
            return
        try:
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.ctx.db.backup_to(os.path.join(self.ctx.backup_dir, f"更新前備份_v{APP_VERSION}_{stamp}.db"))
            install(path, exe)
        except OSError as e:
            self._failed(f"無法替換程式檔（{e.strerror or e}），目前的程式與資料都沒有改變。")
            return
        info(self, f"已更新為 {self.rel['version']} 版，按「確定」後程式會重新開啟。")
        win = self.parent().window() if self.parent() else None
        if win is not None:
            win.close()          # 關閉主視窗時會先關閉帳本資料庫
        try:
            restart(exe)
        except OSError:
            error(None, "新版本已安裝，但無法自動重新開啟，請再點一下程式圖示開啟。")
        QApplication.instance().quit()

    def reject(self) -> None:
        if self._job and self._job.isRunning():
            return          # 下載中不關閉，避免留下不完整的檔案
        super().reject()


# ---------------------------------------------------------------------- 檢查流程
def check_for_updates(ctx: AppContext, parent, silent: bool = False) -> None:
    """在背景查詢最新版本。silent=True（開啟程式時自動檢查）：沒有新版或失敗時不打擾。"""
    def done(rel: dict) -> None:
        ctx.db.set_setting("update_last_check", dt.date.today().isoformat())
        if online.is_newer(rel["version"], APP_VERSION):
            if silent and ctx.db.get_setting("update_skip", "") == rel["version"]:
                return
            UpdateDialog(ctx, rel, parent).exec()
        elif not silent:
            info(parent, f"目前使用的 {APP_VERSION} 版已經是最新版本。")

    def fail(text: str) -> None:
        if not silent:
            error(parent, text)

    if not silent:
        ctx.toast.emit("正在檢查新版本…")
    online.run_background(parent, online.fetch_latest_release, done, fail)


def auto_check_due(ctx: AppContext) -> bool:
    db = ctx.db
    return db.get_setting("update_auto", "1") == "1" and \
        db.get_setting("update_last_check", "") != dt.date.today().isoformat()
