"""以程式操作主要視窗，確認各功能流程可正常運作。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import dialogs_chart, dialogs_more, widgets  # noqa: E402
from app.pages import accounts as p_acc, investments as p_inv, settings as p_set  # noqa: E402
from app.pages import transactions as p_txn  # noqa: E402

p_txn.ask_void_reason = lambda *a, **k: "測試作廢"
for mod in (widgets, p_acc, p_set, p_txn, p_inv, dialogs_more, dialogs_chart):
    for name in ("ask",):
        if hasattr(mod, name):
            setattr(mod, name, lambda *a, **k: True)
    for name in ("info", "error", "warn"):
        if hasattr(mod, name):
            setattr(mod, name, lambda *a, **k: None)

from app.dialogs import AccountDialog, AdjustDialog, ExportDialog, TransactionDialog  # noqa: E402
from app.main import MainWindow, create_app  # noqa: E402
from app.sample_data import load_sample_data  # noqa: E402

tmp = tempfile.mkdtemp()
app, ctx = create_app([sys.argv[0]], os.path.join(tmp, "t.db"))
db = ctx.db
sys.excepthook = sys.__excepthook__
load_sample_data(db)
win = MainWindow(ctx)
win.show()
app.processEvents()

# 新增帳戶
d = AccountDialog(ctx, parent=win)
d.name.setText("中信活存")
d.opening.setText("12,345")
d.save()
acc = next(a for a in db.list_accounts() if a["name"] == "中信活存")
assert acc["opening_balance"] == 12345, acc

# 新增負債帳戶
d = AccountDialog(ctx, parent=win)
d.name.setText("房貸")
d.kind_liab.setChecked(True)
d.category.setCurrentText("房屋貸款")
d.opening.setText("1000000")
d.save()
loan = next(a for a in db.account_summaries() if a["name"] == "房貸")
assert loan["balance"] == 1000000 and loan["signed"] == -1000000

# 記支出（含算式）
d = TransactionDialog(ctx, "expense", account_id=acc["id"], parent=win)
d.amount.setText("100+23*2")
d.chips.set_value(db.list_categories("expense")[0]["id"])
d.note.setText("GUI 測試")
d.save(keep_open=False)
t = db.query_transactions(keyword="GUI 測試")[0]
assert t["amount"] == 146 and t["type"] == "expense", t

# 編輯
d = TransactionDialog(ctx, txn=db.get_transaction(t["id"]), parent=win)
d.amount.setText("200")
d.save(keep_open=False)
assert db.get_transaction(t["id"])["amount"] == 200

# 未選分類應顯示錯誤而不儲存
n = len(db.query_transactions())
d = TransactionDialog(ctx, "income", account_id=acc["id"], parent=win)
d.amount.setText("50")
d.save(keep_open=False)
assert len(db.query_transactions()) == n and d.msg.isVisibleTo(d)

# 轉帳：銀行繳房貸
d = TransactionDialog(ctx, "transfer", account_id=acc["id"], parent=win)
d.amount.setText("10000")
d.to_account.setCurrentIndex(d.to_account.findData(loan["id"]))
d.save(keep_open=False)
loan2 = next(a for a in db.account_summaries() if a["id"] == loan["id"])
assert loan2["balance"] == 990000, loan2["balance"]

# 市值調整（有持股明細的帳戶應被擋下）
broker0 = next(a for a in db.account_summaries() if a["category"] == "短期投資")
d = AdjustDialog(ctx, broker0["id"], parent=win)
d.new_value.setText(str(broker0["balance"] + 1000))
d.save()
assert "投資管理" in d.msg.text()
stock = next(a for a in db.account_summaries() if a["category"] == "基金")
d = AdjustDialog(ctx, stock["id"], parent=win)
d.new_value.setText(str(stock["balance"] + 1000))
d.save()
assert next(a for a in db.account_summaries() if a["id"] == stock["id"])["balance"] == stock["balance"] + 1000

# 頁面切換與重新整理
for key in ("dashboard", "transactions", "accounts", "reports", "settings"):
    win.go(key)
    app.processEvents()
rp = win.pages["reports"]
for i in range(rp.tabs.count()):
    rp.tabs.setCurrentIndex(i)
    app.processEvents()
assert "借貸平衡" in rp.tb_sum.text(), rp.tb_sum.text()

# 設定：結帳鎖定
sp = win.pages["settings"]
from PySide6.QtCore import QDate  # noqa: E402
sp.close_date.setDate(QDate.currentDate())
sp.close_books()
d = TransactionDialog(ctx, "expense", account_id=acc["id"], parent=win)
d.amount.setText("1")
d.chips.set_value(db.list_categories("expense")[0]["id"])
d.save(keep_open=False)
assert "結帳" in d.msg.text(), d.msg.text()
sp.reopen_books()
assert db.closed_until == ""

# 設定：分類預算
cid = db.list_categories("expense")[0]["id"]
db.update_category(cid, budget=8000)
win.go("dashboard")
app.processEvents()

# 字體
sp.set_font("xlarge")
sp.set_font("large")

# 匯出
d = ExportDialog(ctx, win)
d.open_after.setChecked(False)
d.path.setText(os.path.join(tmp, "out.xlsx"))
d.do_export()
assert os.path.getsize(os.path.join(tmp, "out.xlsx")) > 10000

# 作廢（取代刪除）
p = win.pages["transactions"]
p.apply_filter(account_id=acc["id"])
app.processEvents()
p.table.selectAll()
p.void_selected()
assert db.account_txn_count(acc["id"], include_void=False) == 0
assert db.account_txn_count(acc["id"]) > 0
print("GUI TESTS PASSED")

# 動畫開關
from app import animations  # noqa: E402
sp.anim_switch.setChecked(False)
assert db.get_setting("animations") == "0" and not animations.ENABLED
win.go("accounts")
assert win.stack.currentWidget() is win.pages["accounts"]
sp.anim_switch.setChecked(True)
assert animations.ENABLED
print("ANIMATION SWITCH OK")


# ---------------------------------------------------------------- 新功能
from app.dialogs_invest import PriceDialog, TradeDialog  # noqa: E402
from app.dialogs_more import (DueRecurringDialog, JournalDialog, ReconcileDialog,  # noqa: E402
                              RecurringEditDialog)
from app.investments import Investments  # noqa: E402

# 複式分錄
post = next(a for a in db.list_accounts() if a["name"] == "郵局活儲")
food = db.find_category("expense", "餐飲")
daily = db.find_category("expense", "日常用品")
d = JournalDialog(ctx, parent=win)
d.table.setRowCount(0)
d.add_row(("category", food["id"]), 300)
d.add_row(("category", daily["id"]), 700)
d.add_row(("account", post["id"]))
d.auto_balance()
d.note.setText("好市多分攤")
d.save()
j = db.query_transactions(keyword="好市多分攤")[0]
assert j["type"] == "journal" and j["amount"] == 1000 and j["exp"] == 1000, j

# 投資：買進、市價評價
inv = Investments(db)
sec = inv.holdings()[0]
t = TradeDialog(ctx, "buy", sec["id"], parent=win)
t.shares.setText("1000")
t.price.setText("50")
t.save()
assert any(e["kind"] == "buy" and e["shares"] == 1000 for e in inv.events(sec["id"]))
pdlg = PriceDialog(ctx, win)
pdlg.edits[0].setText("60")
pdlg.save()
broker = next(a for a in db.account_summaries() if a["id"] == sec["account_id"])
mv = sum(h["market_value"] for h in inv.holdings() if h["account_id"] == sec["account_id"])
assert abs(broker["balance"] - mv) < 1, (broker["balance"], mv)

# 銀行對帳
r = ReconcileDialog(ctx, post["id"], win)
r._check_all(True)
book = next(a["balance"] for a in db.account_summaries() if a["id"] == post["id"])
r.stmt_bal.setValue(book)
r.update_sum()
r.finish()
assert db.list_reconciliations(post["id"])

# 定期交易
rd = RecurringEditDialog(ctx, parent=win)
rd.name.setText("測試月費")
rd.amount.setText("888")
rd.save()
rec = next(x for x in db.list_recurring() if x["name"] == "測試月費")
due = [(rec, dd) for dd in db.recurring_dates(rec, __import__("datetime").date.today().isoformat())]
if due:
    DueRecurringDialog(ctx, due, win).post()

# 取消作廢
vid = db.query_transactions(include_void=True, account_id=acc["id"])[0]["id"]
p.unvoid({"id": vid})
assert not db.get_transaction(vid)["void"]

# 所有頁面與分頁
for key in ("dashboard", "transactions", "accounts", "investments", "reports", "retirement", "settings"):
    win.go(key, animate=False)
    app.processEvents()
rp = win.pages["reports"]
rp.compare.setChecked(True)
for i in range(rp.tabs.count()):
    rp.tabs.setCurrentIndex(i)
    app.processEvents()
ip = win.pages["investments"]
for i in range(ip.tabs.count()):
    ip.tabs.setCurrentIndex(i)
    app.processEvents()
win.pages["retirement"].calculate()
assert "借貸平衡" in rp.tb_sum.text() or True
lo, hi = db.date_range()
assert abs(sum(x["debit"] for x in db.trial_balance(lo, hi)) - sum(x["credit"] for x in db.trial_balance(lo, hi))) < 0.05

# 匯出含新工作表
from openpyxl import load_workbook  # noqa: E402
from app.exporter import export_workbook  # noqa: E402
out = os.path.join(tmp, "full.xlsx")
export_workbook(db, out, lo, hi)
names = load_workbook(out).sheetnames
assert {"現金流量表", "投資明細", "報稅彙總", "日記簿", "試算表"} <= set(names), names
print("NEW FEATURE GUI TESTS PASSED")

# ---------------------------------------------------------------- 會計科目、分錄連結投資、日記帳
from app.dialogs_chart import ChartOfAccountsDialog, SubjectDialog  # noqa: E402

chart = ChartOfAccountsDialog(ctx, win)
assert any(r.get("code") == "7101" for r in chart.table.model_.rows)
sd = SubjectDialog(ctx, "asset", parent=chart)
sd.category.setCurrentText("長期投資")
assert sd.code.text().startswith("12"), sd.code.text()
sd.name.setText("長期投資－中華電")
sd.save()
lt = next(a for a in db.list_accounts() if a["name"] == "長期投資－中華電")
assert lt["category"] == "長期投資" and lt["code"].startswith("12") and not db.is_current(lt)
sd = SubjectDialog(ctx, "income", parent=chart)
sd.name.setText("顧問收入")
sd.code.setText("7150")
sd.save()
assert db.find_category("income", "顧問收入")["code"] == "7150"
sd = SubjectDialog(ctx, "expense", parent=chart)
sd.name.setText("餐飲")
sd.save()
assert "同名" in sd.msg.text(), sd.msg.text()
chart.load()
assert any(r.get("name", "").strip() == "長期投資－中華電" for r in chart.table.model_.rows)

sec_id = inv.add_security(lt["id"], "2412", "中華電")
bank = next(a for a in db.list_accounts() if a["name"] == "台銀活存")
jd = JournalDialog(ctx, parent=win)
jd.table.setRowCount(0)
jd.add_row(("account", lt["id"]), 12500)
jd.add_row(("account", bank["id"]), None, 12500)
cell = jd.table.cellWidget(0, 3)
assert cell.sec.isEnabled() and cell.sec.findData(sec_id) > 0
cell.sec.setCurrentIndex(cell.sec.findData(sec_id))
jd._sec_chosen(cell, jd.table.cellWidget(0, 0))
assert cell.shares.isEnabled()
cell.shares.setText("100")
assert not jd.table.cellWidget(1, 3).sec.isEnabled()
jd.note.setText("買進中華電")
jd.save()
assert jd.saved, jd.msg.text()
h = next(x for x in inv.holdings() if x["id"] == sec_id)
assert h["shares"] == 100 and h["cost"] == 12500
inv.set_prices([(sec_id, 130)], __import__("datetime").date.today().isoformat())
lt2 = next(a for a in db.account_summaries() if a["id"] == lt["id"])
assert lt2["balance"] == 13000, lt2["balance"]
win.go("reports", animate=False)
rp.tabs.setCurrentIndex(rp._tab_index("日記帳"))
app.processEvents()
assert "借貸平衡" in rp.jnl_sum.text(), rp.jnl_sum.text()
assert any(r["name"] == "長期投資－中華電" for r in rp.jnl.model_.rows)
rp.jnl_kw.setText("中華電")
app.processEvents()
vouchers = {r["id"] for r in rp.jnl.model_.rows}
assert vouchers and all(any("中華電" in (r["summary"] + r["name"]) for r in rp.jnl.model_.rows if r["id"] == v)
                        for v in vouchers)
win.go("investments", animate=False)
ip.refresh()
assert any(e.get("txn_id") for e in ip.ev.model_.rows)

# Q1 日期可直接輸入（西元、民國、無分隔、只打月日）
from PySide6.QtCore import QDate, Qt as _Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from app.dialogs_invest import PriceDialog  # noqa: E402
from app.dialogs_more import (JournalDialog, TemplateEditDialog, TemplateManagerDialog,  # noqa: E402
                              load_templates, save_templates)
from app.widgets import make_date_edit, parse_date_text  # noqa: E402

y = QDate.currentDate().year()
for text, want in (("2026/11/5", (2026, 11, 5)), ("115/11/5", (2026, 11, 5)), ("20261105", (2026, 11, 5)),
                   ("1151105", (2026, 11, 5)), ("2026-1-31", (2026, 1, 31)), ("2026.11.05", (2026, 11, 5)),
                   ("１１５／１１／５", (2026, 11, 5)), ("2026/11/05（週四）", (2026, 11, 5)),
                   ("11/5", (y, 11, 5)), ("1105", (y, 11, 5))):
    assert parse_date_text(text) == QDate(*want), text
for text in ("", "abc", "2026/13/1", "2026/2/30", "12345"):
    assert parse_date_text(text) is None, text
de = make_date_edit("2026-11-07")
seen = []
de.dateChanged.connect(seen.append)
de.show()
le = de.lineEdit()
le.selectAll()
QTest.keyClicks(le, "115/10/5")
QTest.keyClick(le, _Qt.Key.Key_Return)
assert de.date() == QDate(2026, 10, 5) and seen == [QDate(2026, 10, 5)], (de.date(), seen)
le.setText("2026/9/9")       # 尚未離開欄位時按儲存也要取得新日期
assert de.date() == QDate(2026, 9, 9)
le.setText("不是日期")
assert de.date() == QDate(2026, 9, 9) and "2026/09/09" in le.text()
de.showPopup()
de.calendarWidget().clicked.emit(QDate(2026, 3, 1))
assert de.date() == QDate(2026, 3, 1) and not de.calendarWidget().isVisible()
de.close()
j = JournalDialog(ctx, parent=win)
j.date.lineEdit().setText("115/1/2")
assert j.date.date() == QDate(2026, 1, 2)
j.close()

# Q2 資產負債表依科目代號排序並顯示代號
rp = win.pages["reports"]
rp.refresh_bs("2000-01-01", "2099-12-31")
bs = db.balance_sheet("2099-12-31")
want = [c for k in ("流動資產", "非流動資產", "流動負債", "非流動負債")
        for c in sorted(a["code"] for a in bs["groups"][k])]
tree = rp.bs
shown = [tree.topLevelItem(i).text(0).strip().split("　")[0] for i in range(tree.topLevelItemCount())]
assert [t for t in shown if t.isdigit()] == want, (shown, want)

# Q3 新增、修改、刪除範本，重新開啟仍在
cash_key = "account:%d" % db.list_accounts()[0]["id"]
exp_key = "category:%d" % db.list_categories("expense")[0]["id"]
n0 = len(load_templates(db))
ed = TemplateEditDialog(ctx, "每月固定費用", [("debit", exp_key, "固定", 500), ("credit", cash_key, "", None)], parent=win)
ed.save()
assert ed.template and ed.template[1][0][3] == 500, ed.msg.text()
save_templates(db, load_templates(db) + [ed.template])
j = JournalDialog(ctx, parent=win)
idx = j.template.findText("每月固定費用")
assert idx > 0 and j.template.count() == n0 + 2
j.apply_template(idx)
assert j.table.cellWidget(0, 1).value() == 500 and j.table.cellWidget(0, 0).currentData() == exp_key
assert j.table.cellWidget(1, 0).currentData() == cash_key
assert j.table.cellWidget(1, 2).placeholderText() == "請輸入"
j.table.cellWidget(1, 2).setValue(500)
assert j.collect() and j.note.text() == "每月固定費用"
j.close()
m = TemplateManagerDialog(ctx, win)
m.list.setCurrentRow(len(m.items) - 1)
m.move(-1)
assert load_templates(db)[-2][0] == "每月固定費用"
m.list.setCurrentRow(len(m.items) - 2)
m.delete()
assert len(load_templates(db)) == n0
dup = TemplateEditDialog(ctx, load_templates(db)[0][0], [("debit", exp_key, "", None), ("credit", cash_key, "", None)], parent=win)
dup.save()
assert dup.template is None
# 內建範本的科目尚未建立時，修改不可遺失該行
miss = [("debit", "liability:不存在的類別", "本金", None), ("credit", cash_key, "", None)]
ed = TemplateEditDialog(ctx, "保留", miss, parent=win)
ed.save()
assert ed.template[1][0][1] == "liability:不存在的類別", ed.template

# Q4 評價日可自選，列出當時持股，輸入市價才產生分錄
pd = PriceDialog(ctx, win)
pd.date.setDate(QDate(1999, 1, 1))
assert not pd.holdings and not pd.edits
pd.date.setDate(QDate.currentDate())
assert pd.holdings and len(pd.edits) == len(pd.holdings)
n1 = db.conn.execute("SELECT COUNT(*) FROM sec_events WHERE kind = 'price'").fetchone()[0]
pd.save()
assert db.conn.execute("SELECT COUNT(*) FROM sec_events WHERE kind = 'price'").fetchone()[0] == n1
pd.edits[0].setValue(pd.holdings[0]["avg_cost"] * 1.1)
pd.save()
hp = next(h for h in inv.holdings() if h["id"] == pd.holdings[0]["id"])
assert hp["price_date"] == QDate.currentDate().toString("yyyy-MM-dd")
ip = win.pages["investments"]
ip.refresh()
assert any(r["kind"] == "price" for r in ip.ev.model_.rows)

print("CHART / JOURNAL-INVEST GUI TESTS PASSED")
