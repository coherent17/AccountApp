"""帳本執行緒與畫面可呼叫方法的包裝（api_*.py 共用）。"""

from __future__ import annotations

import functools
import json
from concurrent.futures import ThreadPoolExecutor


class DbThread:
    """SQLite 連線只能在建立它的執行緒使用；pywebview 卻會在不同的執行緒呼叫 API。
    所以帳本的開啟與所有讀寫都交給同一個專用執行緒，一次一件、依序執行（v2 的 Database 不需修改）。"""

    def __init__(self):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ledger-db")

    def run(self, fn, *args, **kwargs):
        return self._pool.submit(fn, *args, **kwargs).result()

    def close(self) -> None:
        self._pool.shutdown(wait=True)


def _plain(o):
    """集合、tuple 等轉成清單，日期轉成文字，讓結果一定能傳給畫面（JSON）。"""
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def to_json(result):
    return json.loads(json.dumps(result, default=_plain, ensure_ascii=False))


def exposed(method=None, *, db: bool = True):
    """畫面可呼叫的方法：在帳本執行緒執行（db=False 時在呼叫端執行，例如開檔案視窗），並把錯誤轉成訊息。"""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            def call():
                try:
                    return to_json(fn(self, *args, **kwargs))
                except ValueError as e:
                    if db:
                        try:
                            self._db.conn.rollback()
                        except Exception:  # noqa: BLE001
                            pass
                    return {"__error__": str(e)}
                except Exception as e:  # noqa: BLE001 — 任何錯誤都不能讓視窗卡住
                    self._log_error(fn.__name__, e)
                    return {"__error__": f"發生未預期的錯誤（{type(e).__name__}：{e}）。\n"
                                         "已記錄在資料夾的「錯誤紀錄.log」，帳本資料沒有受到影響。", "__bug__": True}
            return self._dbt.run(call) if db else call()
        return wrapper
    return deco(method) if method else deco
