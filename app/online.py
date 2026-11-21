"""選用的線上資料更新（預設關閉，需在「設定」開啟）。

資料來源（皆為公開資料，只下載、不上傳任何個人資料）：
* 股價：臺灣證券交易所 OpenAPI（上市）、證券櫃檯買賣中心 OpenAPI（上櫃）— 官方開放資料。
* 匯率：ExchangeRate-API（open.er-api.com）國際市場參考匯率（中價），與銀行牌告可能略有差異。
* 新版本：GitHub Releases（本程式的發行頁），只讀取最新版本號碼與說明、下載新版程式。

所有連線皆使用 HTTPS 並驗證憑證；無網路或逾時時拋出 OfflineError，由介面提示改用手動輸入。
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from PySide6.QtCore import QObject, QThread, Signal

FX_API = "https://open.er-api.com/v6/latest/USD"
FX_SOURCE = "ExchangeRate-API 國際市場參考匯率（中價，與銀行牌告可能略有差異）"
TWSE_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_ALL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
PRICE_SOURCE = "臺灣證券交易所、證券櫃檯買賣中心 官方開放資料（最近一個交易日收盤價）"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MyLedger/2.0"}
TIMEOUT = 15


class OfflineError(Exception):
    """無法連線或資料無法取得。"""


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    ctx = ssl.create_default_context()
    # Python 3.13 起預設啟用嚴格檢查，部分政府網站憑證缺少 Subject Key Identifier 會被拒絕；
    # 僅關閉此嚴格旗標，憑證鏈與主機名稱仍照常驗證。
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OfflineError("無法連線到網路，請確認網路後再試，或改用手動輸入。") from e


def _num(s) -> float | None:
    try:
        v = float(str(s).replace(",", "").strip())
        return v if v > 0 else None
    except ValueError:
        return None


def fetch_fx_rates(base: str = "TWD") -> dict[str, float]:
    """回傳 {幣別: 1 單位外幣折合多少本位幣}。"""
    try:
        data = json.loads(_get(FX_API))
    except ValueError as e:
        raise OfflineError("匯率資料格式錯誤，請稍後再試或改用手動輸入。") from e
    rates = data.get("rates") or {}
    if data.get("result") != "success" or base not in rates:
        raise OfflineError("暫時無法取得匯率資料，請稍後再試或改用手動輸入。")
    b = rates[base]
    return {code: round(b / v, 4) for code, v in rates.items() if v}


def fetch_tw_prices() -> dict[str, tuple[str, float]]:
    """回傳 {證券代號: (名稱, 收盤價)}，含上市與上櫃。"""
    out: dict[str, tuple[str, float]] = {}
    errors = []
    for url, code_key, name_key, price_key in ((TWSE_ALL, "Code", "Name", "ClosingPrice"),
                                               (TPEX_ALL, "SecuritiesCompanyCode", "CompanyName", "Close")):
        try:
            for r in json.loads(_get(url)):
                code = (r.get(code_key) or "").strip()
                p = _num(r.get(price_key, ""))
                if code and p and code not in out:
                    out[code] = ((r.get(name_key) or "").strip(), p)
        except (OfflineError, ValueError) as e:
            errors.append(str(e))
    if not out:
        raise OfflineError(errors[0] if errors else "暫時無法取得股價資料，請改用手動輸入。")
    return out


# ---------------------------------------------------------------- 新版本檢查
REPO = "coherent17/AccountApp"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET_NAME = "MyLedger.exe"


def parse_version(text: str) -> tuple[int, ...]:
    """'v2.7.0' -> (2, 7, 0)；無法解析時回傳 ()。"""
    nums = []
    for part in (text or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        nums.append(int(digits))
    return tuple(nums)


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def parse_release(data: dict) -> dict:
    """GitHub API 的最新版本資料 -> 本程式需要的欄位。"""
    tag = data.get("tag_name") or ""
    if not parse_version(tag):
        raise OfflineError("無法讀取最新版本資訊，請稍後再試。")
    asset = next((a for a in data.get("assets") or [] if a.get("name") == ASSET_NAME), None)
    digest = (asset or {}).get("digest") or ""
    return {"version": ".".join(map(str, parse_version(tag))), "tag": tag,
            "notes": data.get("body") or "",
            "published": (data.get("published_at") or "")[:10],
            "url": (asset or {}).get("browser_download_url") or "",
            "size": int((asset or {}).get("size") or 0),
            "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
            "page": data.get("html_url") or RELEASE_PAGE}


def fetch_latest_release() -> dict:
    """查詢 GitHub 上的最新版本（只下載公開的版本資訊）。"""
    try:
        data = json.loads(_get(RELEASE_API))
    except ValueError as e:
        raise OfflineError("版本資訊格式錯誤，請稍後再試。") from e
    return parse_release(data)


def download(url: str, dest: str, size: int = 0, sha256: str = "", progress=None) -> str:
    """下載檔案到 dest，並以 SHA-256（或檔案大小）確認完整；失敗時刪除不完整的檔案。"""
    import hashlib
    import os
    req = urllib.request.Request(url, headers=UA)
    ctx = ssl.create_default_context()
    h = hashlib.sha256()
    got = 0
    tmp = dest + ".part"
    try:
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r, open(tmp, "wb") as fh:
            total = size or int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        _remove(tmp)
        raise OfflineError("下載中斷，請確認網路後再試。") from e
    if (sha256 and h.hexdigest() != sha256) or (size and got != size) or got == 0:
        _remove(tmp)
        raise OfflineError("下載的檔案不完整，已刪除，請再試一次。")
    os.replace(tmp, dest)
    return dest


def _remove(path: str) -> None:
    import os
    try:
        os.remove(path)
    except OSError:
        pass


class _Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except OfflineError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"更新失敗：{e}")


def run_background(owner: QObject, fn, on_done, on_fail) -> None:
    """在背景執行網路下載，避免畫面停頓。"""
    thread = QThread(owner)
    worker = _Worker(fn)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(on_done)
    worker.failed.connect(on_fail)
    for sig in (worker.done, worker.failed):
        sig.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    owner._online_jobs = getattr(owner, "_online_jobs", []) + [(thread, worker)]
    thread.start()
