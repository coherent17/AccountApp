from __future__ import annotations

import datetime as dt
import os

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QRadioButton,
                               QVBoxLayout)

from ..context import APP_NAME, APP_VERSION
from ..database import CURRENCIES, TAX_TAGS
from ..dialogs import open_path
from ..theme import C, FONT_SCALES, fmt_date, fmt_money, icon
from ..widgets import (AmountEdit, Column, DataTable, ask, button, error, info, iso,
                       make_date_edit, page_header)
from .base import Page


class SettingsPage(Page):
    title = "設定"

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent=parent)
        b = self.body
        head, _ = page_header("設定", "個人資料、收支分類與預算、結帳、備份與還原")
        b.addWidget(head)

        # ---------------------------------------------------------- 個人設定
        g = QGroupBox("個人設定")
        gl = QGridLayout(g)
        gl.setHorizontalSpacing(14)
        gl.setVerticalSpacing(12)
        self.name = QLineEdit()
        self.name.setPlaceholderText("顯示在首頁問候與報表「編製者」欄")
        save_name = button("儲存", "Primary")
        save_name.clicked.connect(self.save_name)
        gl.addWidget(QLabel("稱呼"), 0, 0)
        gl.addWidget(self.name, 0, 1)
        gl.addWidget(save_name, 0, 2)
        gl.addWidget(QLabel("文字大小"), 1, 0)
        fr = QHBoxLayout()
        self.font_group = QButtonGroup(self)
        self.font_buttons = {}
        for key, (label, _) in FONT_SCALES.items():
            rb = QRadioButton(label)
            self.font_group.addButton(rb)
            self.font_buttons[key] = rb
            rb.toggled.connect(lambda on, k=key: on and self.set_font(k))
            fr.addWidget(rb)
        fr.addStretch()
        gl.addLayout(fr, 1, 1, 1, 2)
        gl.addWidget(QLabel("動畫效果"), 4, 0)
        self.anim_switch = QCheckBox("開啟動畫效果（按鈕漣漪、頁面轉場、數字滾動、圖表動畫）")
        self.anim_switch.toggled.connect(self.set_animations)
        gl.addWidget(self.anim_switch, 4, 1, 1, 2)
        anim_hint = QLabel("若電腦較舊、覺得畫面不夠流暢，或偏好簡潔畫面，可以關閉。")
        anim_hint.setObjectName("Hint")
        gl.addWidget(anim_hint, 5, 1, 1, 2)
        gl.addWidget(QLabel("本位幣"), 2, 0)
        self.base = QComboBox()
        for code, (n, _) in CURRENCIES.items():
            self.base.addItem(f"{n}（{code}）", code)
        self.base.activated.connect(self.set_base)
        gl.addWidget(self.base, 2, 1)
        base_hint = QLabel("所有報表與資產合計皆以本位幣表示；外幣帳戶依帳戶中設定的匯率換算。")
        base_hint.setObjectName("Hint")
        gl.addWidget(base_hint, 3, 1, 1, 2)
        gl.setColumnStretch(1, 1)
        b.addWidget(g)

        # ---------------------------------------------------------- 分類
        g = QGroupBox("收支分類（會計科目）與每月預算")
        outer = QVBoxLayout(g)
        outer.setSpacing(12)
        ct = QHBoxLayout()
        ch = QLabel("收入、費用科目在這裡管理；資產、負債科目請到「帳戶管理」。完整科目與代號請看會計科目表。")
        ch.setObjectName("Hint")
        ch.setWordWrap(True)
        ct.addWidget(ch, 1)
        chart_btn = button("會計科目表", "Primary", icon("list", "#FFFFFF"))
        chart_btn.clicked.connect(self.open_chart)
        ct.addWidget(chart_btn)
        outer.addLayout(ct)
        gl = QHBoxLayout()
        gl.setSpacing(16)
        outer.addLayout(gl)
        self.cat_tables = {}
        for kind, title in (("expense", "支出分類"), ("income", "收入分類")):
            col = QVBoxLayout()
            lbl = QLabel(title)
            lbl.setStyleSheet(f"font-weight:700; color:{C.expense if kind == 'expense' else C.income};")
            col.addWidget(lbl)
            cols = [Column("代號", lambda r: r["code"], align="center", width=72, color=lambda r: C.muted),
                    Column("分類名稱", lambda r: r["name"], stretch=True,
                           color=lambda r: C.faint if r["archived"] else None),
                    Column("狀態", lambda r: "已隱藏" if r["archived"] else "使用中", align="center",
                           width=90, color=lambda r: C.faint if r["archived"] else C.income)]
            if kind == "expense":
                cols.insert(2, Column("每月預算", lambda r: fmt_money(r["budget"], ctx.base)
                                      if r["budget"] else "—", align="right", width=130))
            cols.insert(len(cols) - 1, Column("稅務歸類", lambda r: TAX_TAGS.get(r["tax_tag"], "")
                                              if r["tax_tag"] else "—", stretch=True, elide=True,
                                              color=lambda r: C.adjust if r["tax_tag"] else C.faint))
            t = DataTable(cols, sortable=False)
            t.setMinimumHeight(420)
            t.rowActivated.connect(lambda r, k=kind: self.rename(k))
            col.addWidget(t, 1)
            bar = QGridLayout()
            bar.setSpacing(6)
            actions = [("新增", "plus", lambda _=False, k=kind: self.add_cat(k)),
                       ("修改", "edit", lambda _=False, k=kind: self.rename(k)),
                       ("上移", "up", lambda _=False, k=kind: self.move(k, -1)),
                       ("下移", "down", lambda _=False, k=kind: self.move(k, 1)),
                       ("隱藏／顯示", "eye", lambda _=False, k=kind: self.toggle(k)),
                       ("刪除", "trash", lambda _=False, k=kind: self.delete_cat(k))]
            if kind == "expense":
                actions.insert(2, ("設定預算", "wallet", lambda _=False: self.set_budget()))
            actions.insert(2, ("稅務歸類", "list", lambda _=False, k=kind: self.set_tax_tag(k)))
            for i, (text, ic, fn) in enumerate(actions):
                btn = button(text, "Danger" if text == "刪除" else None,
                             icon(ic, C.expense if text == "刪除" else C.text))
                btn.clicked.connect(fn)
                bar.addWidget(btn, i // 4, i % 4)
            col.addLayout(bar)
            gl.addLayout(col, 1)
            self.cat_tables[kind] = t
        b.addWidget(g)

        # ---------------------------------------------------------- 結帳
        g = QGroupBox("結帳（關帳）")
        gl = QGridLayout(g)
        gl.setHorizontalSpacing(14)
        gl.setVerticalSpacing(10)
        desc = QLabel("對帳完成後可執行結帳：結帳日（含）以前的紀錄將被鎖定，無法新增、修改或刪除，"
                      "以確保已核對的帳務不會被誤改。年度結帳另會把該年度損益結轉「本期損益（累積淨值）」，"
                      "並在日記簿留下結帳分錄。如需更正，可隨時解除結帳（年度結帳分錄會一併作廢）。")
        desc.setObjectName("Hint")
        desc.setWordWrap(True)
        self.closed_label = QLabel()
        self.closed_label.setStyleSheet("font-weight:700;")
        self.close_date = make_date_edit()
        do_close = button("執行結帳", "Primary")
        do_close.clicked.connect(self.close_books)
        reopen = button("解除結帳", "Danger")
        reopen.clicked.connect(self.reopen_books)
        gl.addWidget(desc, 0, 0, 1, 4)
        gl.addWidget(QLabel("目前狀態"), 1, 0)
        gl.addWidget(self.closed_label, 1, 1, 1, 3)
        gl.addWidget(QLabel("結帳至"), 2, 0)
        gl.addWidget(self.close_date, 2, 1)
        gl.addWidget(do_close, 2, 2)
        gl.addWidget(reopen, 2, 3)
        self.close_year = QComboBox()
        year_btn = button("年度結帳…", "Primary")
        year_btn.clicked.connect(self.close_year_dialog)
        gl.addWidget(QLabel("年度結帳"), 3, 0)
        gl.addWidget(self.close_year, 3, 1)
        gl.addWidget(year_btn, 3, 2)
        gl.setColumnStretch(1, 1)
        b.addWidget(g)

        # ---------------------------------------------------------- 網路連線
        g = QGroupBox("網路")
        gl = QGridLayout(g)
        gl.setHorizontalSpacing(14)
        gl.setVerticalSpacing(10)
        self.online = QCheckBox("允許連線更新匯率與股價（選用，預設關閉）")
        self.online.toggled.connect(self.set_online)
        gl.addWidget(QLabel("網路更新"), 1, 0)
        gl.addWidget(self.online, 1, 1, 1, 3)
        oh = QLabel("開啟後，「市價評價」與「更新匯率」會多一個「從網路取得」按鈕。只會下載公開資料、不會上傳任何個人資料；"
                    "股價來源為臺灣證券交易所與櫃買中心官方開放資料，匯率為 ExchangeRate-API 國際參考匯率。"
                    "沒有網路時仍可手動輸入，所有功能都不受影響。關閉時不會連網取得匯率與股價。")
        oh.setObjectName("Hint")
        oh.setWordWrap(True)
        gl.addWidget(oh, 2, 1, 1, 3)
        gl.addWidget(QLabel("版本更新"), 3, 0)
        self.update_auto = QCheckBox("開啟程式時自動檢查是否有新版本（一天最多一次）")
        self.update_auto.toggled.connect(self.set_update_auto)
        gl.addWidget(self.update_auto, 3, 1, 1, 2)
        chk = button("立即檢查新版本", icon=icon("refresh"))
        chk.clicked.connect(self.check_update)
        gl.addWidget(chk, 3, 3)
        uh = QLabel(f"目前版本 {APP_VERSION}。檢查時只會向 GitHub 查詢最新版本號碼；有新版本時會顯示更新內容，"
                    "按「立即更新」就會自動下載、換成新版並重新開啟，帳本資料不會變動（更新前會先備份）。")
        uh.setObjectName("Hint")
        uh.setWordWrap(True)
        gl.addWidget(uh, 4, 1, 1, 3)
        gl.setColumnStretch(1, 1)
        b.addWidget(g)

        # ---------------------------------------------------------- 資料
        g = QGroupBox("資料管理與備份")
        gl = QGridLayout(g)
        gl.setHorizontalSpacing(14)
        gl.setVerticalSpacing(10)
        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.path_label.setObjectName("Hint")
        open_folder = button("開啟資料夾", icon=icon("folder"))
        open_folder.clicked.connect(lambda: open_path(self.ctx.folder))
        gl.addWidget(QLabel("資料位置"), 0, 0)
        gl.addWidget(self.path_label, 0, 1)
        gl.addWidget(open_folder, 0, 2)
        auto = QLabel("每天第一次開啟程式時會自動備份，保留最近 30 份於「自動備份」資料夾。")
        auto.setObjectName("Hint")
        gl.addWidget(auto, 1, 1, 1, 2)
        row = QHBoxLayout()
        for text, kind, ic, fn in (("立即備份到…", "Primary", "save", self.backup),
                                   ("從備份檔還原…", None, "restore", self.restore),
                                   ("開啟自動備份資料夾", None, "folder",
                                    lambda: open_path(self.ctx.backup_dir)),
                                   ("清除所有資料…", "Danger", "trash", self.reset)):
            btn = button(text, kind, icon(ic, "#FFFFFF" if kind == "Primary" else
                                          (C.expense if kind == "Danger" else C.text)))
            btn.clicked.connect(fn)
            row.addWidget(btn)
        row.addStretch()
        gl.addLayout(row, 2, 0, 1, 3)
        gl.setColumnStretch(1, 1)
        b.addWidget(g)

        # ---------------------------------------------------------- 關於
        g = QGroupBox("關於")
        gl = QVBoxLayout(g)
        about = QLabel(f"{APP_NAME}　版本 {APP_VERSION}\n"
                       "個人資產管理與記帳工具：日記帳、分類帳、資產負債表、收支損益表、試算表及 Excel 匯出。\n"
                       "所有資料僅儲存於本機電腦，不會上傳至網路。")
        about.setObjectName("Hint")
        gl.addWidget(about)
        b.addWidget(g)
        b.addStretch()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        db = self.db
        self.name.setText(db.get_setting("owner_name"))
        scale = db.get_setting("font_scale", "large")
        rb = self.font_buttons.get(scale)
        if rb and not rb.isChecked():
            rb.blockSignals(True)
            rb.setChecked(True)
            rb.blockSignals(False)
        self.base.setCurrentIndex(max(0, self.base.findData(db.base_currency)))
        self.online.blockSignals(True)
        self.online.setChecked(db.get_setting("online_updates", "0") == "1")
        self.online.blockSignals(False)
        self.update_auto.blockSignals(True)
        self.update_auto.setChecked(db.get_setting("update_auto", "1") == "1")
        self.update_auto.blockSignals(False)
        self.anim_switch.blockSignals(True)
        self.anim_switch.setChecked(db.get_setting("animations", "1") == "1")
        self.anim_switch.blockSignals(False)
        for kind, t in self.cat_tables.items():
            t.set_rows(db.list_categories(kind, include_archived=True))
        c = db.closed_until
        done = db.year_closings()
        self.closed_label.setText((f"已結帳至 {fmt_date(c)}" if c else "尚未結帳")
                                  + (f"　｜　已辦理年度結帳：{'、'.join(map(str, sorted(done)))} 年" if done else ""))
        self.close_year.clear()
        first = db.first_year() or dt.date.today().year
        for y in range(dt.date.today().year - 1, first - 1, -1):
            self.close_year.addItem(f"{y} 年（民國 {y - 1911} 年）" + ("　✓ 已結帳" if y in done else ""), y)
        self.closed_label.setStyleSheet(f"font-weight:700; color:{C.adjust if c else C.muted};")
        self.path_label.setText(self.ctx.db_path)

    def save_name(self) -> None:
        self.db.set_setting("owner_name", self.name.text().strip())
        self.ctx.settingsChanged.emit()
        info(self, "已儲存。")

    def set_online(self, on: bool) -> None:
        self.db.set_setting("online_updates", "1" if on else "0")
        self.ctx.toast.emit("已開啟網路更新（選用）" if on else "已關閉網路更新，程式不會連線")

    def set_update_auto(self, on: bool) -> None:
        self.db.set_setting("update_auto", "1" if on else "0")
        self.ctx.toast.emit("開啟程式時會自動檢查新版本" if on else "已關閉自動檢查新版本")

    def check_update(self) -> None:
        from ..dialogs_update import check_for_updates
        check_for_updates(self.ctx, self.window())

    def set_tax_tag(self, kind: str) -> None:
        r = self._sel(kind)
        if not r:
            return
        from ..database import EXPENSE_TAX_TAGS, INCOME_TAX_TAGS
        from ..dialogs import BaseDialog
        dlg = BaseDialog("稅務歸類", self.window(), width=460)
        dlg.root.addWidget(QLabel(f"「{r['name']}」在報稅彙總中歸類為："))
        cb = QComboBox()
        for tag in (INCOME_TAX_TAGS if kind == "income" else EXPENSE_TAX_TAGS):
            cb.addItem(TAX_TAGS[tag], tag)
        cb.setCurrentIndex(max(0, cb.findData(r["tax_tag"])))
        dlg.root.addWidget(cb)
        bar = QHBoxLayout()
        bar.addStretch()
        c = button("取消")
        c.clicked.connect(dlg.reject)
        ok = button("儲存", "Primary")
        ok.clicked.connect(dlg.accept)
        bar.addWidget(c)
        bar.addWidget(ok)
        dlg.root.addLayout(bar)
        if dlg.exec():
            self.db.update_category(r["id"], tax_tag=cb.currentData())
            self.ctx.changed()

    def set_animations(self, on: bool) -> None:
        from .. import animations
        self.db.set_setting("animations", "1" if on else "0")
        animations.set_enabled(on)
        self.ctx.toast.emit("已開啟動畫效果" if on else "已關閉動畫效果")

    def set_font(self, key: str) -> None:
        self.db.set_setting("font_scale", key)
        self.ctx.settingsChanged.emit()

    def set_base(self) -> None:
        code = self.base.currentData()
        if code == self.db.base_currency:
            return
        if not ask(self, f"確定要將本位幣改為「{CURRENCIES[code][0]}」嗎？\n"
                         "改變後請到「帳戶管理」確認各外幣帳戶的匯率是否正確。"):
            self.refresh()
            return
        self.db.set_setting("base_currency", code)
        for a in self.db.list_accounts(include_archived=True):
            if a["currency"] == code:
                self.db.update_account(a["id"], rate=1.0)
        self.ctx.changed()
        info(self, "本位幣已變更，部分畫面將在重新開啟程式後完整更新。")

    # ------------------------------------------------------------------ 分類
    def _sel(self, kind: str) -> dict | None:
        r = self.cat_tables[kind].current_row()
        if not r:
            info(self, "請先點選一個分類。")
        return r

    def _ask_text(self, title: str, label: str, text: str = "") -> str | None:
        dlg = QInputDialog(self)
        dlg.setWindowTitle(title)
        dlg.setLabelText(label)
        dlg.setTextValue(text)
        dlg.setOkButtonText("確定")
        dlg.setCancelButtonText("取消")
        if dlg.exec():
            v = dlg.textValue().strip()
            return v or None
        return None

    def add_cat(self, kind: str) -> None:
        from ..dialogs_chart import SubjectDialog
        SubjectDialog(self.ctx, kind, parent=self.window()).exec()

    def rename(self, kind: str) -> None:
        r = self._sel(kind)
        if not r:
            return
        from ..dialogs_chart import SubjectDialog
        SubjectDialog(self.ctx, category=self.db.get_category(r["id"]), parent=self.window()).exec()

    def open_chart(self) -> None:
        from ..dialogs_chart import ChartOfAccountsDialog
        ChartOfAccountsDialog(self.ctx, self.window()).exec()

    def set_budget(self) -> None:
        r = self._sel("expense")
        if not r:
            return
        from ..dialogs import BaseDialog
        dlg = BaseDialog("設定每月預算", self.window(), width=420)
        dlg.root.addWidget(QLabel(f"「{r['name']}」每月預算（輸入 0 表示不設定）："))
        amt = AmountEdit()
        amt.setValue(r["budget"] or None)
        dlg.root.addWidget(amt)
        bar = QHBoxLayout()
        bar.addStretch()
        cancel = button("取消")
        cancel.clicked.connect(dlg.reject)
        ok = button("儲存", "Primary")
        ok.clicked.connect(dlg.accept)
        bar.addWidget(cancel)
        bar.addWidget(ok)
        dlg.root.addLayout(bar)
        amt.setFocus()
        if dlg.exec():
            v = amt.value() or 0
            self.db.update_category(r["id"], budget=max(0.0, v))
            self.ctx.changed()

    def move(self, kind: str, d: int) -> None:
        r = self._sel(kind)
        if not r:
            return
        self.db.move_category(r["id"], d)
        self.ctx.changed()
        t = self.cat_tables[kind]
        for i, row in enumerate(t.model_.rows):
            if row["id"] == r["id"]:
                t.selectRow(i)

    def toggle(self, kind: str) -> None:
        r = self._sel(kind)
        if not r:
            return
        self.db.update_category(r["id"], archived=0 if r["archived"] else 1)
        self.ctx.changed()

    def delete_cat(self, kind: str) -> None:
        r = self._sel(kind)
        if not r:
            return
        n = self.db.category_txn_count(r["id"])
        if n:
            error(self, f"「{r['name']}」已有 {n} 筆紀錄使用，無法刪除。\n可改用「隱藏」，歷史紀錄會保留。",
                  "無法刪除")
            return
        if ask(self, f"確定要刪除分類「{r['name']}」嗎？", yes="刪除", danger=True):
            self.db.delete_category(r["id"])
            self.ctx.changed()

    # ------------------------------------------------------------------ 結帳
    def close_books(self) -> None:
        d = iso(self.close_date.date())
        if d > dt.date.today().isoformat():
            error(self, "結帳日不可晚於今天。")
            return
        if ask(self, f"確定要結帳至 {fmt_date(d)} 嗎？\n此日期（含）以前的紀錄將被鎖定。", yes="結帳"):
            if d < self.db.closed_until and self.db.year_closings() and not ask(
                    self, "結帳日往前移，之後年度的年度結帳分錄會一併作廢。確定嗎？", yes="確定", danger=True):
                return
            self.db.set_closed_until(d)
            self.ctx.changed()

    def reopen_books(self) -> None:
        if not self.db.closed_until:
            info(self, "目前尚未結帳。")
            return
        if ask(self, "確定要解除結帳嗎？解除後所有紀錄都可以修改，年度結帳分錄也會一併作廢。",
               yes="解除結帳", danger=True):
            self.db.set_closed_until("")
            self.ctx.changed()

    def close_year_dialog(self) -> None:
        y = self.close_year.currentData()
        if y is None:
            info(self, "目前沒有已結束、可辦理結帳的年度。")
            return
        from ..dialogs_more import YearCloseDialog
        YearCloseDialog(self.ctx, y, self.window()).exec()

    # ------------------------------------------------------------------ 資料
    def backup(self) -> None:
        default = os.path.join(os.path.expanduser("~"), "Desktop",
                               f"理財帳本備份_{dt.datetime.now():%Y%m%d_%H%M}.db")
        path, _ = QFileDialog.getSaveFileName(self, "備份帳本", default, "帳本備份檔 (*.db)")
        if not path:
            return
        try:
            self.db.backup_to(path)
        except Exception as e:  # noqa: BLE001
            error(self, f"備份失敗：{e}")
            return
        info(self, f"備份完成！\n{path}\n\n建議將備份檔另外存到隨身碟或雲端硬碟。")

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇備份檔", self.ctx.backup_dir,
                                              "帳本備份檔 (*.db)")
        if not path:
            return
        if not ask(self, "還原後，目前帳本內容會被備份檔取代。\n"
                         "（系統會先自動保存目前的帳本，以防萬一）\n確定要還原嗎？", yes="還原", danger=True):
            return
        try:
            self.db.restore_from(path)
        except Exception as e:  # noqa: BLE001
            error(self, f"還原失敗：{e}")
            return
        self.ctx.changed()
        self.ctx.settingsChanged.emit()
        info(self, "還原完成！")

    def reset(self) -> None:
        if not ask(self, "這會刪除所有帳戶與收支紀錄（分類會恢復為預設值）。\n"
                         "建議先執行「立即備份」。確定要繼續嗎？", yes="繼續", danger=True):
            return
        word = self._ask_text("最後確認", "請輸入「清除」兩個字以確認：")
        if word != "清除":
            info(self, "已取消，資料未變更。")
            return
        self.db.backup_to(os.path.join(self.ctx.backup_dir,
                                       f"清除前備份_{dt.datetime.now():%Y%m%d_%H%M%S}.db"))
        self.db.reset_all()
        self.db.set_setting("closed_until", "")
        self.ctx.changed()
        info(self, "已清除所有資料（清除前的資料已自動備份到「自動備份」資料夾）。")
