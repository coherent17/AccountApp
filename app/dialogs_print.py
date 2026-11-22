"""列印／存成 PDF 視窗。"""

from __future__ import annotations

import os

from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel

from .context import AppContext
from .dialogs import BaseDialog, open_path
from .printing import ANNUAL_SECTIONS, REPORTS, Report, print_html, save_pdf, setup_printer
from .statements import COMPARE_MODES
from .theme import fmt_date, icon
from .widgets import button, section_title


def preview(parent, html: str, landscape: bool = False) -> None:
    """預覽列印：可從預覽視窗直接列印（也可選 Microsoft Print to PDF）。"""
    printer = setup_printer(QPrinter(QPrinter.PrinterMode.HighResolution), landscape)
    dlg = QPrintPreviewDialog(printer, parent)
    dlg.setWindowTitle("預覽列印")
    dlg.paintRequested.connect(lambda p: print_html(html, p))
    dlg.resize(1000, 800)
    dlg.exec()


def print_voucher(ctx: AppContext, txn_id: int, parent=None) -> None:
    preview(parent, Report(ctx.db).build_voucher(txn_id))


class PrintDialog(BaseDialog):
    def __init__(self, ctx: AppContext, start: str, end: str, parent=None):
        super().__init__("列印／存成 PDF", parent, width=560)
        self.ctx = ctx
        self.start, self.end = start, end
        self.root.addWidget(section_title("選擇要列印的報表"))
        period = QLabel(f"報表期間：{fmt_date(start)} 至 {fmt_date(end)}（資產負債表以期末日為基準日）。"
                        "要改期間，請先在財務報表頁上方選擇。")
        period.setObjectName("Hint")
        period.setWordWrap(True)
        self.root.addWidget(period)
        saved = ctx.db.get_json("print_reports", None)
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        self.boxes: dict[str, QCheckBox] = {}
        for i, (key, name) in enumerate(REPORTS):
            cb = QCheckBox(name)
            cb.setChecked(key in saved if saved is not None else key in ("bs", "is", "trial"))
            grid.addWidget(cb, i // 2, i % 2)
            self.boxes[key] = cb
        self.root.addLayout(grid)
        cr = QHBoxLayout()
        cr.addWidget(QLabel("資產負債表、收支損益表與財務比率"))
        self.compare = QComboBox()
        for k, label in COMPARE_MODES:
            self.compare.addItem(label, k)
        self.compare.setCurrentIndex(max(0, self.compare.findData(ctx.db.get_setting("print_compare", "none"))))
        cr.addWidget(self.compare)
        cr.addStretch()
        self.root.addLayout(cr)
        self.landscape = QCheckBox("橫向列印（試算表、總分類帳欄位較多時建議使用）")
        self.root.addWidget(self.landscape)
        hint = QLabel("每份報表從新的一頁開始，表頭在每頁重複，頁尾有頁碼。傳票含核准、會計、覆核、製單簽章欄。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self.root.addWidget(hint)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        bar.addStretch()
        for text, kind, ic, fn in (("取消", None, None, self.reject), ("預覽列印", None, "list", self.do_preview),
                                   ("存成 PDF", None, "download", self.do_pdf), ("列印", "Primary", None, self.do_print)):
            b = button(text, kind, ic or None)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.root.addLayout(bar)

    def chosen(self) -> list[str]:
        keys = [k for k, cb in self.boxes.items() if cb.isChecked()]
        if keys:
            self.ctx.db.set_json("print_reports", keys)
        return keys

    def html(self) -> str | None:
        keys = self.chosen()
        if not keys:
            self.show_error("請至少勾選一份報表")
            return None
        mode = self.compare.currentData()
        self.ctx.db.set_setting("print_compare", mode)
        return Report(self.ctx.db).build(keys, self.start, self.end, mode)

    def do_preview(self) -> None:
        html = self.html()
        if html:
            preview(self, html, self.landscape.isChecked())

    def export_pdf(self, path: str) -> str | None:
        html = self.html()
        if not html:
            return None
        try:
            return save_pdf(html, path, self.landscape.isChecked())
        except OSError as e:
            self.show_error(f"無法寫入檔案：{e}")
            return None

    def do_pdf(self) -> None:
        if not self.chosen():
            self.show_error("請至少勾選一份報表")
            return
        os.makedirs(self.ctx.export_dir, exist_ok=True)
        default = os.path.join(self.ctx.export_dir,
                               f"理財報表_{self.start.replace('-', '')}-{self.end.replace('-', '')}.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "存成 PDF", default, "PDF 檔 (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self.export_pdf(path):
            open_path(path)
            self.ctx.toast.emit("PDF 已儲存")
            self.accept()

    def do_print(self) -> None:
        html = self.html()
        if not html:
            return
        printer = setup_printer(QPrinter(QPrinter.PrinterMode.HighResolution), self.landscape.isChecked())
        if QPrintDialog(printer, self).exec():
            print_html(html, printer)
            self.ctx.toast.emit("已送出列印")
            self.accept()


class AnnualReportDialog(BaseDialog):
    """年度財務報告：選年度與章節，一鍵預覽、存成 PDF 或列印。"""

    def __init__(self, ctx: AppContext, parent=None, year: int | None = None):
        import datetime as dt
        super().__init__("年度財務報告", parent, width=620)
        self.ctx = ctx
        self.root.addWidget(section_title("一份完整的年度報告"))
        intro = QLabel("包含封面與目錄、年度摘要，以及與去年比較的資產負債表、收支損益表等。"
                       "每一章從新的一頁開始，適合存成 PDF 保存或印出來裝訂。")
        intro.setObjectName("Hint")
        intro.setWordWrap(True)
        self.root.addWidget(intro)
        yr = QHBoxLayout()
        yr.addWidget(QLabel("年度"))
        self.year = QComboBox()
        today = dt.date.today()
        first = ctx.db.first_year() or today.year
        for y in range(today.year, first - 1, -1):
            self.year.addItem(f"{y} 年（民國 {y - 1911} 年）" + ("　進行中" if y == today.year else ""), y)
        default = year or (today.year - 1 if today.month <= 3 and first < today.year else today.year)
        self.year.setCurrentIndex(max(0, self.year.findData(default)))
        yr.addWidget(self.year)
        yr.addStretch()
        self.root.addLayout(yr)
        saved = ctx.db.get_json("annual_sections", None)
        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        self.boxes: dict[str, QCheckBox] = {}
        for i, (key, name, on) in enumerate(ANNUAL_SECTIONS):
            cb = QCheckBox(name)
            cb.setChecked(key in saved if saved is not None else on)
            grid.addWidget(cb, i, 0)
            self.boxes[key] = cb
        self.root.addLayout(grid)
        self.root.addWidget(self.msg)
        bar = QHBoxLayout()
        bar.addStretch()
        for text, kind, ic, fn in (("取消", None, None, self.reject), ("預覽", None, "eye", self.do_preview),
                                   ("列印", None, "print", self.do_print),
                                   ("存成 PDF", "Primary", "download", self.do_pdf)):
            b = button(text, kind, ic or None)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.root.addLayout(bar)

    def chosen(self) -> list[str]:
        keys = [k for k, cb in self.boxes.items() if cb.isChecked()]
        self.ctx.db.set_json("annual_sections", keys)
        return keys

    def html(self) -> str:
        return Report(self.ctx.db).annual(self.year.currentData(), self.chosen())

    def do_preview(self) -> None:
        preview(self, self.html())

    def export_pdf(self, path: str) -> str | None:
        try:
            return save_pdf(self.html(), path)
        except OSError as e:
            self.show_error(f"無法寫入檔案：{e}")
            return None

    def do_pdf(self) -> None:
        os.makedirs(self.ctx.export_dir, exist_ok=True)
        default = os.path.join(self.ctx.export_dir, f"{self.year.currentData()}年度財務報告.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "存成 PDF", default, "PDF 檔 (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        if self.export_pdf(path):
            open_path(path)
            self.ctx.toast.emit("年度財務報告已儲存")
            self.accept()

    def do_print(self) -> None:
        printer = setup_printer(QPrinter(QPrinter.PrinterMode.HighResolution))
        if QPrintDialog(printer, self).exec():
            print_html(self.html(), printer)
            self.ctx.toast.emit("已送出列印")
            self.accept()
