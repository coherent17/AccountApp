"""資料：匯出 Excel 報表（與 v2 相同的 13 張工作表、公式與平衡檢查）。"""

from __future__ import annotations

import datetime as dt
import os

from desktop.rpc import exposed


class DataApi:
    @exposed
    def export_form(self) -> dict:
        from core.exporter import SHEET_INFO
        db = self._db
        lo, hi = db.date_range()
        today = dt.date.today()
        return {"years": list(range(max(int(hi[:4]), today.year), int(lo[:4]) - 1, -1)), "range": [lo, hi],
                "sheets": SHEET_INFO, "saved": db.get_json("export_sheets", None),
                "folder": os.path.join(self._folder, "匯出報表")}

    @exposed(db=False)
    def pick_save(self, suggested: str) -> str:
        import webview
        os.makedirs(os.path.dirname(suggested), exist_ok=True)
        res = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=os.path.dirname(suggested),
                                              save_filename=os.path.basename(suggested),
                                              file_types=("Excel 活頁簿 (*.xlsx)",))
        if not res:
            return ""
        path = res if isinstance(res, str) else res[0]
        return path if path.lower().endswith(".xlsx") else path + ".xlsx"

    @exposed
    def export_excel(self, start: str, end: str, sheets: list[str], path: str) -> str:
        from core.exporter import export_workbook
        if not sheets:
            raise ValueError("請至少勾選一份報表")
        if not path:
            raise ValueError("請選擇存檔位置")
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db.set_json("export_sheets", sheets)
        try:
            export_workbook(self._db, path, start, end, sheets)
        except PermissionError:
            raise ValueError("無法寫入檔案，可能檔案正在 Excel 中開啟。請先關閉該檔案後再試一次。") from None
        return path
