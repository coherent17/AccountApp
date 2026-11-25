"""月結小幫手、到期提醒中心、現金流預測、資料健康檢查、月報、智慧對帳與意見回饋。帳務計算都在 core/。"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import tempfile

from core import bankmatch, forecast, health, monthclose, reminders, yearclose
from core.database import month_keys

from desktop.rpc import exposed


class ToolsApi:
    # ------------------------------------------------------------------ 到期提醒中心
    @exposed
    def reminders_upcoming(self, days: int = 90) -> dict:
        return {"events": reminders.upcoming(self._db, int(days)), "custom": reminders.list_custom(self._db),
                "kinds": list(reminders.KINDS.items()), "freqs": list(reminders.FREQS.items()),
                "accounts": [{"id": a["id"], "name": a["name"], "kind": a["kind"]} for a in self._db.list_accounts()]}

    # ------------------------------------------------------------------ 現金流預測
    @exposed
    def cash_forecast(self, months: int = 6) -> dict:
        return forecast.forecast(self._db, max(1, min(24, int(months))))

    @exposed
    def set_forecast_low(self, value: float) -> None:
        if value is None or value < 0:
            raise ValueError("請輸入 0 以上的金額")
        self._db.set_setting(forecast.LOW_KEY, str(value))

    # ------------------------------------------------------------------ 意見回饋（不會自動上傳：存檔並複製到剪貼簿，由她貼到 LINE）
    @exposed(db=False)
    def feedback_capture(self) -> str:
        """擷取本程式目前的畫面（只拍這個視窗），傳回 PNG 的 data URL；失敗時傳回空字串。"""
        from desktop.screenshot import grab_window
        path = os.path.join(tempfile.gettempdir(), "myledger_feedback_shot.png")
        self._fb_capture = "正常"
        try:
            grab_window(int(self._window.native.Handle.ToInt64()), path)
            with open(path, "rb") as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode()
        except Exception as e:  # noqa: BLE001 — 拍不到畫面時仍可只寫文字；原因寫進診斷資訊
            self._fb_capture = f"失敗：{type(e).__name__} {e}"[:120]
            return ""
        finally:
            if os.path.exists(path):
                os.remove(path)

    def _fb_dir(self, *sub: str) -> str:
        d = os.path.join(self._folder, "意見回饋", *sub)
        os.makedirs(d, exist_ok=True)
        return d

    def _fb_path(self, *parts: str) -> str:          # 只組路徑，不建立資料夾（開啟程式時不要多出空資料夾）
        return os.path.join(self._folder, "意見回饋", "待傳送", *parts)

    def _fb_items(self) -> list[dict]:
        p = self._fb_path("items.json")
        try:
            with open(p, encoding="utf-8") as f:
                items = json.load(f)
            return items if isinstance(items, list) else []
        except (OSError, ValueError):
            return []

    def _fb_write(self, items: list[dict]) -> None:
        with open(os.path.join(self._fb_dir("待傳送"), "items.json"), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)

    @exposed(db=False)
    def feedback_items(self) -> list[dict]:
        """還沒做成 PDF 的回饋（可以累積好幾則），附上畫面的 data URL。"""
        return self._fb_list()

    def _fb_list(self) -> list[dict]:
        out = []
        for it in self._fb_items():
            shot = self._fb_path(it["id"] + ".png") if it.get("shot") else ""
            data = ""
            if shot and os.path.exists(shot):
                with open(shot, "rb") as f:
                    data = "data:image/png;base64," + base64.b64encode(f.read()).decode()
            out.append({**it, "shot": data})
        return out

    @exposed(db=False)
    def feedback_add(self, item: dict) -> list[dict]:
        note, tag = (item.get("note") or "").strip(), (item.get("tag") or "").strip()
        if not note and not tag and not item.get("shot"):
            raise ValueError("請寫下想告訴我們的事，或點選一個類型。")
        rid = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shot = item.get("shot") or ""
        if shot:
            with open(os.path.join(self._fb_dir("待傳送"), rid + ".png"), "wb") as f:
                f.write(base64.b64decode(shot.split(",", 1)[1]))
        items = self._fb_items()
        items.append({"id": rid, "at": dt.datetime.now().strftime("%Y/%m/%d %H:%M"), "tag": tag, "note": note,
                      "page": (item.get("page") or "")[:40], "shot": bool(shot)})
        self._fb_write(items)
        return self._fb_list()

    @exposed(db=False)
    def feedback_remove(self, rid: str) -> list[dict]:
        self._fb_remove(rid)
        return self._fb_list()

    def _fb_remove(self, rid: str) -> None:
        shot = self._fb_path(rid + ".png")
        if os.path.exists(shot):
            os.remove(shot)
        self._fb_write([it for it in self._fb_items() if it["id"] != rid])

    @exposed
    def feedback_diag(self) -> dict:
        """PDF 最後一頁的診斷資訊：版本、Windows、資料筆數與最近的錯誤紀錄（不含金額）。"""
        import platform
        from core.database import SCHEMA_VERSION
        from core.version import APP_VERSION
        db = self._db
        n = lambda sql: db._q1(sql)["n"]  # noqa: E731
        log = os.path.join(self._folder, "錯誤紀錄.log")
        tail = ""
        if os.path.exists(log):
            with open(log, encoding="utf-8", errors="replace") as f:
                tail = f.read()[-3000:]
        return {"version": APP_VERSION, "windows": platform.platform(), **_display_info(), "capture": getattr(self, "_fb_capture", "—"), "schema": SCHEMA_VERSION,
                "accounts": n("SELECT COUNT(*) n FROM accounts"), "vouchers": n("SELECT COUNT(*) n FROM transactions"),
                "securities": n("SELECT COUNT(*) n FROM securities"), "recurring": n("SELECT COUNT(*) n FROM recurring"),
                "closed_until": db.closed_until, "error_log": tail}

    @exposed(db=False)
    def feedback_pdf(self, pages: list[str], clear: bool = True) -> dict:
        """把畫好的每一頁（JPEG data URL）做成 PDF，存進「意見回饋」資料夾，並把檔案複製起來（可在 LINE 按 Ctrl+V 貼上）。"""
        from core import pdfimages
        folder = self._fb_dir()
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
        path = os.path.join(folder, f"意見回饋_{stamp}.pdf")
        k = 2
        while os.path.exists(path):
            path = os.path.join(folder, f"意見回饋_{stamp}_{k}.pdf")
            k += 1
        pdfimages.write(path, [base64.b64decode(p.split(",", 1)[1]) for p in pages], f"我的理財帳本 意見回饋 {stamp}")
        if clear:          # 已做成 PDF 的回饋從待傳送清單移除（PDF 本身保留）
            for it in self._fb_items():
                self._fb_remove(it["id"])
        return {"path": path, "folder": folder, "copied": _copy_file(path)}

    @exposed(db=False)
    def feedback_copy(self, path: str) -> bool:
        """完成畫面的「再複製一次」：只接受「意見回饋」資料夾裡的 PDF。"""
        folder = os.path.realpath(self._fb_dir())
        real = os.path.realpath(path)
        if not (real.startswith(folder + os.sep) and real.lower().endswith(".pdf") and os.path.exists(real)):
            raise ValueError("找不到這個 PDF")
        return _copy_file(real)

    # ------------------------------------------------------------------ 提醒的新增、修改、刪除
    @exposed
    def reminder_save(self, item: dict) -> dict:
        return reminders.save_custom(self._db, item)

    @exposed
    def reminder_delete(self, rid: str) -> None:
        reminders.delete_custom(self._db, rid)

    # ------------------------------------------------------------------ 月結小幫手
    @exposed
    def month_close(self, ym: str | None = None) -> dict:
        db = self._db
        ym = ym or monthclose.previous_month()
        st = monthclose.status(db, ym)
        lo, _ = db.date_range()
        this = dt.date.today().strftime("%Y-%m")
        st["months"] = [k for k in month_keys(lo[:7] + "-01", dt.date.today().isoformat()) if k <= this][::-1][:24]
        return st

    @exposed
    def month_close_check(self, ym: str, key: str, on: bool = True) -> None:
        monthclose.check(self._db, ym, key, on)

    @exposed
    def month_close_finish(self, ym: str) -> None:
        monthclose.finish(self._db, ym)

    @exposed
    def month_close_prompt(self) -> str:
        """開啟程式時：月初還沒完成上個月的月結就提醒一次（之後只在總覽顯示）。"""
        ym = monthclose.should_prompt(self._db)
        if ym:
            monthclose.mark_prompted(self._db, ym)
        return ym

    # ------------------------------------------------------------------ 年度結帳小幫手
    @exposed
    def year_assist(self, year: int | None = None) -> dict:
        return yearclose.status(self._db, int(year) if year else yearclose.default_year())

    @exposed
    def year_assist_check(self, year: int, key: str, on: bool = True) -> None:
        yearclose.check(self._db, int(year), key, on)

    # ------------------------------------------------------------------ 健康檢查與月報
    @exposed
    def health_run(self) -> dict:
        self._health = health.run(self._db, self._folder)
        return self._health

    @exposed
    def health_html(self) -> str:
        from core.printing import Report
        res = getattr(self, "_health", None) or health.run(self._db, self._folder)
        return Report(self._db).health(res)

    @exposed
    def monthly_html(self, ym: str) -> str:
        from core.printing import Report
        return Report(self._db).monthly(ym)

    # ------------------------------------------------------------------ 智慧對帳
    @exposed
    def recon_match(self, aid: int, date: str, path: str) -> dict:
        db = self._db
        st = bankmatch.read_statement(path)
        book = [{"txn_id": c["txn_id"], "date": c["date"], "effect": c["effect"]} for c in db.recon_candidates(aid, date)]
        m = bankmatch.match(book, st["rows"], date)
        return {**m, "rows": len(st["rows"]), "last_date": st["last_date"], "last_balance": st["last_balance"],
                "later": sum(1 for r in st["rows"] if r["date"] > date)}


def _display_info() -> dict:
    """螢幕的實際解析度、Windows 縮放與「協助工具 → 文字大小」（畫面裡的 screen／devicePixelRatio 是三者相乘後的結果，
    不能直接當成解析度與縮放）。讀不到時為 None。"""
    out = {"screen": None, "dpi_scale": None, "text_scale": None}
    try:
        import ctypes
        u = ctypes.windll.user32       # pywebview 已設為 DPI 感知，所以這裡是實際像素
        out["screen"] = [u.GetSystemMetrics(0), u.GetSystemMetrics(1)]
        out["dpi_scale"] = round(u.GetDpiForSystem() / 96 * 100)
    except Exception:  # noqa: BLE001
        pass
    try:
        import winreg
        out["text_scale"] = 100        # 從沒調整過時沒有這個值
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as k:
            out["text_scale"] = int(winreg.QueryValueEx(k, "TextScaleFactor")[0])
    except Exception:  # noqa: BLE001
        pass
    return out


def _copy_file(path: str) -> bool:
    """把檔案「複製」到 Windows 剪貼簿（如同在檔案總管按複製），讓她在 LINE 按 Ctrl+V 貼上傳送。"""
    if os.environ.get("MY_LEDGER_SHOT"):      # 開發用截圖時不碰使用者的剪貼簿
        return False
    try:
        import clr
        clr.AddReference("System.Windows.Forms")
        from System.Collections.Specialized import StringCollection
        from System.Threading import ApartmentState, Thread, ThreadStart
        from System.Windows.Forms import Clipboard
        done = []

        def work():
            files = StringCollection()
            files.Add(path)
            Clipboard.SetFileDropList(files)
            done.append(True)
        t = Thread(ThreadStart(work))
        t.SetApartmentState(ApartmentState.STA)      # 剪貼簿只能在 STA 執行緒使用
        t.Start()
        t.Join()
        return bool(done)
    except Exception:  # noqa: BLE001
        return False
