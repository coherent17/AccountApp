"""應用程式共用狀態：資料庫、路徑與「資料已變更」通知。"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QStandardPaths, Signal

from .database import Database

APP_NAME = "我的理財帳本"
APP_VERSION = "2.6.0"


def data_dir() -> str:
    override = os.environ.get("MY_LEDGER_DATA_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    if not docs:
        docs = os.path.expanduser("~")
    path = os.path.join(docs, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


class AppContext(QObject):
    dataChanged = Signal()
    settingsChanged = Signal()
    navigate = Signal(str, dict)
    toast = Signal(str)

    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.folder = os.path.dirname(db_path) if db_path else data_dir()
        self.db_path = db_path or os.path.join(self.folder, "理財帳本.db")
        self.backup_dir = os.path.join(self.folder, "自動備份")
        self.export_dir = os.path.join(self.folder, "匯出報表")
        self.db = Database(self.db_path)

    @property
    def base(self) -> str:
        return self.db.base_currency

    def changed(self) -> None:
        self.dataChanged.emit()
