"""版面檢查：在三種字型大小、兩種視窗大小下開啟每一頁、每個分頁與主要對話框，
找出被截斷的文字、互相重疊的元件與執行錯誤，並存下截圖供人工檢視。

usage: python tools/layout_audit.py <out_dir> [ledger.db]
  沒有指定帳本時載入範例資料。結果寫在 <out_dir>/report.txt，截圖在 <out_dir>/*.png。
  結束碼：有執行錯誤時為 1（版面問題只列在報告中，需人工判斷）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QAbstractScrollArea, QApplication, QComboBox,  # noqa: E402
                               QLabel, QLineEdit, QMenu, QTabBar, QTabWidget, QTableView, QToolButton,
                               QTreeWidget, QWidget)

from app import dialogs_chart, dialogs_more, dialogs_search, dialogs_update, widgets  # noqa: E402
from app.pages import accounts as p_acc, investments as p_inv, settings as p_set  # noqa: E402
from app.pages import transactions as p_txn  # noqa: E402

for mod in (widgets, p_acc, p_set, p_txn, p_inv, dialogs_more, dialogs_chart, dialogs_search, dialogs_update):
    for name in ("ask",):
        if hasattr(mod, name):
            setattr(mod, name, lambda *a, **k: True)
    for name in ("info", "error", "warn"):
        if hasattr(mod, name):
            setattr(mod, name, lambda *a, **k: None)

from app import animations  # noqa: E402
from app.main import MainWindow, apply_theme, create_app  # noqa: E402
from app.sample_data import load_sample_data  # noqa: E402
from app.theme import FONT_SCALES  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "layout_audit"
os.makedirs(out, exist_ok=True)
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "理財帳本.db")
if len(sys.argv) > 2:
    shutil.copy(sys.argv[2], path)
try:
    app, ctx = create_app([sys.argv[0]], path)
except Exception:  # noqa: BLE001
    traceback.print_exc()
    sys.exit(2)
errors: list[str] = []
sys.excepthook = lambda t, e, tb: errors.append("".join(traceback.format_exception(t, e, tb)))
if len(sys.argv) <= 2:
    ctx.db.set_setting("owner_name", "游媽媽")
    load_sample_data(ctx.db)
    # 標籤：讓收支明細的標籤篩選與「標籤／專案」分頁有內容可檢查（名稱刻意取長一點）
    _rows = ctx.db.query_transactions(ttype="expense")
    ctx.db.add_tag([r["id"] for r in _rows[:6]], "日本關西自由行 2026")
    ctx.db.add_tag([r["id"] for r in _rows[3:9]], "房屋修繕")
ctx.db.set_setting("first_run_done", "1")
animations.set_enabled(False)
try:
    win = MainWindow(ctx)
except Exception:  # noqa: BLE001
    traceback.print_exc()
    sys.exit(2)
win.show()

report: list[str] = []
seen: set[str] = set()


def pump(n=20, wait=0.15):
    for _ in range(n):
        app.processEvents()
    time.sleep(wait)
    for _ in range(n):
        app.processEvents()


def path_of(w: QWidget, root: QWidget) -> str:
    parts = []
    while w is not None and w is not root:
        n = w.objectName() or type(w).__name__
        txt = ""
        if isinstance(w, (QLabel, QAbstractButton)) and w.text():
            txt = f"「{w.text()[:24]}」"
        parts.append(n + txt)
        w = w.parentWidget()
    return " / ".join(reversed(parts[:3]))


def in_scroll_content(w: QWidget, root: QWidget) -> bool:
    p = w.parentWidget()
    while p is not None and p is not root:
        if isinstance(p, QAbstractScrollArea) and not isinstance(p, (QTableView, QTreeWidget)):
            return True
        p = p.parentWidget()
    return False


def visible_rect(w: QWidget, root: QWidget) -> QRect:
    """元件實際可見的範圍（被父元件裁切後），以 root 座標表示。"""
    r = QRect(w.mapTo(root, w.rect().topLeft()), w.size())
    p = w.parentWidget()
    while p is not None and p is not root:
        r = r.intersected(QRect(p.mapTo(root, p.rect().topLeft()), p.size()))
        p = p.parentWidget()
    return r


def is_shown(w: QWidget, root: QWidget) -> bool:
    if not w.isVisibleTo(root) or w.width() <= 2 or w.height() <= 2:
        return False
    return not visible_rect(w, root).isEmpty()


def plain(text: str) -> bool:
    return bool(text) and not ("<" in text and ">" in text)


def check(root: QWidget, where: str) -> list[str]:
    found: list[str] = []
    widgets_ = [w for w in root.findChildren(QWidget) if is_shown(w, root)]
    for w in widgets_:
        if isinstance(w, QMenu) or getattr(w, "autoshrink", False):
            continue    # FitLabel 放不下時會自動縮小字型
        fm = w.fontMetrics()
        if isinstance(w, QLabel) and not w.wordWrap() and plain(w.text()) and w.pixmap().isNull():
            need = max(fm.horizontalAdvance(s) for s in w.text().split("\n"))
            avail = w.contentsRect().width() - 2 * w.margin()
            if need > avail + 1:
                found.append(f"文字被截斷 {need}>{avail}px: {path_of(w, root)}")
            hneed = fm.height() * len(w.text().split("\n"))
            if hneed > w.contentsRect().height() + 3:
                found.append(f"文字高度不足 {hneed}>{w.contentsRect().height()}px: {path_of(w, root)}")
        elif isinstance(w, QLabel) and w.wordWrap() and plain(w.text()):
            need = w.heightForWidth(w.width())
            if need > w.height() + 3:
                found.append(f"換行文字高度不足 {need}>{w.height()}px: {path_of(w, root)}")
        elif isinstance(w, QAbstractButton) and not isinstance(w, QToolButton) and w.text():
            sh = w.sizeHint()
            if sh.width() > w.width() + 1:
                found.append(f"按鈕文字被截斷 {sh.width()}>{w.width()}px: {path_of(w, root)}")
            if sh.height() > w.height() + 4:
                found.append(f"按鈕高度不足 {sh.height()}>{w.height()}px: {path_of(w, root)}")
        elif isinstance(w, QComboBox) and w.currentText():
            need = fm.horizontalAdvance(w.currentText()) + 44
            if need > w.width() + 1:
                found.append(f"下拉選單文字被截斷 {need}>{w.width()}px: {path_of(w, root)}「{w.currentText()[:20]}」")
        elif isinstance(w, QLineEdit) and not w.text() and w.placeholderText() and w.isEnabled():
            need = fm.horizontalAdvance(w.placeholderText()) + 24
            if need > w.width() + 1:
                found.append(f"提示文字被截斷 {need}>{w.width()}px: {path_of(w, root)}「{w.placeholderText()[:20]}」")
        elif isinstance(w, QTabBar) and w.count():
            last = w.tabRect(w.count() - 1)
            if last.right() > w.width() + 1:
                found.append(f"分頁標籤超出寬度 {last.right()}>{w.width()}px: {path_of(w, root)}")
        if isinstance(w, QTableView):
            found += check_table(w, root)
        if isinstance(w, QTreeWidget):
            found += check_tree(w, root)
    # 重疊：同一個版面配置中的兄弟元件
    for w in [root] + widgets_:
        lay = w.layout()
        if lay is None:
            continue
        kids = [c for c in w.children() if isinstance(c, QWidget) and is_shown(c, root)
                and not c.isWindow() and type(c).__name__ not in ("NavIndicator", "Toast", "QSizeGrip")
                and lay.indexOf(c) >= 0]
        for i, a in enumerate(kids):
            for b in kids[i + 1:]:
                ra, rb = a.geometry().adjusted(1, 1, -1, -1), b.geometry().adjusted(1, 1, -1, -1)
                if ra.intersects(rb):
                    found.append(f"元件重疊: {path_of(a, root)}  ×  {path_of(b, root)}")
        # 超出父元件（含巢狀版面中的元件）
        if not in_scroll_content(w, root) and w is not root:
            for c in [c for c in w.children() if isinstance(c, QWidget) and is_shown(c, root)
                      and not c.isWindow() and type(c).__name__ not in ("NavIndicator", "Toast", "QSizeGrip")]:
                g = c.geometry()
                if g.right() > w.width() + 2 or g.bottom() > w.height() + 2:
                    found.append(f"超出父元件範圍 ({g.right()},{g.bottom()})>({w.width()},{w.height()}): "
                                 f"{path_of(c, root)}")
    return [f"[{where}] {s}" for s in found]


def check_table(t: QTableView, root: QWidget) -> list[str]:
    found = []
    hh = t.horizontalHeader()
    model = t.model()
    if model is None:
        return found
    if hh.length() > t.viewport().width() + 2 and model.rowCount():
        found.append(f"表格需水平捲動（欄位總寬 {hh.length()}>{t.viewport().width()}px）: {path_of(t, root)}")
    fm = t.fontMetrics()
    bold = t.font()
    bold.setBold(True)
    from PySide6.QtGui import QFontMetrics
    bfm = QFontMetrics(bold)
    for c in range(model.columnCount()):
        if t.isColumnHidden(c) or hh.sectionSize(c) <= 0:
            continue
        head = str(model.headerData(c, Qt.Orientation.Horizontal) or "")
        if head and bfm.horizontalAdvance(head) + 18 > hh.sectionSize(c) + 1:
            found.append(f"表頭被截斷「{head}」{bfm.horizontalAdvance(head) + 18}>{hh.sectionSize(c)}px: "
                         f"{path_of(t, root)}")
        stretch = hh.sectionResizeMode(c).name == "Stretch"
        cols = getattr(t, "columns", None)
        if (not cols and stretch) or (cols and cols[c].stretch and (cols[c].elide or hh.sectionSize(c) >= t.STRETCH_CAP)):
            continue   # 長文字欄位（說明、備註）以省略號顯示、滑鼠提示完整內容
        if model.rowCount() and t.indexWidget(model.index(0, c)) is not None:
            continue   # 輸入欄位（金額、備註編輯框）不是文字
        need = t.sizeHintForColumn(c)
        if need > hh.sectionSize(c) + 1 and model.rowCount():
            found.append(f"表格內容被截斷「{head}」欄 {need}>{hh.sectionSize(c)}px: {path_of(t, root)}")
    return found


def check_tree(t: QTreeWidget, root: QWidget) -> list[str]:
    found = []
    from PySide6.QtGui import QFontMetrics
    hh = t.header()
    if hh.length() > t.viewport().width() + 2:
        found.append(f"報表需水平捲動（欄位總寬 {hh.length()}>{t.viewport().width()}px）: {path_of(t, root)}")
    for c in range(t.columnCount()):
        if t.isColumnHidden(c):
            continue
        head = t.headerItem().text(c)
        bold = t.font()
        bold.setBold(True)
        if head and QFontMetrics(bold).horizontalAdvance(head) + 18 > hh.sectionSize(c) + 1:
            found.append(f"表頭被截斷「{head}」: {path_of(t, root)}")
        if any(t.topLevelItem(i).isFirstColumnSpanned() for i in range(t.topLevelItemCount())) and c == 0:
            continue
        need = t.sizeHintForColumn(c)
        if need > hh.sectionSize(c) + 1:
            found.append(f"報表內容被截斷「{head}」欄 {need}>{hh.sectionSize(c)}px: {path_of(t, root)}")
    return found


def record(where: str, root: QWidget, shot: str | None = None) -> None:
    pump()
    issues = check(root, where)
    for s in issues:
        key = s.split("] ", 1)[1] + where.split("@")[-1]
        if key not in seen:
            seen.add(key)
            report.append(s)
    if shot:
        root.grab().save(os.path.join(out, shot + ".png"))


def set_scale(key: str) -> None:
    ctx.db.set_setting("font_scale", key)
    apply_theme(app, ctx)
    ctx.settingsChanged.emit()
    pump()


def visit_pages(tag: str, shots: bool) -> None:
    for key, page in win.pages.items():
        try:
            win.go(key, animate=False)
            pump()
            record(f"{key}@{tag}", win, f"{tag}_{key}" if shots else None)
            for tabs in page.findChildren(QTabWidget):
                for i in range(tabs.count()):
                    tabs.setCurrentIndex(i)
                    pump()
                    name = tabs.tabText(i)
                    record(f"{key}/{name}@{tag}", win, f"{tag}_{key}_{i}" if shots else None)
                tabs.setCurrentIndex(0)
            if key == "settings":
                from PySide6.QtWidgets import QScrollArea
                area = page.findChild(QScrollArea)
                if area:
                    bar = area.verticalScrollBar()
                    for n, v in enumerate(range(0, bar.maximum() + 1, max(1, area.viewport().height() - 80))):
                        bar.setValue(v)
                        pump()
                        record(f"settings(捲動{n})@{tag}", win, f"{tag}_settings_scroll{n}" if shots else None)
                    bar.setValue(0)
        except Exception:  # noqa: BLE001
            errors.append(f"{key}@{tag}\n{traceback.format_exc()}")


def dialogs() -> list[tuple[str, callable]]:
    from app.dialogs import AccountDialog, AdjustDialog, ExportDialog, TransactionDialog, WelcomeDialog
    from app.dialogs_chart import ChartOfAccountsDialog, SubjectDialog
    from app.dialogs_invest import (PriceDialog, RateDialog, SecurityDialog, SecurityListDialog,
                                    SecurityTypesDialog, TradeDialog)
    from app.dialogs_more import (AuditDialog, DueRecurringDialog, ImportDialog, JournalDialog,
                                  RecurringEditDialog, RecurringManagerDialog, ReconcileDialog,
                                  TagPickDialog, TemplateEditDialog, TemplateManagerDialog, VoidDialog,
                                  YearCloseDialog)
    from app.dialogs_print import AnnualReportDialog, PrintDialog
    from app.dialogs_search import SearchDialog
    from app.dialogs_update import UpdateDialog
    from app.investments import Investments
    db = ctx.db
    inv = Investments(db)
    secs = inv.list_securities()
    sid = secs[0]["id"] if secs else None
    accs = db.list_accounts()
    usd = next((a for a in accs if a["currency"] != ctx.base), None)
    rec = db.list_recurring()
    jtx = next((t for t in db.query_transactions() if t["type"] == "journal"), None)
    etx = next((t for t in db.query_transactions() if t["type"] == "expense"), None)
    lo, hi = db.date_range()
    rel = {"version": "9.9.0", "tag": "v9.9.0", "published": hi,
           "notes": "## 新功能\n- 比較財務報表\n- 年化報酬率\n\n## 修正\n- 版面調整",
           "url": "https://example.invalid/MyLedger.exe", "size": 52_000_000, "sha256": "", "page": ""}

    def search():
        d = SearchDialog(ctx, win)
        d.box.setText("全聯")
        d.run()
        return d

    out_ = [
        ("記一筆_支出", lambda: TransactionDialog(ctx, "expense", parent=win)),
        ("記一筆_收入", lambda: TransactionDialog(ctx, "income", parent=win)),
        ("記一筆_轉帳", lambda: TransactionDialog(ctx, "transfer", parent=win)),
        ("編輯支出", lambda: TransactionDialog(ctx, txn=etx, parent=win) if etx else None),
        ("新增帳戶", lambda: AccountDialog(ctx, parent=win)),
        ("編輯外幣帳戶", lambda: AccountDialog(ctx, usd, parent=win) if usd else None),
        ("餘額調整", lambda: AdjustDialog(ctx, parent=win)),
        ("匯出", lambda: ExportDialog(ctx, win)),
        ("歡迎", lambda: WelcomeDialog(ctx, win)),
        ("列印", lambda: PrintDialog(ctx, lo, hi, win)),
        ("年度財務報告", lambda: AnnualReportDialog(ctx, win)),
        ("加上標籤", lambda: TagPickDialog(ctx, 3, win)),
        ("複式分錄", lambda: JournalDialog(ctx, parent=win)),
        ("編輯分錄", lambda: JournalDialog(ctx, txn=jtx, parent=win) if jtx else None),
        ("範本管理", lambda: TemplateManagerDialog(ctx, win)),
        ("編輯範本", lambda: TemplateEditDialog(ctx, parent=win)),
        ("年度結帳", lambda: YearCloseDialog(ctx, int(hi[:4]) - 1, win)),
        ("作廢", lambda: VoidDialog(win)),
        ("異動紀錄", lambda: AuditDialog(ctx, parent=win)),
        ("定期交易", lambda: RecurringManagerDialog(ctx, win)),
        ("編輯定期", lambda: RecurringEditDialog(ctx, rec[0] if rec else None, parent=win)),
        ("到期定期", lambda: DueRecurringDialog(ctx, [(rec[0], hi)], win) if rec else None),
        ("對帳", lambda: ReconcileDialog(ctx, accs[0]["id"], win)),
        ("匯入", lambda: ImportDialog(ctx, win)),
        ("會計科目表", lambda: ChartOfAccountsDialog(ctx, win)),
        ("新增科目", lambda: SubjectDialog(ctx, "asset", parent=win)),
        ("買進", lambda: TradeDialog(ctx, "buy", sid, parent=win)),
        ("賣出", lambda: TradeDialog(ctx, "sell", sid, parent=win)),
        ("現金股利", lambda: TradeDialog(ctx, "cash_div", sid, parent=win)),
        ("股票股利", lambda: TradeDialog(ctx, "stock_div", sid, parent=win)),
        ("市價評價", lambda: PriceDialog(ctx, win)),
        ("匯率", lambda: RateDialog(ctx, win)),
        ("新增標的", lambda: SecurityDialog(ctx, parent=win)),
        ("標的設定", lambda: SecurityListDialog(ctx, win)),
        ("標的類型", lambda: SecurityTypesDialog(ctx, win)),
        ("搜尋", search),
        ("新版本", lambda: UpdateDialog(ctx, rel, win)),
    ]
    return out_


def visit_dialogs(tag: str, shots: bool) -> None:
    for name, make in dialogs():
        try:
            d = make()
            if d is None:
                continue
            d.show()
            pump()
            record(f"視窗:{name}@{tag}", d, f"{tag}_dlg_{name}" if shots else None)
            d.close()
            d.deleteLater()
        except Exception:  # noqa: BLE001
            errors.append(f"視窗:{name}@{tag}\n{traceback.format_exc()}")


for scale in FONT_SCALES:
    set_scale(scale)
    for size in ((1380, 900), (1100, 700)):
        win.showNormal()
        win.resize(*size)
        pump()
        tag = f"{scale}_{size[0]}"
        visit_pages(tag, shots=True)
    visit_dialogs(scale, shots=True)
set_scale("large")

with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as fh:
    fh.write(f"版面問題 {len(report)} 項，執行錯誤 {len(errors)} 項\n\n")
    fh.write("\n".join(report))
    if errors:
        fh.write("\n\n==== 執行錯誤 ====\n" + "\n".join(errors))
print(f"LAYOUT AUDIT: {len(report)} layout issues, {len(errors)} errors -> {out}")
win.close()
sys.exit(1 if errors else 0)
