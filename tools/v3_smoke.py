"""v3 exe 煙霧測試：新資料夾＋每一個舊版本帳本（tests/fixtures），同時跑 4 個，每一頁畫好就截圖。

用法（Windows 的 python，在 src 資料夾）：
    python tools/v3_smoke.py v3\\dist\\我的理財帳本.exe [輸出資料夾]
每一本都要：6 張 exe_*.png、沒有「錯誤紀錄.log」、舊結構的帳本要產生「升級前備份」。任何一本失敗時結束碼為 1。
"""

import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
CURRENT_SCHEMA_TAGS = ("v2.11.0", "v2.11.1")      # 已是目前資料結構，不需要升級前備份


def one(exe: str, out: str, name: str, src: str | None) -> tuple[str, bool, str]:
    d = os.path.join(out, name)
    data, shots = os.path.join(d, "data"), os.path.join(d, "shots")
    os.makedirs(data)
    if src:
        shutil.copy(src, os.path.join(data, "理財帳本.db"))
    env = dict(os.environ, MY_LEDGER_DATA_DIR=data, MY_LEDGER_SMOKE_DIR=shots)
    t = time.time()
    try:
        subprocess.run([exe], env=env, timeout=180, check=False)
    except subprocess.TimeoutExpired:
        return name, False, "逾時"
    n = len([f for f in os.listdir(shots) if f.startswith("exe_")]) if os.path.isdir(shots) else 0
    problems = []
    if n != 6:
        problems.append(f"截圖 {n}/6")
    if os.path.exists(os.path.join(data, "錯誤紀錄.log")):
        problems.append("有錯誤紀錄：" + open(os.path.join(data, "錯誤紀錄.log"), encoding="utf-8").read()[-300:])
    if src and not any(t in name for t in CURRENT_SCHEMA_TAGS) and \
            not any(f.startswith("理財帳本_升級前備份") for f in os.listdir(data)):
        problems.append("沒有升級前備份")
    return name, not problems, f"{time.time() - t:.0f} 秒" + ("；" + "；".join(problems) if problems else "")


def main() -> int:
    exe = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "..", "v3exesmoke"))
    shutil.rmtree(out, ignore_errors=True)
    jobs = [("fresh", None)] + [(f[:-3], os.path.join(FIX, f)) for f in sorted(os.listdir(FIX))
                                if f.startswith("ledger_v") and f.endswith(".db")]
    start = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda j: one(exe, out, *j), jobs))
    for name, ok, info in results:
        print(("OK   " if ok else "FAIL ") + name + "　" + info, flush=True)
    bad = [r for r in results if not r[1]]
    print(f"{len(results) - len(bad)}/{len(results)} 通過，共 {time.time() - start:.0f} 秒")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
