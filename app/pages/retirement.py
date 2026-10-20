from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QHeaderView,
                               QLabel, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..analytics import (DEFAULT_TARGETS, allocation_vs_target, retirement_defaults,
                         retirement_projection)
from ..charts import BarChart, LineChart
from ..theme import C, fmt_money, fmt_num
from ..widgets import AmountEdit, Card, Column, DataTable, StatCard, button, page_header, section_title
from .base import Page


class RetirementPage(Page):
    title = "退休規劃"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent=parent)
        b = self.body
        head, _ = page_header("退休規劃", "退休金流試算與資產配置檢視（僅供規劃參考）")
        b.addWidget(head)

        # ---------------------------------------------------------- 參數
        pc = Card()
        pc.lay.addWidget(section_title("試算條件"))
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(10)
        self.age = QSpinBox()
        self.age.setRange(40, 110)
        self.age.setSuffix(" 歲")
        self.life = QSpinBox()
        self.life.setRange(60, 120)
        self.life.setSuffix(" 歲")
        self.assets = AmountEdit()
        self.assets.setObjectName("")
        self.exclude_re = QCheckBox("不含不動產（自住房屋通常不會拿來支付生活費）")
        self.expense = AmountEdit()
        self.expense.setObjectName("")
        self.income = AmountEdit()
        self.income.setObjectName("")
        self.ret = QDoubleSpinBox()
        self.ret.setRange(-5, 15)
        self.ret.setDecimals(1)
        self.ret.setSuffix(" %")
        self.infl = QDoubleSpinBox()
        self.infl.setRange(0, 10)
        self.infl.setDecimals(1)
        self.infl.setSingleStep(0.1)
        self.infl.setSuffix(" %")
        self.pg = QDoubleSpinBox()
        self.pg.setRange(-5, 10)
        self.pg.setDecimals(1)
        self.pg.setSingleStep(0.1)
        self.pg.setSuffix(" %")
        items = [("目前年齡", self.age), ("預估壽命（規劃到）", self.life),
                 ("可運用資產", self.assets), ("", self.exclude_re),
                 ("每月生活支出", self.expense), ("每月退休金／年金收入", self.income),
                 ("預估年投資報酬率", self.ret), ("預估年通膨率（生活支出年增）", self.infl),
                 ("退休金每年調幅", self.pg)]
        for i, (label, w) in enumerate(items):
            r, c = divmod(i, 2)
            g.addWidget(QLabel(label), r, c * 2)
            g.addWidget(w, r, c * 2 + 1)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        pc.lay.addLayout(g)
        row = QHBoxLayout()
        self.src = QLabel()
        self.src.setObjectName("Hint")
        self.src.setWordWrap(True)
        reset = button("依帳本資料重新帶入", "Link")
        reset.clicked.connect(lambda: self.load_defaults(force=True))
        calc = button("試算", "Primary")
        calc.clicked.connect(self.calculate)
        row.addWidget(self.src, 1)
        row.addWidget(reset)
        row.addWidget(calc)
        pc.lay.addLayout(row)
        b.addWidget(pc)

        # ---------------------------------------------------------- 結果
        cards = QHBoxLayout()
        cards.setSpacing(16)
        self.r_age = StatCard("資產可支應至", C.primary)
        self.r_safe = StatCard("每月可安心支用", C.income)
        self.r_gap = StatCard("每月收支缺口", C.expense)
        self.r_final = StatCard("規劃期末剩餘資產", C.gold)
        for c in (self.r_age, self.r_safe, self.r_gap, self.r_final):
            cards.addWidget(c)
        b.addLayout(cards)
        chart_row = QVBoxLayout()
        chart_row.setSpacing(16)
        cc = Card()
        cc.lay.addWidget(section_title("資產變化預估"))
        self.chart = LineChart(height=300)
        cc.lay.addWidget(self.chart)
        tc = Card()
        tc.lay.addWidget(section_title("逐年明細"))
        self.table = DataTable([
            Column("年齡", lambda r: r["age"], align="center", width=60),
            Column("年初資產", lambda r: fmt_num(r["start"], ctx.base), align="right", width=150),
            Column("投資收益", lambda r: fmt_num(r["return"], ctx.base), align="right", width=100),
            Column("退休金收入", lambda r: fmt_num(r["income"], ctx.base), align="right", width=110),
            Column("生活支出", lambda r: fmt_num(r["expense"], ctx.base), align="right", width=110),
            Column("年底資產", lambda r: fmt_num(r["end"], ctx.base), align="right", width=120, bold=True,
                   color=lambda r: C.expense if r["end"] < 0 else None),
            Column("今日幣值", lambda r: fmt_num(r["real_end"], ctx.base), align="right", stretch=True,
                   color=lambda r: C.muted),
        ], sortable=False)
        self.table.setMinimumHeight(300)
        tc.lay.addWidget(self.table)
        chart_row.addWidget(cc)
        chart_row.addWidget(tc)
        b.addLayout(chart_row)
        self.real_note = QLabel()
        self.real_note.setWordWrap(True)
        self.real_note.setStyleSheet(f"color:{C.adjust}; font-weight:700;")
        b.addWidget(self.real_note)
        note = QLabel("試算假設：投資報酬率與通膨率每年固定；實際情況會隨市場與政策變動，建議每年檢視一次。")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        b.addWidget(note)

        # ---------------------------------------------------------- 資產配置
        ac = Card()
        ah = QHBoxLayout()
        ah.addWidget(section_title("資產配置：目標與實際"))
        ah.addStretch()
        save_t = button("儲存目標比例", "Primary")
        save_t.clicked.connect(self.save_targets)
        reset_t = button("恢復建議比例", "Link")
        reset_t.clicked.connect(self.reset_targets)
        ah.addWidget(reset_t)
        ah.addWidget(save_t)
        ac.lay.addLayout(ah)
        arow = QHBoxLayout()
        arow.setSpacing(16)
        self.alloc = QTableWidget(0, 6)
        self.alloc.setHorizontalHeaderLabels(["資產類別", "目前金額", "實際比例", "目標比例", "差距", "再平衡建議"])
        self.alloc.verticalHeader().setVisible(False)
        self.alloc.verticalHeader().setDefaultSectionSize(44)
        self.alloc.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, w in ((1, 115), (2, 80), (3, 90), (4, 75), (5, 150)):
            self.alloc.setColumnWidth(i, w)
        self.alloc.setMinimumHeight(360)
        self.alloc_chart = BarChart(height=360)
        arow.addWidget(self.alloc, 3)
        arow.addWidget(self.alloc_chart, 2)
        ac.lay.addLayout(arow)
        self.alloc_note = QLabel()
        self.alloc_note.setObjectName("Hint")
        ac.lay.addWidget(self.alloc_note)
        b.addWidget(ac)
        b.addStretch()

        self.exclude_re.toggled.connect(self._re_toggled)
        self._loaded = False

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.load_defaults(force=not self._loaded)
        self._loaded = True
        self.calculate()
        self.load_alloc()

    def load_defaults(self, force: bool = False) -> None:
        p = retirement_defaults(self.db)
        self.params = p
        if force:
            self.age.setValue(p["age"])
            self.life.setValue(p["life"])
            self.exclude_re.blockSignals(True)
            self.exclude_re.setChecked(p["exclude_real_estate"])
            self.exclude_re.blockSignals(False)
            self._re_toggled()
            self.expense.setValue(p["monthly_expense"])
            self.income.setValue(p["monthly_income"])
            self.ret.setValue(p["return_rate"])
            self.infl.setValue(p["inflation"])
            self.pg.setValue(p["pension_growth"])
        base = self.ctx.base
        self.src.setText(f"預設值來自帳本：淨資產 {fmt_money(p['net_worth'], base)}、近 12 個月平均支出、"
                         "近 12 個月退休金／年金收入平均。可自行修改後按「試算」。")
        if force:
            self.calculate()

    def _re_toggled(self) -> None:
        p = getattr(self, "params", None) or retirement_defaults(self.db)
        v = p["net_worth"] - (p["real_estate"] if self.exclude_re.isChecked() else 0)
        self.assets.setValue(round(v))

    def calculate(self) -> None:
        base = self.ctx.base
        res = retirement_projection(self.age.value(), self.life.value(), self.assets.value() or 0,
                                    self.expense.value() or 0, self.income.value() or 0,
                                    self.ret.value(), self.infl.value(), self.pg.value())
        self.db.set_json("retire_params", {"life": self.life.value(), "return_rate": self.ret.value(),
                                           "inflation": self.infl.value(),
                                           "pension_growth": self.pg.value(),
                                           "exclude_real_estate": self.exclude_re.isChecked()})
        if res["depleted_age"]:
            self.r_age.set(f"{res['depleted_age']} 歲", "資產將在此年齡用完，建議調整支出或配置", C.expense)
        else:
            self.r_age.set(f"{self.life.value()} 歲以上", "規劃期間內資產足夠支應", C.income)
        self.r_safe.set_money(res["sustainable_monthly"], base, "資產可支用到預估壽命的每月上限", C.income)
        gap = res["monthly_gap"]
        if gap > 0:
            self.r_gap.title.setText("每月收支缺口")
            self.r_gap.set_accent(C.expense)
            self.r_gap.set_money(gap, base, "每月支出超過退休金的部分（需由資產支應）", C.expense)
        else:
            self.r_gap.title.setText("每月收支結餘")
            self.r_gap.set_accent(C.income)
            self.r_gap.set_money(-gap, base, "退休金足以支付生活費，每月還有結餘", C.income)
        self.r_final.set_money(res["final"], base,
                               f"{self.life.value()} 歲時｜約等於今日的 {fmt_money(res['final_real'], base)}",
                               C.gold)
        self.real_note.setText(
            f"已考慮通膨：生活支出每年增加 {self.infl.value():.1f}%，退休金每年調整 {self.pg.value():+.1f}%；"
            f"扣除通膨後的實質報酬率約 {res['real_return']:+.2%}。「今日幣值」為換算成現在購買力的金額。")
        rows = res["rows"]
        self.table.set_rows(rows)
        self.chart.set_data([str(r["age"]) for r in rows], [r["end"] for r in rows],
                            C.primary if not res["depleted_age"] else C.expense, x_title="年齡")

    def load_alloc(self) -> None:
        rows = allocation_vs_target(self.db)
        base = self.ctx.base
        self.alloc.setRowCount(len(rows))
        self.target_spins = {}
        for r, row in enumerate(rows):
            vals = [row["category"], fmt_num(row["amount"], base), f"{row['actual_pct']:.1f}%"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if c:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.alloc.setItem(r, c, it)
            sp = QDoubleSpinBox()
            sp.setRange(0, 100)
            sp.setDecimals(0)
            sp.setSuffix(" %")
            sp.setValue(row["target_pct"])
            self.alloc.setCellWidget(r, 3, sp)
            self.target_spins[row["category"]] = sp
            d = QTableWidgetItem(f"{row['diff_pct']:+.1f}%")
            d.setFlags(Qt.ItemFlag.ItemIsEnabled)
            d.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            d.setForeground(Qt.GlobalColor.darkRed if abs(row["diff_pct"]) > 5 else Qt.GlobalColor.darkGray)
            self.alloc.setItem(r, 4, d)
            rb = row["rebalance"]
            text = "—" if abs(rb) < 1000 else (f"增加 {fmt_money(rb, base)}" if rb > 0 else f"減少 {fmt_money(-rb, base)}")
            x = QTableWidgetItem(text)
            x.setFlags(Qt.ItemFlag.ItemIsEnabled)
            x.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.alloc.setItem(r, 5, x)
        total_t = sum(r["target_pct"] for r in rows)
        self.alloc_note.setText(f"目標比例合計 {total_t:.0f}%（建議合計為 100%）。差距超過 ±5% 時可考慮調整配置。"
                                "比例以資產類別計算（帳戶管理中的「類別」）。")
        self.alloc_chart.set_data([r["category"] for r in rows],
                                  [("實際 %", [r["actual_pct"] for r in rows], C.primary),
                                   ("目標 %", [r["target_pct"] for r in rows], C.gold)], unit="單位：%",
                                  x_title="")

    def save_targets(self) -> None:
        targets = {k: sp.value() for k, sp in self.target_spins.items() if sp.value() > 0}
        self.db.set_json("allocation_targets", targets)
        self.ctx.toast.emit(f"已儲存目標配置（合計 {sum(targets.values()):.0f}%）")
        self.load_alloc()

    def reset_targets(self) -> None:
        self.db.set_json("allocation_targets", DEFAULT_TARGETS)
        self.load_alloc()

