"""以每個已發行版本的程式建立舊版帳本，供 tests 檢查「舊資料在新版仍可完整開啟」。

用法（在專案根目錄）：python3 tools/make_fixtures.py [v2.4.0 ...]
不指定版本時，處理所有 git tag 中尚未產生的版本。每發行一個新版本，就要為它產生一份並提交。
產生：tests/fixtures/ledger_<版本>.db（以該版建立的帳本）與 ledger_<版本>.json（該版看到的帳務快照）。
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")

RUNNER = r"""
import json, os, sys
root, fixtures, db_path, out = sys.argv[1:5]
sys.path.insert(0, root)
sys.path.insert(0, fixtures)
from app.database import Database
from app.investments import Investments
import ledger_tools
db = Database(db_path)
inv = Investments(db)
ledger_tools.build(db, inv)
snap = ledger_tools.snapshot(db, inv)
db.close()
json.dump(snap, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("schema", snap["schema"])
"""


def make(tag: str) -> None:
    db_path = os.path.join(FIX, f"ledger_{tag}.db")
    out = os.path.join(FIX, f"ledger_{tag}.json")
    for p in (db_path, out):
        if os.path.exists(p):
            os.remove(p)
    with tempfile.TemporaryDirectory() as tmp:
        code = subprocess.run(["git", "archive", tag, "app"], cwd=ROOT, check=True, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", tmp], input=code, check=True)
        res = subprocess.run([sys.executable, "-c", RUNNER, tmp, FIX, db_path, out],
                             capture_output=True, text=True)
    if res.returncode:
        raise SystemExit(f"{tag} 建立失敗：\n{res.stderr}")
    print(f"{tag}: {os.path.basename(db_path)} ({os.path.getsize(db_path):,} bytes), {res.stdout.strip()}")


def main() -> None:
    tags = sys.argv[1:] or subprocess.run(["git", "tag", "--sort=v:refname"], cwd=ROOT, check=True,
                                          capture_output=True, text=True).stdout.split()
    for tag in tags:
        if sys.argv[1:] or not os.path.exists(os.path.join(FIX, f"ledger_{tag}.db")):
            make(tag)


if __name__ == "__main__":
    main()
