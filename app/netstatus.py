"""側邊欄的「網路狀態」小燈號：定期檢查是否連得上網路。

只嘗試與 GitHub（檢查新版本用的網站）建立連線，不傳送任何資料。沒有網路時所有記帳功能
照常使用；只有「檢查新版本」與「從網路取得匯率／股價」需要網路。
"""

from __future__ import annotations

import datetime as dt
import socket

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QPushButton

PROBE_HOST = ("api.github.com", 443)
INTERVAL_MS = 5 * 60 * 1000        # 每 5 分鐘檢查一次
ON_COLOR, OFF_COLOR, WAIT_COLOR = "#34D399", "#F87171", "#94A3B8"


def probe(timeout: float = 4.0) -> bool:
    """能否連上網路（只建立連線後立即關閉）。"""
    try:
        with socket.create_connection(PROBE_HOST, timeout=timeout):
            return True
    except OSError:
        return False


class _Probe(QThread):
    result = Signal(bool)

    def run(self):
        self.result.emit(bool(probe()))


class NetStatus(QPushButton):
    """顯示「● 網路：已連線／離線」；按一下立即重新檢查。"""

    changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NetStatus")
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.online: bool | None = None
        self.checked_at: dt.datetime | None = None
        self._job = _Probe(self)
        self._job.result.connect(self._apply)
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self.check_now)
        self.clicked.connect(self.check_now)
        self._show("網路：檢查中…", WAIT_COLOR)

    def start(self, first_delay_ms: int = 1500) -> None:
        self._timer.start()
        QTimer.singleShot(first_delay_ms, self.check_now)

    def stop(self) -> None:
        self._timer.stop()
        self._job.wait(5000)

    def check_now(self) -> None:
        if self._job.isRunning():
            return
        if self.online is None:
            self._show("網路：檢查中…", WAIT_COLOR)
        self._job.start()

    def _show(self, text: str, color: str) -> None:
        self.setText(f"●  {text}")
        self.setStyleSheet(f"#NetStatus {{ color: {color}; border: none; background: transparent;"
                           " text-align: left; padding: 2px 0; font-weight: 700; }"
                           "#NetStatus:hover { text-decoration: underline; }")

    def _apply(self, ok: bool) -> None:
        prev = self.online
        self.online = ok
        self.checked_at = dt.datetime.now()
        self._show("網路：已連線" if ok else "網路：離線", ON_COLOR if ok else OFF_COLOR)
        self.setToolTip(
            ("目前可以連上網路。" if ok else "目前連不上網路。沒有網路時記帳、報表、備份等功能都照常使用；") +
            ("" if ok else "只有「檢查新版本」與「從網路取得匯率／股價」需要網路。") +
            f"\n最後檢查：{self.checked_at:%H:%M}（每 5 分鐘自動檢查，按一下可立即重新檢查）")
        if ok != prev:
            self.changed.emit(ok)
