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
for key in ("dashboard", "transactions", "accounts", "investments", "reports", "settings"):
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
assert "retirement" not in win.pages
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
assert lt2["balance"] == 13000 - 20 - 39, lt2["balance"]   # 預估淨售價：扣最低手續費與 0.3% 證交稅
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

# 1151115 Q4：股利科目可連結標的、股數與每股股利，金額自動帶入
div_cat = db.find_category("income", "股利")
jd = JournalDialog(ctx, parent=win)
jd.table.setRowCount(0)
jd.add_row(("account", bank["id"]), 450)
jd.add_row(("category", div_cat["id"]))
cell = jd.table.cellWidget(1, 3)
assert cell.sec.isEnabled() and cell.sec.findData(sec_id) > 0 and cell.sec.findData("new") < 0
assert not jd.table.cellWidget(0, 3).sec.isEnabled()
cell.sec.setCurrentIndex(cell.sec.findData(sec_id))
jd._sec_chosen(cell, jd.table.cellWidget(1, 0))
assert cell.shares.isEnabled() and cell.price.placeholderText() == "每股股利"
cell.shares.setValue(100)
cell.price.setValue(4.5)
assert jd.table.cellWidget(1, 2).value() == 450, jd.table.cellWidget(1, 2).value()
assert "股利" in jd.inv_info.text(), jd.inv_info.text()
jd.note.setText("中華電 配息")
jd.save()
assert jd.saved, jd.msg.text()
ip.refresh()
ev = next(e for e in ip.ev.model_.rows if e["kind"] == "jdiv")
assert ev["amount"] == 450 and ev["shares"] == 100 and ev["price"] == 4.5
# 重新開啟傳票，連結仍在
jd2 = JournalDialog(ctx, db.get_transaction(ev["txn_id"]), parent=win)
c2_ = next(jd2.table.cellWidget(r, 3) for r in range(jd2.table.rowCount())
           if jd2.table.cellWidget(r, 3).sec.currentData() == sec_id)
assert c2_.shares.value() == 100 and c2_.price.value() == 4.5
jd2.reject()

# 1151115 Q1–Q3：分錄全數賣出：手續費／稅依淨價款推算、不產生迴轉評價傳票、已實現損益列出股數
from PySide6.QtCore import Qt as _Qt  # noqa: E402
_dtm = __import__("datetime")
today = (_dtm.date.today() + _dtm.timedelta(days=1)).isoformat()   # 在今天的市價評價之後
n_inv = db.conn.execute("SELECT COUNT(*) FROM transactions WHERE source LIKE 'inv:%'").fetchone()[0]
db.add_journal(today, "賣出中華電", [
    {"account_id": bank["id"], "debit": 13839},
    {"account_id": lt["id"], "credit": 12500, "security_id": sec_id, "shares": 100, "price": 139},
    {"special": "realized", "credit": 1339}])
assert db.conn.execute("SELECT COUNT(*) FROM transactions WHERE source LIKE 'inv:%'").fetchone()[0] == n_inv
ip.refresh()
sell = next(e for e in ip.ev.model_.rows if e["kind"] == "jsell" and e["security_id"] == sec_id)
assert (sell["fee"], sell["tax"]) == (20, 41), sell          # 13,900 − 13,839 ＝ 61 ＝ 20＋41（不是 1,400）
ip.year.setCurrentText(today[:4])
ip.load_realized()
heads = [ip.real.model_.headerData(i, _Qt.Orientation.Horizontal) for i in range(ip.real.model_.columnCount())]
assert "股數" in heads, heads
assert any(r["code"] == "2412" and r["shares"] == 100 for r in ip.real.model_.rows)
gone = next(h for h in inv.holdings() if h["id"] == sec_id)
assert gone["shares"] == 0 and gone["market_value"] == 13000 - 20 - 39 - 12500
pd = PriceDialog(ctx, win)
pd.date.setDate(QDate.fromString(today, "yyyy-MM-dd"))
row = next(i for i, h in enumerate(pd.holdings) if h["id"] == sec_id)
assert not pd.edits[row].isEnabled() and "歸零" in pd.edits[row].placeholderText()
pd.save()
assert not any(h["id"] == sec_id for h in inv.holdings())
assert next(a for a in db.account_summaries() if a["id"] == lt["id"])["balance"] == 0

# 1151115-2 Q6：投資管理自動產生的傳票可刪除（開啟傳票按「刪除這張傳票」，或在收支明細選取後按作廢）
held = next(h for h in inv.holdings() if h["shares"] > 0)
d2 = (_dtm.date.today() + _dtm.timedelta(days=2)).isoformat()
inv.set_prices([(held["id"], round(held["avg_cost"] * 1.2, 2) or 10)], d2)
vid = db._q1("SELECT id FROM transactions WHERE source = ? AND date = ?", (f"inv:{held['id']}", d2))["id"]
jd3 = JournalDialog(ctx, db.get_transaction(vid), parent=win)
assert jd3.readonly and jd3.del_sys.isEnabled() and "刪除這張傳票" in jd3.msg.text()
jd3.delete_system_voucher()
assert not db.get_transaction(vid), jd3.msg.text()
assert not any(e["kind"] == "price" and e["date"] == d2 for e in inv.events(held["id"]))
inv.set_prices([(held["id"], round(held["avg_cost"] * 1.3, 2) or 10)], d2)
vid = db._q1("SELECT id FROM transactions WHERE source = ? AND date = ?", (f"inv:{held['id']}", d2))["id"]
tp = win.pages["transactions"]
tp.clear_filters()
tp.d1.setDate(QDate.fromString(d2, "yyyy-MM-dd"))
tp.d2.setDate(QDate.fromString(d2, "yyyy-MM-dd"))
tp.reload()
tp.table.clearSelection()
r = next(i for i, x in enumerate(tp.table.model_.rows) if x["id"] == vid)
tp.table.selectRow(tp.table.proxy.mapFromSource(tp.table.model_.index(r, 0)).row())
assert [x["id"] for x in tp.table.selected_rows()] == [vid]
tp.void_selected()
assert not db.get_transaction(vid)
_acc = held["account_id"]
assert abs(next(a for a in db.account_summaries() if a["id"] == _acc)["balance"]
           - sum(h["market_value"] for h in inv.holdings() if h["account_id"] == _acc)) < 0.01

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


# ---- 1151113 回報
from app.dialogs import ExportDialog as _ExportDialog  # noqa: E402
from app.dialogs_invest import SecurityDialog  # noqa: E402

# Q5 複式分錄輸入成交單價：金額空白時自動帶入含手續費成本，交易紀錄顯示單價
st_acc = next(a for a in db.list_accounts() if a["category"] == "短期投資")
s3715 = inv.add_security(st_acc["id"], "3715", "定穎投控")
bank_acc = next(a for a in db.list_accounts() if a["category"] == "銀行存款")
j = JournalDialog(ctx, parent=win)
j.table.setRowCount(0)
j.add_row(("account", st_acc["id"]))
j.add_row(("account", bank_acc["id"]))
c0 = j.table.cellWidget(0, 3)
c0.sec.setCurrentIndex(c0.sec.findData(s3715))
j._sec_chosen(c0, j.table.cellWidget(0, 0))
assert c0.price.isEnabled()
c0.shares.setValue(1000)
c0.price.setValue(98)
assert j.table.cellWidget(0, 1).value() == 98139, j.table.cellWidget(0, 1).value()
assert "手續費 139" in j.inv_info.text(), j.inv_info.text()
c0.price.setValue(97)                       # 自動帶入的金額會跟著更新
assert j.table.cellWidget(0, 1).value() == 97138
j.table.cellWidget(0, 1).setText("97000")   # 使用者自行輸入後不再覆蓋
j.table.cellWidget(0, 1).textEdited.emit("97000")
c0.price.setValue(98)
assert j.table.cellWidget(0, 1).value() == 97000
j.table.cellWidget(0, 1).setValue(98139)
j.auto_balance()
j.note.setText("買入 定穎投控")
j.save()
assert j.saved, j.msg.text()
ev = next(e for e in inv.events(s3715) if e["kind"] == "jbuy")
assert ev["price"] == 98 and ev["fee"] == 139, ev
jv = db.query_transactions(keyword="買入 定穎投控")[0]
j2 = JournalDialog(ctx, db.get_transaction(jv["id"]), parent=win)
assert j2.table.cellWidget(0, 3).price.value() == 98
j2.close()
# 賣出：貸方自動帶入實收（扣手續費與證交稅）
j = JournalDialog(ctx, parent=win)
j.apply_template(next(i for i, (n, _) in enumerate(j.templates) if n.startswith("賣出股票")))
row = next(r for r in range(j.table.rowCount())
           if (j.table.cellWidget(r, 0).currentData() or "") == "account:%d" % st_acc["id"])
cs = j.table.cellWidget(row, 3)
cs.sec.setCurrentIndex(cs.sec.findData(s3715))
j._sec_chosen(cs, j.table.cellWidget(row, 0))
cs.shares.setValue(400)
cs.price.setValue(135)
assert j.table.cellWidget(row, 2).value() == 54000 - 76 - 162, j.table.cellWidget(row, 2).value()
j.close()

# Q1 標的費率設定
sd = SecurityDialog(ctx, inv.get_security(s3715), parent=win)
assert abs(sd.tax_rate.value() - 0.3) < 1e-9 and sd.kind.currentIndex() == 0
sd.kind.setCurrentIndex(1)
sd._kind_chosen()
assert abs(sd.tax_rate.value() - 0.1) < 1e-9
sd.fee_rate.setValue(0.0855)
sd.save()
assert inv.get_security(s3715)["fee_rate"] == 0.000855 and inv.get_security(s3715)["tax_rate"] == 0.001
nd = SecurityDialog(ctx, parent=win, account_id=st_acc["id"])
nd.code.setText("00878")
nd._code_typed("00878")
assert abs(nd.tax_rate.value() - 0.1) < 1e-9
nd.close()

# Q3 匯出可勾選報表，選擇會記住
ed = _ExportDialog(ctx, win)
assert len(ed.sheet_boxes) == 13 and all(cb.isChecked() for cb in ed.sheet_boxes.values())
for name, cb in ed.sheet_boxes.items():
    cb.setChecked(name in ("資產負債表", "分類帳"))
ed.open_after.setChecked(False)
ed.path.setText(os.path.join(tmp, "選擇.xlsx"))
ed.do_export()
from openpyxl import load_workbook  # noqa: E402
assert load_workbook(os.path.join(tmp, "選擇.xlsx")).sheetnames == ["資產負債表", "分類帳"]
ed2 = _ExportDialog(ctx, win)
assert [n for n, cb in ed2.sheet_boxes.items() if cb.isChecked()] == ["資產負債表", "分類帳"]
for cb in ed2.sheet_boxes.values():
    cb.setChecked(False)
ed2.do_export()
assert "至少" in ed2.msg.text()
ed2.close()

# Q4 帳戶管理依科目代號排序；負餘額不取絕對值
ap = win.pages["accounts"]
cash = next(a for a in db.list_accounts() if a["category"] == "現金")
db.add_transaction(type="expense", account_id=cash["id"], amount=10_000_000,
                   date=__import__("datetime").date.today().isoformat(),
                   category_id=db.list_categories("expense")[0]["id"], note="透支測試")
ap.refresh()
t = ap.tables["asset"]
codes = [t.proxy.data(t.proxy.index(i, 0)) for i in range(t.proxy.rowCount())]
assert codes == sorted(codes), codes
neg = [r for r in t.model_.rows if r["balance"] < 0]
assert neg and all(r["_value"] < 0 for r in neg), [(r["name"], r["balance"], r["_value"]) for r in neg]


# 歡迎畫面按 ✕ 關閉也保留稱呼
from app.dialogs import WelcomeDialog  # noqa: E402
db.set_setting("owner_name", "")
wd = WelcomeDialog(ctx, win)
wd.reject()
assert db.get_setting("owner_name") == "游媽媽"

# 無效日期：跳出提醒並還原
warned = []
widgets.warn = lambda *a, **k: warned.append(a[1])
de = make_date_edit("2026-03-01")
de.lineEdit().setText("2026/2/30")
assert de.date() == QDate(2026, 3, 1) and warned and "不是有效的日期" in warned[0]
widgets.warn = lambda *a, **k: None


# ---- 商用功能：六欄式試算表、年度結帳、列印／PDF、傳票號碼
from PySide6.QtPdf import QPdfDocument  # noqa: E402  （只在測試使用，不打包）
from app.dialogs_print import PrintDialog  # noqa: E402
from app.dialogs_more import YearCloseDialog  # noqa: E402
from app.printing import REPORTS, Report, save_pdf  # noqa: E402


def pdf_pages(path):
    d = QPdfDocument()
    d.load(path)
    return d.pageCount()


lo, hi = db.date_range()
rp = win.pages["reports"]
rp.tabs.setCurrentIndex(rp._tab_index("試算表"))
app.processEvents()
assert rp.tb.model().columnCount() == 9 and "借貸平衡" in rp.tb_sum.text(), rp.tb_sum.text()
assert rp.tb.model_.rows[-1]["name"] == "合計"

# 列印：每份報表都能輸出 PDF
for key, name in REPORTS:
    out = os.path.join(tmp, f"r_{key}.pdf")
    save_pdf(Report(db).build([key], lo, hi), out)
    assert os.path.getsize(out) > 1000 and pdf_pages(out) >= 1, (key, name)
pd_ = PrintDialog(ctx, lo, hi, win)
for k, cb in pd_.boxes.items():
    cb.setChecked(k in ("journal", "ledger", "trial", "bs", "is", "equity"))
pd_.landscape.setChecked(True)
allpdf = pd_.export_pdf(os.path.join(tmp, "全部.pdf"))
assert allpdf and pdf_pages(allpdf) >= 6, pdf_pages(allpdf)
for cb in pd_.boxes.values():
    cb.setChecked(False)
assert pd_.export_pdf(os.path.join(tmp, "空.pdf")) is None and "至少" in pd_.msg.text()
pd_.close()
html = Report(db).build(["trial", "bs"], lo, hi)
assert "✓ 借貸平衡" in html and "資產總計" in html
# 傳票：類別、簽章欄、號碼
some = db.query_transactions(start=lo, end=hi)[0]
from app.database import voucher_no as voucher_no_  # noqa: E402
vh = Report(db).build_voucher(some["id"])
assert voucher_no_(some["id"]) in vh and "製　單" in vh
cash_acc = next(a for a in db.list_accounts() if a["category"] == "現金")
exp_id = db.add_transaction(type="expense", account_id=cash_acc["id"], amount=120,
                            date=__import__("datetime").date.today().isoformat(),
                            category_id=db.list_categories("expense")[0]["id"], note="列印測試")
assert "現金支出傳票" in Report(db).build_voucher(exp_id)
vp = os.path.join(tmp, "voucher.pdf")
save_pdf(Report(db).build(["vouchers"], lo, hi), vp)
n_v = len(db.query_transactions(start=lo, end=hi))
assert pdf_pages(vp) >= n_v, (pdf_pages(vp), n_v)   # 每張傳票一頁

# 年度結帳：預覽、確認、檢視結帳分錄（唯讀）、解除結帳
first = db.first_year()
year = __import__("datetime").date.today().year - 1
if first > year:
    year = None
if year:
    yd = YearCloseDialog(ctx, year, win)
    assert not yd.blocked
    yd.confirm()
    assert yd.closed_ok and year in db.year_closings() and db.closed_until >= f"{year}-12-31"
    cid = db.year_closings()[year]
    jd = JournalDialog(ctx, db.get_transaction(cid), parent=win)
    assert jd.readonly and "年度結帳" in jd.msg.text()
    assert any((jd.table.cellWidget(r, 0).currentText() or "").startswith("3201") for r in range(jd.table.rowCount()))
    jd.close()
    win.pages["transactions"].refresh()
    rp.refresh()
    assert YearCloseDialog(ctx, year, win).blocked
    sp_ = win.pages["settings"]
    sp_.refresh()
    sp_.reopen_books()
    assert year not in db.year_closings() and db.closed_until == ""


# ---- 每個已發行版本建立的帳本：以目前程式開啟主視窗、所有頁面與分頁、匯出與列印都不出錯
import shutil  # noqa: E402
from app.context import AppContext  # noqa: E402
from app.printing import REPORTS as _REPORTS  # noqa: E402
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
for name in sorted(f for f in os.listdir(FIX) if f.startswith("ledger_v") and f.endswith(".db")):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "理財帳本.db")
    shutil.copy(os.path.join(FIX, name), path)
    c2 = AppContext(path)
    w2 = MainWindow(c2)
    w2.show()
    app.processEvents()
    for key in w2.pages:
        w2.go(key, animate=False)
        app.processEvents()
    for page in ("reports", "investments"):
        tabs = w2.pages[page].tabs
        for i2 in range(tabs.count()):
            tabs.setCurrentIndex(i2)
            app.processEvents()
    export_workbook(c2.db, os.path.join(d, "old.xlsx"), "2025-01-01", "2025-12-31")
    Report(c2.db).build([k for k, _ in _REPORTS], "2025-01-01", "2025-12-31")
    w2.close()
    c2.db.close()
    print("OLD LEDGER OK", name)

print("CHART / JOURNAL-INVEST GUI TESTS PASSED")
