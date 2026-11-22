"""自動操作程式並錄製功能示範影片（MP4）。

用法：python tools/demo_video.py 輸出.mp4 [Excel截圖資料夾]
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import imageio_ffmpeg  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter,  # noqa: E402
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import QAbstractButton, QPushButton, QScrollArea, QWidget  # noqa: E402

from app.animations import Ripple  # noqa: E402

from app.dialogs import ExportDialog, TransactionDialog  # noqa: E402
from app.dialogs_chart import ChartOfAccountsDialog, SubjectDialog  # noqa: E402
from app.dialogs_invest import PriceDialog, TradeDialog  # noqa: E402
from app.dialogs_more import (AuditDialog, DueRecurringDialog, JournalDialog,  # noqa: E402
                              ReconcileDialog, VoidDialog)
from app.investments import Investments  # noqa: E402
from app.main import MainWindow, create_app  # noqa: E402
from app.sample_data import load_sample_data  # noqa: E402
from app.theme import FONT_FAMILY, app_icon  # noqa: E402

import hashlib  # noqa: E402
import wave  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "demo.mp4"
SILENT = OUT[:-4] + "_silent.mp4"
VOICE = os.environ.get("DEMO_VOICE", "1") == "1"
TTS_DIR = os.path.join(os.path.dirname(os.path.abspath(OUT)), "tts_cache")
TTS_PS1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts.ps1")


def spoken(text: str) -> str:
    for a, b in (("✓", ""), ("／", "、"), ("＝", "等於"), ("→", "")):
        text = text.replace(a, b)
    return text


def tts(text: str) -> tuple[str, float]:
    """以 Windows 內建中文語音（台灣）產生旁白，並快取。"""
    os.makedirs(TTS_DIR, exist_ok=True)
    key = hashlib.md5(text.encode("utf-8")).hexdigest()[:16]
    wav = os.path.join(TTS_DIR, key + ".wav")
    if not os.path.exists(wav):
        txt = os.path.join(TTS_DIR, key + ".txt")
        with open(txt, "w", encoding="utf-8-sig") as fh:
            fh.write(spoken(text))
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        TTS_PS1, txt, wav], check=True, capture_output=True)
    with wave.open(wav) as w:
        return wav, w.getnframes() / w.getframerate()
EXCEL_SHOTS = sys.argv[2] if len(sys.argv) > 2 else None
W, H, FPS = 1280, 800, 15
BAND = 120          # 字幕列高度：字幕放在 App 畫面下方，不會遮住任何內容
HT = H + BAND       # 影片總高度

tmp = tempfile.mkdtemp()
app, ctx = create_app([sys.argv[0]], os.path.join(tmp, "理財帳本.db"))
ctx.db.set_setting("owner_name", "游媽媽")
load_sample_data(ctx.db)
ctx.db.set_setting("sample_data", "0")
win = MainWindow(ctx)
win.resize(W, H)
win.show()
for _ in range(30):
    app.processEvents()
DPR = win.devicePixelRatioF() or 1.0
PW, PH = int(W * DPR) // 2 * 2, int(HT * DPR) // 2 * 2


def font(px: float, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(int(px))
    f.setBold(bold)
    return f


class Recorder:
    def __init__(self):
        self.proc = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-s", f"{PW}x{PH}", "-r", str(FPS), "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", SILENT],
            stdin=subprocess.PIPE)
        self.dialog: QWidget | None = None
        self.caption = ""
        self.step = ""
        self.pointer = QPointF(W * 0.6, H * 0.6)
        self.flash = 0.0
        self.card: tuple | None = None
        self.slide: QPixmap | None = None
        self.frames = 0
        self.t0 = time.perf_counter()
        self.voices: list[tuple[float, str]] = []
        self.voice_end = 0

    # ------------------------------------------------------------------ 畫面
    def dialog_origin(self) -> QPoint:
        d = self.dialog
        return QPoint((W - d.width()) // 2, max(20, (H - d.height()) // 2 - 20))

    def render(self) -> QImage:
        img = QImage(PW, PH, QImage.Format.Format_RGB888)
        img.setDevicePixelRatio(DPR)
        img.fill(QColor("#F3F5F9"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.slide is not None:
            self._draw_slide(p)
        else:
            p.drawPixmap(0, 0, win.grab())
            if self.dialog is not None and self.dialog.isVisible():
                p.fillRect(0, 0, W, H, QColor(15, 23, 42, 110))
                o = self.dialog_origin()
                pm = self.dialog.grab()
                r = QRectF(o.x(), o.y(), self.dialog.width(), self.dialog.height())
                for i in range(12, 0, -2):
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(0, 0, 0, 6))
                    p.drawRoundedRect(r.adjusted(-i, -i + 6, i, i + 6), 14 + i, 14 + i)
                path = QPainterPath()
                path.addRoundedRect(r, 12, 12)
                p.save()
                p.setClipPath(path)
                p.drawPixmap(o, pm)
                p.restore()
        if self.card:
            self._draw_card(p, *self.card)
        if not self.card:
            self._draw_caption(p)
        if self.slide is None and not self.card:
            self._draw_pointer(p)
        p.end()
        return img

    def _draw_caption(self, p: QPainter) -> None:
        """字幕列：位於 App 畫面正下方的獨立區域。"""
        band = QRectF(0, H, W, BAND)
        g = QLinearGradient(0, H, 0, HT)
        g.setColorAt(0, QColor("#1C2840"))
        g.setColorAt(1, QColor("#141D30"))
        p.fillRect(band, g)
        p.fillRect(QRectF(0, H, W, 3), QColor("#2563EB"))
        left = 40
        if self.step:
            p.setFont(font(17, True))
            sw = p.fontMetrics().horizontalAdvance(self.step) + 32
            sr = QRectF(left, H + (BAND - 38) / 2 + 1, sw, 38)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2563EB"))
            p.drawRoundedRect(sr, 10, 10)
            p.setPen(QColor("white"))
            p.drawText(sr, Qt.AlignmentFlag.AlignCenter, self.step)
            left = sr.right() + 28
        p.setPen(QColor("white"))
        size = 30
        p.setFont(font(size, True))
        while p.fontMetrics().horizontalAdvance(self.caption) > W - left - 40 and size > 18:
            size -= 1
            p.setFont(font(size, True))
        p.drawText(QRectF(left, H + 3, W - left - 40, BAND - 3),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.caption)

    def _draw_pointer(self, p: QPainter) -> None:
        x, y = self.pointer.x(), self.pointer.y()
        if self.flash > 0:
            rad = 14 + (1 - self.flash) * 26
            p.setPen(QPen(QColor(37, 99, 235, int(200 * self.flash)), 4))
            p.setBrush(QColor(37, 99, 235, int(60 * self.flash)))
            p.drawEllipse(QPointF(x, y), rad, rad)
            self.flash = max(0.0, self.flash - 0.12)
        path = QPainterPath()
        pts = [(0, 0), (0, 26), (7, 20), (12, 31), (17, 29), (12, 18), (21, 18)]
        path.moveTo(x + pts[0][0], y + pts[0][1])
        for dx, dy in pts[1:]:
            path.lineTo(x + dx, y + dy)
        path.closeSubpath()
        p.setPen(QPen(QColor("#111827"), 2))
        p.setBrush(QColor("white"))
        p.drawPath(path)

    def _draw_card(self, p: QPainter, title: str, sub: str, lines: list[str]) -> None:
        g = QLinearGradient(0, 0, W, HT)
        g.setColorAt(0, QColor("#1C2840"))
        g.setColorAt(1, QColor("#2F4372"))
        p.fillRect(0, 0, W, HT, g)
        p.translate(0, 60)
        p.drawPixmap(W // 2 - 48, 150, app_icon().pixmap(96, 96))
        p.setPen(QColor("white"))
        p.setFont(font(54, True))
        p.drawText(QRectF(0, 270, W, 80), Qt.AlignmentFlag.AlignCenter, title)
        p.setPen(QColor("#C3CDE2"))
        p.setFont(font(26))
        p.drawText(QRectF(0, 352, W, 50), Qt.AlignmentFlag.AlignCenter, sub)
        p.setFont(font(22))
        p.setPen(QColor("#E2E8F0"))
        for i, line in enumerate(lines):
            p.drawText(QRectF(0, 440 + i * 44, W, 40), Qt.AlignmentFlag.AlignCenter, line)
        p.translate(0, -60)

    def _draw_slide(self, p: QPainter) -> None:
        p.fillRect(0, 0, W, H, QColor("#E9EDF3"))
        pm = self.slide
        avail = QRectF(40, 70, W - 80, H - 100)
        s = min(avail.width() / pm.width(), avail.height() / pm.height(), 1.0)
        w, h = pm.width() * s, pm.height() * s
        r = QRectF((W - w) / 2, avail.y(), w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawRoundedRect(r.adjusted(-4, 0, 4, 8), 6, 6)
        p.drawPixmap(r, pm, QRectF(pm.rect()))
        p.setPen(QColor("#107C41"))
        p.setFont(font(22, True))
        p.drawText(QRectF(40, 20, W - 80, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Microsoft Excel　｜　匯出的報表")

    # ------------------------------------------------------------------ 時間軸
    def frame(self) -> None:
        app.processEvents()
        img = self.render()
        bpl = img.bytesPerLine()
        data = bytes(img.constBits())
        if bpl != PW * 3:
            data = b"".join(data[i * bpl:i * bpl + PW * 3] for i in range(PH))
        self.proc.stdin.write(data)
        self.frames += 1
        target = self.t0 + self.frames / FPS
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

    def hold(self, sec: float) -> None:
        for _ in range(max(1, int(sec * FPS))):
            self.frame()

    def wait_voice(self) -> None:
        if self.frames < self.voice_end:
            self.hold((self.voice_end - self.frames) / FPS + 0.25)

    def say(self, text: str, step: str | None = None, sec: float = 0.0) -> None:
        if VOICE and text and text != self.caption:
            self.wait_voice()
            wav, dur = tts(text)
            self.t0 = time.perf_counter() - self.frames / FPS
            self.voices.append((self.frames / FPS, wav))
            self.voice_end = self.frames + int(dur * FPS)
        self.caption = text
        if step is not None:
            self.step = step
        if sec:
            self.hold(sec)

    def pos_of(self, w: QWidget) -> QPointF:
        c = w.rect().center()
        if self.dialog is not None and self.dialog.isVisible() and \
                (w is self.dialog or self.dialog.isAncestorOf(w)):
            pt = w.mapTo(self.dialog, c) + self.dialog_origin()
        else:
            pt = w.mapTo(win, c)
        return QPointF(pt.x(), pt.y())

    def move(self, target, sec: float = 0.6) -> None:
        end = self.pos_of(target) if isinstance(target, QWidget) else QPointF(*target)
        start = QPointF(self.pointer)
        n = max(1, int(sec * FPS))
        for i in range(1, n + 1):
            t = i / n
            e = 0.5 - math.cos(math.pi * t) / 2
            self.pointer = start + (end - start) * e
            self.frame()

    def click(self, w: QWidget, action=None, sec: float = 0.6) -> None:
        self.wait_voice()
        self.move(w, sec)
        self.flash = 1.0
        if isinstance(w, QAbstractButton):
            Ripple(w, w.rect().center())
        self.hold(0.15)
        if action:
            action()
        elif isinstance(w, QPushButton):
            w.click()
        self.hold(0.35)

    def type(self, edit, text: str, per_char: float = 0.11) -> None:
        self.move(edit, 0.5)
        self.flash = 1.0
        edit.setFocus()
        edit.clear() if hasattr(edit, "clear") else None
        for ch in text:
            edit.setText(edit.text() + ch)
            self.hold(per_char)
        self.hold(0.3)

    def scroll(self, area: QScrollArea | QWidget, to: int, sec: float = 2.0) -> None:
        bar = area.verticalScrollBar()
        start = bar.value()
        n = max(1, int(sec * FPS))
        for i in range(1, n + 1):
            t = i / n
            e = 0.5 - math.cos(math.pi * t) / 2
            bar.setValue(int(start + (to - start) * e))
            self.frame()

    def open_dialog(self, dlg: QWidget) -> None:
        dlg.show()
        app.processEvents()
        self.dialog = dlg
        self.hold(0.4)

    def close_dialog(self) -> None:
        if self.dialog is not None:
            self.dialog.close()
        self.dialog = None
        self.hold(0.2)

    def finish(self) -> None:
        self.proc.stdin.close()
        self.proc.wait()
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        if not self.voices:
            os.replace(SILENT, OUT)
            return
        cmd = [ff, "-y", "-loglevel", "error", "-i", SILENT]
        parts = []
        for i, (t, wav) in enumerate(self.voices, 1):
            cmd += ["-i", wav]
            ms = int(t * 1000)
            parts.append(f"[{i}]aresample=44100,adelay={ms}|{ms}[a{i}]")
        mix = "".join(f"[a{i}]" for i in range(1, len(self.voices) + 1))
        total = self.frames / FPS
        flt = ";".join(parts) + f";{mix}amix=inputs={len(self.voices)}:normalize=0:dropout_transition=0," \
              f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,apad=whole_dur={total:.3f}," \
              f"atrim=0:{total:.3f}[aout]"
        cmd += ["-filter_complex", flt, "-map", "0:v", "-map", "[aout]", "-c:v", "copy",
                "-ac", "2", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", OUT]
        import json
        with open(OUT[:-4] + "_voices.json", "w", encoding="utf-8") as fh:
            json.dump({"voices": self.voices, "total": total}, fh, ensure_ascii=False)
        subprocess.run(cmd, check=True, timeout=300)
        os.remove(SILENT)


def find_button(root: QWidget, text: str) -> QPushButton:
    for b in root.findChildren(QPushButton):
        if b.text().strip() == text and b.isVisible():
            return b
    for b in root.findChildren(QPushButton):
        if text in b.text() and b.isVisible():
            return b
    raise LookupError(text)


def page_scroll(key: str) -> QScrollArea:
    return win.pages[key].findChild(QScrollArea)


def nav(key: str, label: str) -> None:
    rec.click(win.nav_buttons[key], lambda: win.go(key))
    rec.hold(0.4)


def select_combo(combo, text: str) -> None:
    for i in range(combo.count()):
        if text in combo.itemText(i):
            combo.setCurrentIndex(i)
            return


# 示範用：建立一筆已到期的定期交易（首頁會出現提醒）
_post = next(a for a in ctx.db.list_accounts() if a["name"] == "郵局活儲")
_cat = ctx.db.find_category("expense", "居家水電")
ctx.db.save_recurring(None, "社區管理費", {"type": "expense", "account_id": _post["id"], "amount": 2400,
                                       "category_id": _cat["id"], "note": "社區管理費"},
                      "monthly", 15, "2026-10-01")
ctx.changed()
for _ in range(20):
    app.processEvents()

rec = Recorder()

# ============================================================== 片頭
rec.card = ("我的理財帳本", "個人資產與記帳管理　・　功能示範",
            ["日記帳　分類帳　資產負債表　損益表　現金流量表　試算表",
             "投資管理　一鍵匯出專業 Excel 報表"])
rec.hold(0.8)
if VOICE:
    wav, dur = tts("游媽媽您好，歡迎使用我的理財帳本。接下來為您示範主要功能。")
    rec.voices.append((rec.frames / FPS, wav))
    rec.voice_end = rec.frames + int(dur * FPS)
rec.hold(3.2)
rec.wait_voice()
rec.card = None

dash = win.pages["dashboard"]
# ============================================================== 1. 總覽
win.go("dashboard")
rec.say("首頁總覽：淨資產、本月收支一目了然", "1　首頁總覽", 0.5)
rec.move(dash.c_net, 1.0)
rec.hold(1.2)
rec.say("財務健康指標：負債比率、流動比率、緊急預備金、儲蓄率")
rec.move(dash.ratio_labels["current_ratio"], 0.8)
rec.hold(1.5)
rec.say("提醒事項：定存、保單即將到期，以及到期的定期交易")
rec.move(dash.remind_card, 0.8)
rec.hold(1.5)
area = page_scroll("dashboard")
rec.say("資產配置、近 12 個月收支、淨資產趨勢與預算執行")
rec.scroll(area, 520, 2.2)
rec.hold(1.6)
rec.scroll(area, 0, 1.0)

# ============================================================== 2. 定期交易
rec.say("定期交易到期了，按「確認入帳」", "2　定期交易", 0.3)
due = ctx.db.due_recurring()
dlg = DueRecurringDialog(ctx, due, win)
rec.click(find_button(dash, "確認入帳"), lambda: rec.open_dialog(dlg))
rec.say("金額可以先修改，確認後一鍵入帳，不會自動亂記帳", sec=1.2)
rec.click(find_button(dlg, "入帳所選"), dlg.post)
rec.dialog = None
rec.hold(1.2)

# ============================================================== 3. 記支出
rec.say("記一筆支出：點右上角「記支出」", "3　日常記帳", 0.3)
btn = find_button(dash, "記支出")
dlg = TransactionDialog(ctx, "expense", parent=win)
rec.click(btn, lambda: rec.open_dialog(dlg))
rec.say("金額可以直接輸入算式，例如 120+35")
rec.type(dlg.amount, "120+35", 0.18)
rec.hold(0.4)
dlg.amount._normalize()
rec.say("自動計算成 155 元，再點選分類")
rec.click(find_button(dlg, "餐飲"))
rec.type(dlg.note, "早餐和咖啡", 0.2)
rec.say("按「儲存」完成，也可以附上收據照片")
rec.click(find_button(dlg, "儲存"), lambda: dlg.save(False))
rec.dialog = None
rec.hold(1.0)

# ============================================================== 4. 複式分錄
rec.say("需要拆分多個科目時，用「複式分錄」", "4　複式分錄", 0.3)
win.go("transactions")
rec.hold(0.6)
tp = win.pages["transactions"]
dlg = JournalDialog(ctx, parent=win)
rec.click(find_button(tp, "複式分錄"), lambda: rec.open_dialog(dlg))
rec.say("選擇常用範本，例如「年繳保費」")
rec.click(dlg.template, lambda: (dlg.template.setCurrentIndex(2), dlg.apply_template(2)))
rec.hold(0.8)
rec.type(dlg.table.cellWidget(0, 1), "48000", 0.12)
rec.type(dlg.table.cellWidget(1, 1), "12000", 0.12)
rec.say("按「自動平衡差額」，借貸平衡才能儲存")
rec.click(find_button(dlg, "自動平衡差額"), dlg.auto_balance)
rec.hold(1.2)
rec.click(find_button(dlg, "儲存"), dlg.save)
rec.dialog = None
rec.hold(1.0)

# ============================================================== 5. 收支明細、作廢與修改紀錄
rec.say("收支明細：每筆傳票都有傳票號碼", "5　收支明細", 2.0)
rec.say("輸入錯誤時用「作廢」，不會真的刪除，帳務有跡可循")
tp.table.selectRow(0)
row = tp.table.current_row()
vd = VoidDialog(win)
rec.click(find_button(tp, "作廢"), lambda: rec.open_dialog(vd))
vd.reason.setCurrentText("重複輸入")
rec.hold(1.0)
rec.click(find_button(vd, "作廢"), lambda: (vd.accept(), ctx.db.void_transactions([row["id"]], "重複輸入"),
                                           ctx.changed()))
rec.dialog = None
rec.click(tp.show_void, lambda: tp.show_void.setChecked(True))
rec.hold(1.0)
rec.say("勾選「顯示已作廢」可以看到作廢的傳票與原因", sec=1.5)
ad = AuditDialog(ctx, parent=win)
rec.say("每一次新增、修改、作廢都會留下修改紀錄，可供稽核")
rec.open_dialog(ad)
rec.hold(2.0)
rec.close_dialog()
tp.show_void.setChecked(False)

# ============================================================== 6. 會計科目、帳戶與銀行對帳
rec.wait_voice()
rec.step = "6　會計科目與帳戶"
nav("accounts", "帳戶管理")
rec.say("帳戶管理：資產與負債依流動性分類，外幣自動換算", sec=1.6)
ap = win.pages["accounts"]
cd = ChartOfAccountsDialog(ctx, win)
rec.say("會計科目表：資產 1、負債 2、權益 3、收入 4、費用 5")
rec.click(find_button(ap, "會計科目表"), lambda: rec.open_dialog(cd))
rec.hold(1.6)
sd = SubjectDialog(ctx, "asset", parent=cd)
rec.say("按「新增會計科目」，例如新增一個「長期投資」科目")
rec.click(find_button(cd, "新增會計科目"), lambda: rec.open_dialog(sd))
rec.click(sd.category, lambda: sd.category.setCurrentText("長期投資"))
rec.hold(0.6)
rec.type(sd.name, "長期投資－中華電信", 0.14)
rec.say("科目代號依編碼原則自動建議，也可以改成自己習慣的代號")
rec.move(sd.code, 0.6)
rec.hold(1.4)
rec.click(find_button(sd, "儲存"), sd.save)
cd.load()
cd.show()
rec.dialog = cd
rec.hold(0.4)
cd.table.scrollTo(cd.table.model().index(
    next(i for i, r in enumerate(cd.table.model_.rows) if "中華電信" in r["name"]), 0))
rec.say("新科目立刻出現在科目表，記帳和分錄都可以直接選用", sec=1.0)
rec.wait_voice()
rec.hold(0.4)
rec.close_dialog()
rec.say("拿出存摺，用「更多功能 → 銀行對帳」逐筆勾選核對", "6　會計科目與帳戶")
post_id = next(a["id"] for a in ctx.db.list_accounts() if a["name"] == "郵局活儲")
rd = ReconcileDialog(ctx, post_id, win)
rec.click(ap.more_btn, lambda: rec.open_dialog(rd))
rec.click(find_button(rd, "全部勾選"), lambda: rd._check_all(True))
rec.say("差額為 0 就是對帳完成；沒勾選的就是未達帳項")
rec.move(rd.lbl, 0.6)
rec.hold(1.4)
rec.click(find_button(rd, "完成對帳"), rd.finish)
rec.dialog = None
rec.hold(0.8)

# ============================================================== 7. 投資管理
rec.wait_voice()
rec.step = "7　投資管理"
nav("investments", "投資管理")
ip = win.pages["investments"]
rec.say("投資管理：持股、平均成本、已實現與未實現損益", sec=1.8)
rec.say("賣出時自動帶入手續費與證交稅，並計算已實現損益")
sid = next(h["id"] for h in Investments(ctx.db).holdings() if h["code"] == "0056")
td = TradeDialog(ctx, "sell", sid, parent=win)
rec.click(find_button(ip, "賣出"), lambda: rec.open_dialog(td))
rec.type(td.shares, "2000", 0.15)
rec.hold(0.6)
rec.move(td.calc, 0.6)
rec.hold(1.6)
rec.click(find_button(td, "儲存"), td.save)
rec.dialog = None
rec.say("股利會自動扣除二代健保補充保費，所有分錄由系統自動產生", sec=1.4)
rec.say("也可以直接用複式分錄買股票：借 短期投資，貸 銀行存款")
jd = JournalDialog(ctx, parent=win)
win.go("transactions", animate=False)
rec.hold(0.3)
rec.click(find_button(tp, "複式分錄"), lambda: rec.open_dialog(jd))
_ti = next(i for i, (n, _) in enumerate(JournalDialog.TEMPLATES) if n.startswith("買進股票"))
rec.click(jd.template, lambda: (jd.template.setCurrentIndex(_ti), jd.apply_template(_ti)))
rec.hold(0.6)
rec.type(jd.table.cellWidget(0, 1), "50071", 0.12)
cell = jd.table.cellWidget(0, 3)
rec.say("在投資科目那一行選擇投資標的與股數，就會計入持股明細")
s0050 = next(x["id"] for x in Investments(ctx.db).list_securities() if x["code"] == "0050")
rec.click(cell.sec, lambda: (cell.sec.setCurrentIndex(cell.sec.findData(s0050)),
                             jd._sec_chosen(cell, jd.table.cellWidget(0, 0))))
rec.type(cell.shares, "500", 0.15)
rec.type(jd.note, "買進 元大台灣50 500 股", 0.08)
rec.click(find_button(jd, "自動平衡差額"), jd.auto_balance)
rec.move(jd.inv_info, 0.6)
rec.hold(1.2)
rec.click(find_button(jd, "儲存"), jd.save)
rec.dialog = None
nav("investments", "投資管理")
rec.say("買賣不會自動評價。需要評價時，選日期並輸入市價：借 短期投資，貸 未實現評價損益")
pd = PriceDialog(ctx, win)
rec.click(find_button(ip, "市價評價"), lambda: rec.open_dialog(pd))
_pi = next(i for i, h in enumerate(pd.holdings) if h["code"] == "0050")
rec.type(pd.edits[_pi], f"{pd.holdings[_pi]['price'] * 1.03:.2f}", 0.14)
rec.hold(0.8)
rec.click(find_button(pd, "產生評價分錄"), pd.save)
rec.dialog = None
rec.hold(1.4)

# ============================================================== 8. 財務報表
rec.wait_voice()
rec.step = "8　財務報表"
nav("reports", "財務報表")
rp = win.pages["reports"]
tab = rp.tabs.tabBar()


def open_tab(name: str, text: str, sec: float = 2.4) -> None:
    rec.wait_voice()
    idx = rp._tab_index(name)
    target = tab.mapTo(win, tab.tabRect(idx).center())
    rec.move((target.x(), target.y()), 0.6)
    rec.flash = 1.0
    rp.tabs.setCurrentIndex(idx)
    rec.say(text, sec=sec)


open_tab("資產負債表", "資產負債表：流動／非流動資產與負債，並附財務比率")
rec.scroll(rp.bs, rp.bs.verticalScrollBar().maximum(), 2.0)
open_tab("收支損益表", "收支損益表：可選擇「與去年同期比較」", 0.8)
rp.is_cmp.setCurrentIndex(rp.is_cmp.findData("prior_year"))
rec.hold(1.6)
open_tab("現金流量表", "現金流量表：生活、投資、籌資活動，期初加淨增減等於期末")
rec.scroll(rp.cf, rp.cf.verticalScrollBar().maximum(), 2.0)
open_tab("日記帳", "日記帳：每張傳票的科目代號、借方與貸方，自動核對借貸平衡")
rec.type(rp.jnl_kw, "元大台灣50", 0.14)
rec.hold(0.3)
rec.scroll(rp.jnl, rp.jnl.verticalScrollBar().maximum(), 1.6)
rec.say("剛才買進的分錄，以及手動評價產生的分錄都在這裡", sec=1.5)
rec.wait_voice()
rec.hold(0.6)
rp.jnl_kw.clear()
open_tab("分類帳", "分類帳：任一科目的借方、貸方與累計餘額")
open_tab("試算表", "試算表：借貸合計自動核對 ✓ 借貸平衡", 0.6)
rec.move(rp.tb_sum, 0.8)
rec.hold(1.4)
open_tab("報稅彙總", "報稅彙總：利息、股利、退職所得與可扣除項目，報稅時參考")

# ============================================================== 10. 設定
rec.wait_voice()
rec.step = "10　設定"
nav("settings", "設定")
sp = win.pages["settings"]
rec.say("文字大小可調整：標準／大／特大")
rec.click(sp.font_buttons["xlarge"], lambda: sp.font_buttons["xlarge"].setChecked(True))
rec.hold(1.6)
rec.click(sp.font_buttons["large"], lambda: sp.font_buttons["large"].setChecked(True))
rec.say("動畫效果也可以在這裡開啟或關閉")
rec.move(sp.anim_switch, 0.7)
rec.hold(1.0)
area = page_scroll("settings")
rec.say("網路更新股價與匯率為選用功能，預設關閉，沒有網路也完全不影響")
rec.scroll(area, area.verticalScrollBar().maximum() - 420, 1.8)
rec.move(sp.online, 0.7)
rec.hold(1.6)
rec.say("每天自動備份，也可手動備份到隨身碟、隨時還原", sec=1.6)
rec.scroll(area, 0, 0.6)

# ============================================================== 11. 匯出 Excel
rec.wait_voice()
rec.step = "11　匯出 Excel"
rec.say("一鍵匯出 Excel 報表")
exp_btn = find_button(win, "匯出 Excel 報表")
dlg = ExportDialog(ctx, win)
rec.click(exp_btn, lambda: rec.open_dialog(dlg))
dlg.open_after.setChecked(False)
shown_path = dlg.path.text().replace(tmp, r"C:\Users\游媽媽\Documents\我的理財帳本")
real_path = dlg.path.text()
dlg.path.setText(shown_path)
rec.say("共 12 張工作表，合計都是 Excel 公式，可稽核", sec=1.2)
rec.click(find_button(dlg, "匯出"), lambda: (dlg.path.setText(real_path), dlg.do_export()))
rec.dialog = None
rec.hold(0.5)

if EXCEL_SHOTS and os.path.isdir(EXCEL_SHOTS):
    titles = {
        "01": "財務摘要：重要數字與各工作表說明",
        "02": "資產負債表：小計、合計皆為公式，並自動檢查平衡",
        "03": "收支損益表：以 SUMIFS 公式自明細彙總，含業外損益",
        "04": "現金流量表：期初＋淨增減＝期末，自動勾稽",
        "05": "收支明細：可篩選，合計自動重算",
        "06": "月度收支：含儲蓄率、累計結餘與圖表",
        "08": "日記簿：每張傳票的借貸分錄",
        "09": "試算表：借貸合計 ✓ 平衡",
        "11": "投資明細：持股、成本、帳面價值與未實現損益",
        "12": "報稅彙總：所得與扣除項目，報稅參考",
    }
    for name in sorted(os.listdir(EXCEL_SHOTS)):
        key = name.split("_")[0]
        if key in titles and name.lower().endswith(".png"):
            rec.wait_voice()
            rec.slide = QPixmap(os.path.join(EXCEL_SHOTS, name))
            rec.say(titles[key], "11　匯出 Excel", 2.4)
    rec.slide = None

# ============================================================== 片尾
rec.wait_voice()
rec.caption = ""
rec.card = ("我的理財帳本", "專業、清楚、容易使用",
            ["所有資料只存在這台電腦，每天自動備份",
             "單一執行檔，雙擊即可使用，不需安裝，也不需要網路"])
if VOICE:
    wav, dur = tts("所有資料只存在這台電腦，每天自動備份。祝您使用愉快！")
    rec.voices.append((rec.frames / FPS, wav))
    rec.voice_end = rec.frames + int(dur * FPS)
rec.hold(3.0)
rec.wait_voice()
rec.hold(1.0)
rec.finish()
print("video:", OUT, f"{rec.frames / FPS:.1f}s")
