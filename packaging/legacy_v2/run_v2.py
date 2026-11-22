"""v2（PySide6 介面，已停用）的進入點：在專案根目錄執行 python packaging/legacy_v2/run_v2.py。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
