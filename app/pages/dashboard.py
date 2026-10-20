from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QVBoxLayout, QWidget)

from ..animations import animate_progress
from ..charts import BarChart, DonutChart, LineChart
from ..database import TYPE_LABELS, last_n_months, month_end, month_start
from ..dialogs import AdjustDialog, TransactionDialog
from ..theme import TYPE_COLORS, C, fmt_date, fmt_date_long, fmt_money, fmt_month_short, icon
from ..widgets import Card, Column, DataTable, StatCard, button, section_title
from .base import Page


def greeting() -> str:
    h = dt.datetime.now().hour
    if h < 11:
        return "早安"
    if h < 14:
        return "午安"
    if h < 18:
        return "下午好"
    return "晚安"


def _clear_layout(lay) -> None:
    """清空版面；舊元件立即隱藏並移除，避免在刪除前與新內容重疊顯示。"""
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())
            item.layout().deleteLater()


class DashboardPage(Page):
    title = "總覽"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent=parent)
        b = self.body

        # 標題列
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        self.hello = QLabel()
        self.hello.setObjectName("PageTitle")
        self.today = QLabel()
        self.today.setObjectName("PageSubtitle")
        col.addWidget(self.hello)
        col.addWidget(self.today)
        head.addLayout(col)
        head.addStretch()
        for text, kind, ttype, ic in (("記支出", "Expense", "expense", "minus"),
                                       ("記收入", "Income", "income", "plus"),
                                       ("轉帳", "Transfer", "transfer", "transfer")):
            btn = button(text, kind, icon(ic, "#FFFFFF"))
            btn.setMinimumHeight(46)
            btn.clicked.connect(lambda _=False, t=ttype: self.new_txn(t))
            head.addWidget(btn)
        adj = button("更新市值", "Adjust", icon("refresh", "#FFFFFF"),
                     "股票、基金等資產市值變動時使用")
        adj.setMinimumHeight(46)
        adj.clicked.connect(self.adjust)
        head.addWidget(adj)
        b.addLayout(head)

        # 範例資料提示
        self.sample_banner = QFrame()
        self.sample_banner.setObjectName("SampleBanner")
        self.sample_banner.setStyleSheet(
            f"#SampleBanner {{ background: #FFF7E6; border: 1px solid #F5C66B; border-radius: 12px; }}"
            "#SampleBanner QLabel { background: transparent; }")
        bl = QHBoxLayout(self.sample_banner)
        bl.setContentsMargins(18, 12, 14, 12)
        bt = QLabel("目前顯示的是「範例資料」，僅供試用。熟悉操作後，按右邊按鈕即可清除並開始正式記帳。")
        bt.setWordWrap(True)
        bt.setStyleSheet("color:#8A5A00; font-weight:700;")
        clear_btn = button("清除範例資料，開始正式記帳", "Primary")
        clear_btn.clicked.connect(self.clear_sample)
        bl.addWidget(bt, 1)
        bl.addWidget(clear_btn)
        b.addWidget(self.sample_banner)

        # 統計卡片
        grid = QGridLayout()
        grid.setSpacing(16)
        self.c_net = StatCard("淨資產（業主權益）", C.primary)
        self.c_assets = StatCard("資產總計", C.income)
        self.c_liab = StatCard("負債總計", C.expense)
        self.c_inc = StatCard("本月收入", C.income)
        self.c_exp = StatCard("本月支出", C.expense)
        self.c_bal = StatCard("本月結餘", C.gold)
        for i, card in enumerate((self.c_net, self.c_assets, self.c_liab,
                                  self.c_inc, self.c_exp, self.c_bal)):
            grid.addWidget(card, i // 3, i % 3)
        b.addLayout(grid)

        # 財務比率
        ratio_card = Card(padding=14)
        rl = QHBoxLayout()
        rl.setSpacing(10)
        self.ratio_labels = {}
        for key, name, tip in (
                ("debt_ratio", "負債比率", "負債總計 ÷ 資產總計，愈低愈穩健"),
                ("current_ratio", "流動比率", "流動資產 ÷ 流動負債，> 2 倍表示短期償債能力佳"),
                ("emergency_months", "緊急預備金", "現金及約當現金可支應幾個月的平均支出"),
                ("savings_rate", "近 12 月儲蓄率", "（收入 − 支出）÷ 收入")):
            box = QVBoxLayout()
            t = QLabel(name)
            t.setObjectName("StatTitle")
            t.setToolTip(tip)
            v = QLabel("—")
            v.setStyleSheet("font-weight:700;")
            v.setToolTip(tip)
            box.addWidget(t, alignment=Qt.AlignmentFlag.AlignHCenter)
            box.addWidget(v, alignment=Qt.AlignmentFlag.AlignHCenter)
            rl.addLayout(box, 1)
            self.ratio_labels[key] = v
        ratio_card.lay.addWidget(section_title("財務健康指標"))
        ratio_card.lay.addLayout(rl)
        b.addWidget(ratio_card)

        # 提醒事項
        self.remind_card = Card(padding=16)
        self.remind_card.setStyleSheet(f"#Card {{ border-left: 5px solid {C.gold}; }}")
        self.remind_card.lay.addWidget(section_title("提醒事項"))
        self.remind_box = QVBoxLayout()
        self.remind_box.setSpacing(8)
        self.remind_card.lay.addLayout(self.remind_box)
        b.addWidget(self.remind_card)

        # 圖表
        row1 = QHBoxLayout()
        row1.setSpacing(16)
        alloc_card = Card()
        alloc_card.lay.addWidget(section_title("資產配置"))
        self.donut = DonutChart(height=280)
        alloc_card.lay.addWidget(self.donut)
        bar_card = Card()
        bar_card.lay.addWidget(section_title("近 12 個月收支"))
        self.bars = BarChart(height=280)
        bar_card.lay.addWidget(self.bars)
        row1.addWidget(alloc_card, 1)
        row1.addWidget(bar_card, 1)
        b.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(16)
        nw_card = Card()
        nw_card.lay.addWidget(section_title("淨資產趨勢（月底）"))
        self.line = LineChart(height=260)
        nw_card.lay.addWidget(self.line)
        self.budget_card = Card()
        self.budget_card.lay.addWidget(section_title("本月預算執行"))
        self.budget_box = QVBoxLayout()
        self.budget_box.setSpacing(10)
        self.budget_card.lay.addLayout(self.budget_box)
        self.budget_card.lay.addStretch()
        row2.addWidget(nw_card, 3)
        row2.addWidget(self.budget_card, 2)
        b.addLayout(row2)

        # 最近紀錄
        rec = Card()
        rh = QHBoxLayout()
        rh.addWidget(section_title("最近的紀錄"))
        rh.addStretch()
        more = button("查看全部 →", "Link")
        more.clicked.connect(lambda: self.ctx.navigate.emit("transactions", {}))
        rh.addWidget(more)
        rec.lay.addLayout(rh)
        self.recent = DataTable([
            Column("日期", lambda r: fmt_date(r["date"]), width=120),
            Column("類型", lambda r: TYPE_LABELS[r["type"]], align="center",
                   color=lambda r: TYPE_COLORS[r["type"]][0], width=100),
            Column("分類", lambda r: r["category_name"] or ("→ " + (r["to_account_name"] or "")
                                                            if r["type"] == "transfer" else "評價調整"),
                   width=150),
            Column("帳戶", lambda r: r["account_name"], width=170),
            Column("說明", lambda r: r["note"], stretch=True),
            Column("金額", lambda r: fmt_money(_signed(r), r["currency"], signed=r["type"] != "transfer"),
                   align="right", color=lambda r: TYPE_COLORS[r["type"]][0], width=160, bold=True),
        ], sortable=False)
        self.recent.setMinimumHeight(8 * 44 + 48)
        self.recent.rowActivated.connect(self.edit_txn)
        rec.lay.addWidget(self.recent)
        b.addWidget(rec)
        b.addStretch()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        db = self.db
        base = self.ctx.base
        self.sample_banner.setVisible(db.get_setting("sample_data") == "1")
        name = db.get_setting("owner_name")
        self.hello.setText(f"{greeting()}，{name}" if name else f"{greeting()}！")
        self.today.setText(fmt_date_long(dt.date.today()))

        nw = db.net_worth()
        self.c_net.set_money(nw["net"], base, "資產總計 − 負債總計",
                             C.primary if nw["net"] >= 0 else C.expense)
        self.c_assets.set_money(nw["assets"], base)
        self.c_liab.set_money(nw["liabilities"], base)
        ym = dt.date.today().strftime("%Y-%m")
        m = db.income_expense_totals(month_start(ym), month_end(ym))
        prev_ym = last_n_months(2)[0]
        pm = db.income_expense_totals(month_start(prev_ym), month_end(prev_ym))
        self.c_inc.set_money(m["income"], base, f"上月 {fmt_money(pm['income'], base)}", C.income)
        self.c_exp.set_money(m["expense"], base, f"上月 {fmt_money(pm['expense'], base)}", C.expense)
        rate = f"儲蓄率 {m['net'] / m['income']:.0%}" if m["income"] else ""
        self.c_bal.set_money(m["net"], base, rate, C.income if m["net"] >= 0 else C.expense)

        r = db.ratios(dt.date.today().isoformat())

        def pct(v):
            return "—" if v is None else f"{v:.1%}"
        self.ratio_labels["debt_ratio"].setText(pct(r["debt_ratio"]))
        self.ratio_labels["current_ratio"].setText(
            "無流動負債" if r["current_ratio"] is None else f"{r['current_ratio']:.2f} 倍")
        self.ratio_labels["emergency_months"].setText(
            "—" if r["emergency_months"] is None else f"{r['emergency_months']:.1f} 個月")
        self.ratio_labels["savings_rate"].setText(pct(r["savings_rate"]))

        alloc = db.allocation_by_category()
        self.donut.set_data(alloc)
        months = last_n_months(12)
        mt = db.monthly_totals(month_start(months[0]), month_end(months[-1]))
        labels = [fmt_month_short(k) for k in months]
        self.bars.set_data(labels, [("收入", [mt[k]["income"] for k in months], C.income),
                                    ("支出", [mt[k]["expense"] for k in months], C.expense)])
        series = db.net_worth_series(months)
        self.line.set_data(labels, [s["net"] for s in series])

        self._fill_budget(ym, base)
        self._fill_reminders(base)
        self.recent.set_rows(db.query_transactions(limit=8))

    def _fill_budget(self, ym: str, base: str) -> None:
        _clear_layout(self.budget_box)
        cats = [c for c in self.db.list_categories("expense") if c["budget"] > 0]
        self._bar_targets = []
        spent = {c["id"]: c["total"] for c in
                 self.db.category_totals(month_start(ym), month_end(ym), "expense")}
        if not cats:
            hint = QLabel("尚未設定預算。\n可到「設定 → 收支分類」為支出分類設定每月預算，"
                          "這裡就會顯示執行進度。")
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            self.budget_box.addWidget(hint)
            return
        for c in cats[:7]:
            used = spent.get(c["id"], 0.0)
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(4)
            top = QHBoxLayout()
            top.addWidget(QLabel(c["name"]))
            top.addStretch()
            amt = QLabel(f"{fmt_money(used, base)} / {fmt_money(c['budget'], base)}")
            amt.setObjectName("Hint")
            top.addWidget(amt)
            bar = QProgressBar()
            bar.setRange(0, 100)
            ratio = used / c["budget"]
            animate_progress(bar, min(100, int(ratio * 100)), self, 120 * len(self._bar_targets))
            self._bar_targets.append(c["id"])
            bar.setProperty("over", "true" if ratio > 1 else "false")
            bar.setFixedHeight(12)
            lay.addLayout(top)
            lay.addWidget(bar)
            self.budget_box.addWidget(w)

    def _fill_reminders(self, base: str) -> None:
        _clear_layout(self.remind_box)
        due = self.db.due_recurring()
        mats = self.db.upcoming_maturities(60)
        self.remind_card.setVisible(bool(due or mats))
        if due:
            row = QHBoxLayout()
            names = "、".join(dict.fromkeys(r["name"] for r, _ in due))
            lbl = QLabel(f"🔔　有 {len(due)} 筆定期交易已到期：{names}")
            lbl.setWordWrap(True)
            btn = button("確認入帳", "Primary")
            btn.clicked.connect(self.post_due)
            row.addWidget(lbl, 1)
            row.addWidget(btn)
            self.remind_box.addLayout(row)
        for a in mats[:5]:
            d = a["days_left"]
            when = "今天到期" if d == 0 else (f"已到期 {-d} 天" if d < 0 else f"剩 {d} 天")
            extra = f"，預估利息 {fmt_money(a['est_interest'], a['currency'])}" if a["est_interest"] else ""
            lbl = QLabel(f"📅　{a['name']} 將於 {fmt_date(a['maturity_date'])} 到期（{when}）"
                         f"，金額 {fmt_money(a['balance'], a['currency'])}{extra}")
            lbl.setWordWrap(True)
            if d <= 7:
                lbl.setStyleSheet(f"color:{C.expense}; font-weight:700;")
            self.remind_box.addWidget(lbl)

    def post_due(self) -> None:
        from ..dialogs_more import DueRecurringDialog
        due = self.db.due_recurring()
        if due:
            DueRecurringDialog(self.ctx, due, self.window()).exec()

    def clear_sample(self) -> None:
        import datetime as _d
        import os
        from ..widgets import ask
        if not ask(self, "確定要清除所有範例資料嗎？\n清除後會保留「現金」與「銀行存款」兩個空白帳戶，"
                         "您可以到「帳戶管理」修改或新增帳戶。", yes="清除並開始"):
            return
        self.db.backup_to(os.path.join(self.ctx.backup_dir,
                                       f"範例資料備份_{_d.datetime.now():%Y%m%d_%H%M%S}.db"))
        self.db.start_fresh()
        self.ctx.changed()
        self.ctx.toast.emit("已清除範例資料，可以開始正式記帳了！")

    def new_txn(self, ttype: str) -> None:
        TransactionDialog(self.ctx, ttype, parent=self.window()).exec()

    def edit_txn(self, row: dict) -> None:
        TransactionDialog(self.ctx, txn=self.db.get_transaction(row["id"]), parent=self.window()).exec()

    def adjust(self) -> None:
        AdjustDialog(self.ctx, parent=self.window()).exec()


def _signed(r: dict) -> float:
    if r["type"] == "expense":
        return -r["amount"]
    return r["amount"]
