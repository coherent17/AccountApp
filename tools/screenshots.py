"""產生各頁面截圖（用於檢查 UI 與說明文件）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.main import MainWindow, create_app  # noqa: E402
from app.sample_data import load_sample_data  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "shots"
os.makedirs(out, exist_ok=True)
tmp = tempfile.mkdtemp()
app, ctx = create_app([sys.argv[0]], os.path.join(tmp, "ledger.db"))
ctx.db.set_setting("owner_name", "游媽媽")
load_sample_data(ctx.db)
from app import animations  # noqa: E402
animations.set_enabled(False)
ctx.db.set_setting("sample_data", "0")
win = MainWindow(ctx)
win.resize(1440, 920)
win.show()


def pump(n=20):
    for _ in range(n):
        app.processEvents()


def snap(name, w=None):
    pump()
    (w or win).grab().save(os.path.join(out, name + ".png"))
    print("saved", name)


for key in ["dashboard", "transactions", "accounts", "investments", "reports", "retirement", "settings"]:
    win.go(key)
    pump(40)
    import time; time.sleep(0.7); pump(40)
    snap(key)
from PySide6.QtWidgets import QScrollArea  # noqa: E402
win.go("retirement", animate=False)
pump(30)
_sa = win.pages["retirement"].findChild(QScrollArea)
_sa.verticalScrollBar().setValue(470)
pump(30); time.sleep(0.6); pump(20)
snap("retirement_2")
_sa.verticalScrollBar().setValue(_sa.verticalScrollBar().maximum())
pump(30); time.sleep(0.6); pump(20)
snap("retirement_3")
_sa.verticalScrollBar().setValue(0)
rep = win.pages["reports"]
for i in range(1, rep.tabs.count()):
    win.go("reports")
    rep.tabs.setCurrentIndex(i)
    pump(40); time.sleep(0.7); pump(20)
    snap(f"reports_{i}")

from app.dialogs import (AccountDialog, AdjustDialog, ExportDialog,  # noqa: E402
                         TransactionDialog, WelcomeDialog)
from app.dialogs_invest import PriceDialog, RateDialog, TradeDialog  # noqa: E402
from app.dialogs_more import (AuditDialog, DueRecurringDialog, ImportDialog,  # noqa: E402
                              JournalDialog, ReconcileDialog,
                              RecurringManagerDialog)
from app.investments import Investments  # noqa: E402

inv_page = win.pages["investments"]
for i in range(1, inv_page.tabs.count()):
    win.go("investments", animate=False)
    inv_page.tabs.setCurrentIndex(i)
    pump(40); time.sleep(0.5); pump(20)
    snap(f"investments_{i}")
rep.compare.setChecked(True)
win.go("reports", animate=False)
rep.tabs.setCurrentIndex(1)
pump(40); time.sleep(0.5)
snap("reports_compare")
jd = JournalDialog(ctx, parent=win)
jd.apply_template(1)
sec = Investments(ctx.db).holdings()[0]
post = next(a for a in ctx.db.list_accounts() if a["name"] == "郵局活儲")
rec = ctx.db.list_recurring()[0]
extra = [("dlg_journal", jd),
         ("dlg_journal_edit", JournalDialog(ctx, ctx.db.get_transaction(
             ctx.db.query_transactions(keyword="年繳保費")[0]["id"]), parent=win)),
         ("dlg_buy", TradeDialog(ctx, "buy", sec["id"], parent=win)),
         ("dlg_sell", TradeDialog(ctx, "sell", sec["id"], parent=win)),
         ("dlg_div", TradeDialog(ctx, "cash_div", sec["id"], parent=win)),
         ("dlg_price", PriceDialog(ctx, win)),
         ("dlg_rate", RateDialog(ctx, win)),
         ("dlg_reconcile", ReconcileDialog(ctx, post["id"], win)),
         ("dlg_recurring", RecurringManagerDialog(ctx, win)),
         ("dlg_due", DueRecurringDialog(ctx, [(rec, "2026-10-05")], win)),
         ("dlg_import", ImportDialog(ctx, win)),
         ("dlg_audit", AuditDialog(ctx, parent=win))]
# 會計科目表、新增科目、分錄連結投資標的
from app.dialogs_chart import ChartOfAccountsDialog, SubjectDialog  # noqa: E402
jdi = JournalDialog(ctx, parent=win)
jdi.apply_template(next(i for i, (n, _) in enumerate(JournalDialog.TEMPLATES) if n.startswith("買進股票")))
s0050 = next(x for x in Investments(ctx.db).list_securities() if x["code"] == "0050")
c0 = jdi.table.cellWidget(0, 3)
c0.sec.setCurrentIndex(c0.sec.findData(s0050["id"]))
jdi._sec_chosen(c0, jdi.table.cellWidget(0, 0))
c0.shares.setText("500")
jdi.table.cellWidget(0, 1).setText("50071")
jdi.table.cellWidget(0, 4).setText("含手續費 71 元")
jdi.table.cellWidget(1, 2).setText("50071")
jdi.note.setText("買進 元大台灣50 500 股")
jdi.update_totals()
sdi = SubjectDialog(ctx, "asset")
sdi.category.setCurrentText("長期投資")
sdi.name.setText("長期投資－中華電信")
extra += [("dlg_chart", ChartOfAccountsDialog(ctx, win)), ("dlg_subject", sdi),
          ("dlg_journal_invest", jdi)]
jd2 = extra[1][1]
for name, dlg in extra:
    dlg.show()
    if name == "dlg_sell":
        dlg.shares.setText("100")
    if name == "dlg_div":
        dlg.amount.setText("21600")
    if name == "dlg_chart":
        dlg.resize(1000, 900)
    snap(name, dlg)
    dlg.close()
for name, dlg in [("dlg_expense", TransactionDialog(ctx, "expense", parent=win)),
                  ("dlg_transfer", TransactionDialog(ctx, "transfer", parent=win)),
                  ("dlg_account", AccountDialog(ctx, parent=win)),
                  ("dlg_account_usd", AccountDialog(ctx, next(a for a in ctx.db.list_accounts()
                                                              if a["currency"] == "USD"), parent=win)),
                  ("dlg_adjust", AdjustDialog(ctx, parent=win)),
                  ("dlg_export", ExportDialog(ctx, win)),
                  ("dlg_welcome", WelcomeDialog(ctx, win))]:
    dlg.show()
    snap(name, dlg)
    dlg.close()

# 範例資料提示列
ctx.db.set_setting("sample_data", "1")
win.go("dashboard", animate=False)
win.pages["dashboard"].refresh()
time.sleep(1.2)
snap("dashboard_sample")
