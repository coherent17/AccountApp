"""資料存取層：以 SQLite 儲存帳戶、分類、傳票、投資、定期交易與設定。

金額慣例
--------
* 每個帳戶有「帶號餘額」(signed balance)：資產為正（借餘）、負債為負（貸餘）。
* 使用者看到的負債餘額為「欠款金額」(正數)，即 -signed。
* 傳票類型：
    收入 income   : 帳戶 +amount
    支出 expense  : 帳戶 -amount
    轉帳 transfer : 轉出帳戶 -amount，轉入帳戶 +to_amount
    調整 adjust   : 帳戶 +amount（市值或餘額校正，對方科目為未實現評價損益）
    分錄 journal  : 多行借貸分錄（txn_lines），借貸以本位幣表示，帳戶行另存原幣 orig；
                    投資科目行可連結投資標的（security_id、shares），計入投資明細帳
* 所有計算都透過三個檢視表（view）取得「過帳」資料，作廢的傳票一律排除：
    v_acc_post     帳戶過帳（原幣帶號增減）
    v_cat_post     收入／支出科目過帳（本位幣，收入或費用方向為正）
    v_special_post 特殊科目過帳（本位幣，貸方為正）：評價損益、兌換損益、處分損益、淨值調整
* 匯率 rate 代表「1 單位帳戶幣別 = rate 單位本位幣」。
* 會計科目代號（code）存於 accounts／categories，可由使用者自訂；空白時依編碼原則自動編號。
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import sqlite3
from typing import Iterable

SCHEMA_VERSION = 4

ASSET_CATEGORIES = [
    "現金", "銀行存款", "定期存款", "外幣存款", "短期投資", "股票", "基金", "債券",
    "長期投資", "保險", "不動產", "應收款項", "其他資產",
]
LIABILITY_CATEGORIES = [
    "信用卡", "房屋貸款", "信用貸款", "汽車貸款", "應付款項", "其他負債",
]
DEFAULT_INCOME = [
    "薪資", "退休金", "年金", "股利", "利息", "租金收入", "獎金",
    "紅包禮金", "退款", "其他收入",
]
DEFAULT_EXPENSE = [
    "餐飲", "日常用品", "交通", "居家水電", "房租房貸", "房貸利息", "通訊網路", "醫療保健",
    "保險費", "服飾美容", "休閒娛樂", "旅遊", "教育學習", "人情交際",
    "孝親家用", "稅金規費", "健保補充保費", "捐款", "其他支出",
]

# 稅務歸類（綜合所得稅參考用）
TAX_TAGS = {
    "": "（不適用）",
    "interest": "利息所得",
    "dividend": "股利所得",
    "rental": "租賃所得",
    "pension": "退職所得",
    "salary": "薪資所得",
    "other_income": "其他所得",
    "insurance": "保險費（列舉扣除）",
    "medical": "醫藥及生育費（列舉扣除）",
    "donation": "捐贈（列舉扣除）",
    "mortgage_interest": "自用住宅購屋借款利息",
    "house_rent": "房屋租金支出",
    "nhi_supplement": "二代健保補充保費",
}
INCOME_TAX_TAGS = ["", "interest", "dividend", "rental", "pension", "salary", "other_income"]
EXPENSE_TAX_TAGS = ["", "insurance", "medical", "donation", "mortgage_interest", "house_rent",
                    "nhi_supplement"]
DEFAULT_TAX_TAGS = {
    ("income", "利息"): "interest", ("income", "股利"): "dividend",
    ("income", "租金收入"): "rental", ("income", "退休金"): "pension",
    ("income", "年金"): "pension", ("income", "薪資"): "salary", ("income", "獎金"): "salary",
    ("expense", "保險費"): "insurance", ("expense", "醫療保健"): "medical",
    ("expense", "捐款"): "donation", ("expense", "房貸利息"): "mortgage_interest",
    ("expense", "健保補充保費"): "nhi_supplement",
}

CURRENCIES = {
    "TWD": ("新台幣", "NT$"),
    "USD": ("美元", "US$"),
    "HKD": ("港幣", "HK$"),
    "CNY": ("人民幣", "CN¥"),
    "JPY": ("日圓", "JP¥"),
    "EUR": ("歐元", "€"),
    "GBP": ("英鎊", "£"),
    "AUD": ("澳幣", "A$"),
    "CAD": ("加幣", "C$"),
    "SGD": ("新加坡幣", "S$"),
    "CHF": ("瑞士法郎", "CHF "),
    "NZD": ("紐西蘭幣", "NZ$"),
}
ZERO_DECIMAL_CURRENCIES = {"TWD", "JPY"}

# 流動性分類（個人資產負債表）
CURRENT_ASSET_CATEGORIES = {"現金", "銀行存款", "定期存款", "外幣存款", "短期投資", "股票", "基金", "債券",
                            "應收款項"}
CASH_EQUIVALENT_CATEGORIES = {"現金", "銀行存款", "定期存款", "外幣存款"}
CURRENT_LIABILITY_CATEGORIES = {"信用卡", "應付款項"}
INVESTMENT_CATEGORIES = {"短期投資", "長期投資", "股票", "基金", "債券"}

ADJUST_ACCOUNT = "未實現評價損益"
FX_ACCOUNT = "兌換損益"
REALIZED_ACCOUNT = "處分投資損益"
EQUITY_ACCOUNT = "期初淨值（業主權益）"
EQUITY_ADJ_ACCOUNT = "淨值調整"

SPECIALS = {
    "adjust": ("7101", ADJUST_ACCOUNT, "業外損益"),
    "fx": ("7201", FX_ACCOUNT, "業外損益"),
    "realized": ("7301", REALIZED_ACCOUNT, "業外損益"),
    "equity": ("3102", EQUITY_ADJ_ACCOUNT, "權益"),
}
EQUITY_CODE = "3101"

# 科目代號首碼：資產 1、負債 2、收入 4（業外 7）、費用 5／6（業外 7）
CODE_FIRST_DIGITS = {"asset": "1", "liability": "2", "income": "47", "expense": "567"}
NATURE_LABELS = {"asset": "資產", "liability": "負債", "income": "收入", "expense": "費用"}

TYPE_LABELS = {
    "income": "收入",
    "expense": "支出",
    "transfer": "轉帳",
    "adjust": "餘額調整",
    "journal": "分錄",
}

DEFAULT_SETTINGS = {
    "owner_name": "",
    "base_currency": "TWD",
    "font_scale": "large",
    "first_run_done": "0",
    "last_account_id": "",
    "closed_until": "",
    "animations": "1",
    "sample_data": "0",
    "birth_year": "",
    "allocation_targets": "",
    "retire_params": "",
    "online_updates": "0",
    "journal_templates": "",
}

_TABLES = """
CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    kind            TEXT    NOT NULL CHECK (kind IN ('asset', 'liability')),
    category        TEXT    NOT NULL,
    currency        TEXT    NOT NULL DEFAULT 'TWD',
    rate            REAL    NOT NULL DEFAULT 1,
    opening_balance REAL    NOT NULL DEFAULT 0,
    opening_date    TEXT    NOT NULL,
    note            TEXT    NOT NULL DEFAULT '',
    archived        INTEGER NOT NULL DEFAULT 0,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    maturity_date   TEXT    NOT NULL DEFAULT '',
    interest_rate   REAL    NOT NULL DEFAULT 0,
    code            TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    kind       TEXT    NOT NULL CHECK (kind IN ('income', 'expense')),
    budget     REAL    NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    archived   INTEGER NOT NULL DEFAULT 0,
    tax_tag    TEXT    NOT NULL DEFAULT '',
    code       TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT    NOT NULL,
    type          TEXT    NOT NULL CHECK (type IN ('income', 'expense', 'transfer', 'adjust', 'journal')),
    account_id    INTEGER REFERENCES accounts(id),
    to_account_id INTEGER REFERENCES accounts(id),
    amount        REAL    NOT NULL,
    to_amount     REAL,
    category_id   INTEGER REFERENCES categories(id),
    note          TEXT    NOT NULL DEFAULT '',
    void          INTEGER NOT NULL DEFAULT 0,
    void_reason   TEXT    NOT NULL DEFAULT '',
    source        TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS txn_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id      INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL DEFAULT 0,
    account_id  INTEGER REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),
    special     TEXT,
    debit       REAL    NOT NULL DEFAULT 0,
    credit      REAL    NOT NULL DEFAULT 0,
    orig        REAL,
    memo        TEXT    NOT NULL DEFAULT '',
    security_id INTEGER REFERENCES securities(id),
    shares      REAL    NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT    NOT NULL,
    action  TEXT    NOT NULL,
    txn_id  INTEGER,
    voucher TEXT    NOT NULL DEFAULT '',
    summary TEXT    NOT NULL DEFAULT '',
    detail  TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recurring (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL,
    data       TEXT    NOT NULL,
    freq       TEXT    NOT NULL CHECK (freq IN ('monthly', 'quarterly', 'yearly')),
    day        INTEGER NOT NULL DEFAULT 1,
    start_date TEXT    NOT NULL,
    end_date   TEXT    NOT NULL DEFAULT '',
    last_date  TEXT    NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS reconciliations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id        INTEGER NOT NULL REFERENCES accounts(id),
    statement_date    TEXT    NOT NULL,
    statement_balance REAL    NOT NULL,
    created_at        TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS recon_items (
    recon_id   INTEGER NOT NULL REFERENCES reconciliations(id) ON DELETE CASCADE,
    txn_id     INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    PRIMARY KEY (txn_id, account_id)
);
CREATE TABLE IF NOT EXISTS attachments (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_id   INTEGER NOT NULL,
    name     TEXT    NOT NULL,
    path     TEXT    NOT NULL,
    added_at TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS securities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    code       TEXT    NOT NULL DEFAULT '',
    name       TEXT    NOT NULL,
    note       TEXT    NOT NULL DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sec_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    security_id     INTEGER NOT NULL REFERENCES securities(id),
    date            TEXT    NOT NULL,
    kind            TEXT    NOT NULL CHECK (kind IN ('buy', 'sell', 'cash_div', 'stock_div', 'price')),
    shares          REAL    NOT NULL DEFAULT 0,
    price           REAL    NOT NULL DEFAULT 0,
    fee             REAL    NOT NULL DEFAULT 0,
    tax             REAL    NOT NULL DEFAULT 0,
    amount          REAL    NOT NULL DEFAULT 0,
    nhi             REAL    NOT NULL DEFAULT 0,
    cash_account_id INTEGER REFERENCES accounts(id),
    note            TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_txn_to_account ON transactions(to_account_id);
CREATE INDEX IF NOT EXISTS idx_txn_source ON transactions(source);
CREATE INDEX IF NOT EXISTS idx_lines_txn ON txn_lines(txn_id);
CREATE INDEX IF NOT EXISTS idx_lines_account ON txn_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_lines_security ON txn_lines(security_id);
CREATE INDEX IF NOT EXISTS idx_sec_events ON sec_events(security_id, date);
"""

_VIEWS = """
DROP VIEW IF EXISTS v_acc_post;
CREATE VIEW v_acc_post AS
    SELECT t.id AS txn_id, t.date AS date, t.account_id AS account_id,
           CASE t.type WHEN 'income' THEN t.amount WHEN 'adjust' THEN t.amount
                       ELSE -t.amount END AS delta
      FROM transactions t
     WHERE t.void = 0 AND t.type IN ('income', 'expense', 'transfer', 'adjust')
    UNION ALL
    SELECT t.id, t.date, t.to_account_id, t.to_amount
      FROM transactions t WHERE t.void = 0 AND t.type = 'transfer'
    UNION ALL
    SELECT t.id, t.date, l.account_id, l.orig
      FROM txn_lines l JOIN transactions t ON t.id = l.txn_id
     WHERE t.void = 0 AND t.type = 'journal' AND l.account_id IS NOT NULL;

DROP VIEW IF EXISTS v_cat_post;
CREATE VIEW v_cat_post AS
    SELECT t.id AS txn_id, t.date AS date, t.category_id AS category_id, t.type AS kind,
           t.amount * a.rate AS base
      FROM transactions t JOIN accounts a ON a.id = t.account_id
     WHERE t.void = 0 AND t.type IN ('income', 'expense')
    UNION ALL
    SELECT t.id, t.date, l.category_id, c.kind,
           CASE c.kind WHEN 'expense' THEN l.debit - l.credit ELSE l.credit - l.debit END
      FROM txn_lines l
      JOIN transactions t ON t.id = l.txn_id
      JOIN categories c ON c.id = l.category_id
     WHERE t.void = 0 AND t.type = 'journal';

DROP VIEW IF EXISTS v_special_post;
CREATE VIEW v_special_post AS
    SELECT t.id AS txn_id, t.date AS date, 'adjust' AS special, t.amount * a.rate AS gain
      FROM transactions t JOIN accounts a ON a.id = t.account_id
     WHERE t.void = 0 AND t.type = 'adjust'
    UNION ALL
    SELECT t.id, t.date, 'fx', t.to_amount * b.rate - t.amount * a.rate
      FROM transactions t
      JOIN accounts a ON a.id = t.account_id
      JOIN accounts b ON b.id = t.to_account_id
     WHERE t.void = 0 AND t.type = 'transfer'
    UNION ALL
    SELECT t.id, t.date, l.special, l.credit - l.debit
      FROM txn_lines l JOIN transactions t ON t.id = l.txn_id
     WHERE t.void = 0 AND t.type = 'journal' AND l.special IS NOT NULL
    UNION ALL
    SELECT t.id, t.date, 'fx', SUM(l.orig * a.rate - (l.debit - l.credit))
      FROM txn_lines l
      JOIN transactions t ON t.id = l.txn_id
      JOIN accounts a ON a.id = l.account_id
     WHERE t.void = 0 AND t.type = 'journal'
     GROUP BY t.id
    HAVING ABS(SUM(l.orig * a.rate - (l.debit - l.credit))) > 0.004;
"""


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return _dt.date.today().isoformat()


def money_round(value: float) -> float:
    return round(float(value) + 0.0, 2)


def fmt_shares(shares: float) -> str:
    """股數顯示：整數不顯示小數，基金單位數最多四位小數。"""
    if abs(shares - round(shares)) < 1e-9:
        return f"{shares:,.0f}"
    return f"{shares:,.4f}".rstrip("0").rstrip(".")


def voucher_no(txn_id: int | None) -> str:
    return f"V{txn_id:06d}" if txn_id else ""


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn: sqlite3.Connection | None = None
        self._restating = False
        self._open()

    # ================================================================== 連線與升級
    def _open(self) -> None:
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = OFF")
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        has_tables = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transactions'").fetchone()
        if has_tables and version < SCHEMA_VERSION:
            self._backup_before_upgrade(version)
        if has_tables and version < 2:
            self._migrate_v1_to_v2()
        if has_tables and version < 3:
            self._migrate_v2_to_v3()
        self.conn.executescript(_TABLES)
        self.conn.executescript(_VIEWS)
        # 投資分錄重編完成才標記為第 4 版，中途失敗時下次開啟會重做
        restate = bool(has_tables) and version < 4
        self.conn.execute(f"PRAGMA user_version = {3 if restate else SCHEMA_VERSION}")
        for key, value in DEFAULT_SETTINGS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))
        if not self.conn.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
            self._insert_default_categories()
        self._ensure_codes()
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")
        if restate:
            self._migrate_v3_to_v4()
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.conn.commit()

    def _backup_before_upgrade(self, version: int) -> None:
        """升級資料庫結構前，先在同一資料夾留一份原始檔（只做一次）。"""
        root, ext = os.path.splitext(self.path)
        dest = f"{root}_升級前備份_v{version}{ext or '.db'}"
        if os.path.exists(dest):
            return
        try:
            bak = sqlite3.connect(dest)
            with bak:
                self.conn.backup(bak)
            bak.close()
        except (OSError, sqlite3.Error):
            pass

    def _migrate_v3_to_v4(self) -> None:
        """買賣不再自動評價：依新規則重編所有投資系統分錄（含已結帳期間，以維持帳與明細一致）。
        重編前的資料已留在升級前備份；銀行對帳勾選與憑證附件會接回重編後的傳票。"""
        from .investments import Investments
        inv = Investments(self)
        self._restating = True
        try:
            for sec in self._q("SELECT id, name FROM securities"):
                src = f"inv:{sec['id']}"
                old = self._q("SELECT id, date, note FROM transactions WHERE source = ? ORDER BY id",
                              (src,))
                if not old:
                    continue
                ids = ",".join(str(t["id"]) for t in old)
                recon = self._q(f"SELECT * FROM recon_items WHERE txn_id IN ({ids})")
                try:
                    inv.rebuild(sec["id"], min(t["date"] for t in old))
                except ValueError as e:
                    self._log("升級失敗", None, f"{sec['name']} 投資分錄重編失敗：{e}")
                    continue
                new: dict[tuple, list[int]] = {}
                for t in self._q("SELECT id, date, note FROM transactions WHERE source = ?"
                                 " ORDER BY id", (src,)):
                    new.setdefault((t["date"], t["note"]), []).append(t["id"])
                for t in old:
                    same = new.get((t["date"], t["note"]))
                    if not same:
                        continue
                    nid = same.pop(0)
                    self.conn.execute("UPDATE attachments SET txn_id = ? WHERE txn_id = ?", (nid, t["id"]))
                    for r in recon:
                        if r["txn_id"] == t["id"] and self._q1(
                                "SELECT 1 FROM txn_lines WHERE txn_id = ? AND account_id = ?",
                                (nid, r["account_id"])):
                            self.conn.execute(
                                "INSERT OR IGNORE INTO recon_items(recon_id, txn_id, account_id)"
                                " VALUES (?, ?, ?)", (r["recon_id"], nid, r["account_id"]))
            self._log("系統升級", None, "投資買賣不再自動評價，已重編投資系統分錄；只保留手動輸入市價的評價")
            self.conn.commit()
        finally:
            self._restating = False

    def _migrate_v1_to_v2(self) -> None:
        """第 1 版資料庫升級：新增欄位、重建交易表（放寬類型限制）。"""
        c = self.conn
        cols = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
        if "maturity_date" not in cols:
            c.execute("ALTER TABLE accounts ADD COLUMN maturity_date TEXT NOT NULL DEFAULT ''")
        if "interest_rate" not in cols:
            c.execute("ALTER TABLE accounts ADD COLUMN interest_rate REAL NOT NULL DEFAULT 0")
        cols = {r[1] for r in c.execute("PRAGMA table_info(categories)")}
        if "tax_tag" not in cols:
            c.execute("ALTER TABLE categories ADD COLUMN tax_tag TEXT NOT NULL DEFAULT ''")
        c.executescript("""
            DROP VIEW IF EXISTS v_acc_post; DROP VIEW IF EXISTS v_cat_post;
            DROP VIEW IF EXISTS v_special_post;
            ALTER TABLE transactions RENAME TO transactions_v1;
        """)
        c.executescript(_TABLES)
        c.execute("""
            INSERT INTO transactions(id, date, type, account_id, to_account_id, amount, to_amount,
                                     category_id, note, created_at, updated_at)
            SELECT id, date, type, account_id, to_account_id, amount, to_amount, category_id,
                   note, created_at, updated_at FROM transactions_v1
        """)
        c.execute("DROP TABLE transactions_v1")
        existing = {(r["kind"], r["name"]) for r in c.execute("SELECT kind, name FROM categories")}
        for kind, names in (("income", DEFAULT_INCOME), ("expense", DEFAULT_EXPENSE)):
            for name in names:
                if (kind, name) not in existing:
                    c.execute("INSERT INTO categories(name, kind, sort_order) VALUES (?, ?, 999)",
                              (name, kind))
        for (kind, name), tag in DEFAULT_TAX_TAGS.items():
            c.execute("UPDATE categories SET tax_tag = ? WHERE kind = ? AND name = ? AND tax_tag = ''",
                      (tag, kind, name))
        c.execute("PRAGMA user_version = 2")
        c.commit()

    def _migrate_v2_to_v3(self) -> None:
        """第 2 版升級：會計科目代號、分錄行連結投資標的。舊科目沿用原自動代號。"""
        c = self.conn
        for table, col, ddl in (("accounts", "code", "TEXT NOT NULL DEFAULT ''"),
                                ("categories", "code", "TEXT NOT NULL DEFAULT ''"),
                                ("txn_lines", "security_id", "INTEGER REFERENCES securities(id)"),
                                ("txn_lines", "shares", "REAL NOT NULL DEFAULT 0")):
            cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if cols and col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        c.commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _insert_default_categories(self) -> None:
        for kind, names in (("income", DEFAULT_INCOME), ("expense", DEFAULT_EXPENSE)):
            for i, name in enumerate(names):
                self.conn.execute(
                    "INSERT INTO categories(name, kind, sort_order, tax_tag) VALUES (?, ?, ?, ?)",
                    (name, kind, i, DEFAULT_TAX_TAGS.get((kind, name), "")))

    def _q(self, sql: str, params: Iterable = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def _q1(self, sql: str, params: Iterable = ()) -> dict | None:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    # ================================================================== 設定
    def get_setting(self, key: str, default: str = "") -> str:
        row = self._q1("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def get_json(self, key: str, default=None):
        raw = self.get_setting(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def set_json(self, key: str, value) -> None:
        self.set_setting(key, json.dumps(value, ensure_ascii=False))

    @property
    def base_currency(self) -> str:
        return self.get_setting("base_currency", "TWD")

    @property
    def closed_until(self) -> str:
        return self.get_setting("closed_until", "")

    def _check_open(self, date: str) -> None:
        c = self.closed_until
        if c and date <= c and not self._restating:
            raise ValueError(f"{date.replace('-', '/')} 屬於已結帳期間（結帳至 {c.replace('-', '/')}），"
                             "無法新增、修改或作廢。如需更正，請使用「迴轉」在未結帳期間產生反向傳票，"
                             "或先到「設定」解除結帳。")

    # ================================================================== 帳戶
    def list_accounts(self, include_archived: bool = False) -> list[dict]:
        sql = "SELECT * FROM accounts"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY kind, sort_order, id"
        return self._q(sql)

    def get_account(self, account_id: int) -> dict | None:
        return self._q1("SELECT * FROM accounts WHERE id = ?", (account_id,))

    def add_account(self, name, kind, category, currency="TWD", rate=1.0,
                    opening_balance=0.0, opening_date=None, note="", maturity_date="",
                    interest_rate=0.0, code="") -> int:
        if not (name or "").strip():
            raise ValueError("請輸入科目名稱")
        if currency == self.base_currency:
            rate = 1.0
        code = self.validate_code(code, kind) if (code or "").strip() else \
            self.next_code(self.code_prefix(kind, category))
        order = self._q1("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM accounts")["n"]
        cur = self.conn.execute(
            "INSERT INTO accounts(name, kind, category, currency, rate, opening_balance,"
            " opening_date, note, sort_order, maturity_date, interest_rate, code)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name.strip(), kind, category, currency, float(rate),
             money_round(opening_balance), opening_date or _today(), note.strip(), order,
             maturity_date or "", float(interest_rate or 0), code),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_account(self, account_id: int, **fields) -> None:
        allowed = {"name", "kind", "category", "currency", "rate", "opening_balance",
                   "opening_date", "note", "archived", "sort_order", "maturity_date",
                   "interest_rate", "code"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if "code" in fields:
            kind = fields.get("kind") or self.get_account(account_id)["kind"]
            fields["code"] = self.validate_code(fields["code"], kind, ("account", account_id))
        if "currency" in fields and fields["currency"] == self.base_currency:
            fields["rate"] = 1.0
        if "opening_balance" in fields:
            fields["opening_balance"] = money_round(fields["opening_balance"])
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))
        self.conn.commit()

    def account_txn_count(self, account_id: int, include_void: bool = True) -> int:
        void = "" if include_void else " AND t.void = 0"
        n = self._q1(
            f"SELECT COUNT(*) AS n FROM transactions t WHERE (t.account_id = ? OR t.to_account_id = ?"
            f" OR EXISTS (SELECT 1 FROM txn_lines l WHERE l.txn_id = t.id AND l.account_id = ?)){void}",
            (account_id, account_id, account_id))["n"]
        n += self._q1("SELECT COUNT(*) AS n FROM securities WHERE account_id = ?", (account_id,))["n"]
        return n

    def delete_account(self, account_id: int) -> None:
        if self.account_txn_count(account_id):
            raise ValueError("此帳戶仍有交易紀錄或投資標的，無法刪除。建議改用「封存」。")
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        self.conn.commit()

    def signed_balances(self, as_of: str | None = None) -> dict[int, float]:
        """回傳 {帳戶 id: 帶號餘額（原幣）}，as_of 為 ISO 日期（含當日）。"""
        as_of = as_of or "9999-12-31"
        result: dict[int, float] = {}
        for acc in self._q("SELECT id, kind, opening_balance, opening_date FROM accounts"):
            if acc["opening_date"] <= as_of:
                ob = acc["opening_balance"]
                result[acc["id"]] = ob if acc["kind"] == "asset" else -ob
            else:
                result[acc["id"]] = 0.0
        for r in self._q("SELECT account_id AS id, SUM(delta) AS d FROM v_acc_post"
                         " WHERE date <= ? GROUP BY account_id", (as_of,)):
            if r["id"] in result:
                result[r["id"]] += r["d"] or 0.0
        return {k: money_round(v) for k, v in result.items()}

    def account_summaries(self, as_of: str | None = None, include_archived=False) -> list[dict]:
        """帳戶清單加上餘額資訊。balance 為使用者看到的餘額（負債為欠款正數）。"""
        bal = self.signed_balances(as_of)
        out = []
        for acc in self.list_accounts(include_archived=include_archived):
            signed = bal.get(acc["id"], 0.0)
            acc = dict(acc)
            acc["signed"] = signed
            acc["balance"] = signed if acc["kind"] == "asset" else -signed
            acc["base_value"] = money_round(signed * acc["rate"])
            out.append(acc)
        return out

    def net_worth(self, as_of: str | None = None) -> dict:
        assets = liabilities = 0.0
        for acc in self.account_summaries(as_of, include_archived=True):
            if acc["kind"] == "asset":
                assets += acc["base_value"]
            else:
                liabilities += -acc["base_value"]
        return {"assets": money_round(assets), "liabilities": money_round(liabilities),
                "net": money_round(assets - liabilities)}

    def upcoming_maturities(self, days: int = 60, as_of: str | None = None) -> list[dict]:
        today = _dt.date.fromisoformat(as_of) if as_of else _dt.date.today()
        limit = (today + _dt.timedelta(days=days)).isoformat()
        out = []
        for acc in self.account_summaries():
            m = acc["maturity_date"]
            if m and today.isoformat() <= m <= limit:
                d = (_dt.date.fromisoformat(m) - today).days
                acc["days_left"] = d
                acc["est_interest"] = money_round(
                    acc["balance"] * (acc["interest_rate"] or 0) / 100 * max(d, 0) / 365)
                out.append(acc)
            elif m and m < today.isoformat() and (today - _dt.date.fromisoformat(m)).days <= 30:
                acc["days_left"] = (_dt.date.fromisoformat(m) - today).days
                acc["est_interest"] = 0.0
                out.append(acc)
        return sorted(out, key=lambda a: a["maturity_date"])

    # ================================================================== 分類
    def list_categories(self, kind: str | None = None, include_archived=False) -> list[dict]:
        sql = "SELECT * FROM categories WHERE 1 = 1"
        params: list = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if not include_archived:
            sql += " AND archived = 0"
        sql += " ORDER BY kind DESC, sort_order, id"
        return self._q(sql, params)

    def get_category(self, category_id: int) -> dict | None:
        return self._q1("SELECT * FROM categories WHERE id = ?", (category_id,))

    def find_category(self, kind: str, name: str) -> dict | None:
        return self._q1("SELECT * FROM categories WHERE kind = ? AND name = ?", (kind, name))

    def add_category(self, name: str, kind: str, budget: float = 0.0, tax_tag: str = "",
                     code: str = "") -> int:
        if not (name or "").strip():
            raise ValueError("請輸入科目名稱")
        if self.find_category(kind, name.strip()):
            raise ValueError(f"已有同名的{NATURE_LABELS[kind]}科目「{name.strip()}」")
        code = self.validate_code(code, kind) if (code or "").strip() else \
            self.next_code(self.code_prefix(kind))
        order = self._q1(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM categories WHERE kind = ?", (kind,)
        )["n"]
        cur = self.conn.execute(
            "INSERT INTO categories(name, kind, budget, sort_order, tax_tag, code)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name.strip(), kind, money_round(budget), order, tax_tag, code),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_category(self, category_id: int, **fields) -> None:
        allowed = {"name", "budget", "sort_order", "archived", "tax_tag", "code"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if "code" in fields:
            kind = self.get_category(category_id)["kind"]
            fields["code"] = self.validate_code(fields["code"], kind, ("category", category_id))
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(f"UPDATE categories SET {cols} WHERE id = ?", (*fields.values(), category_id))
        self.conn.commit()

    def category_txn_count(self, category_id: int) -> int:
        return self._q1(
            "SELECT (SELECT COUNT(*) FROM transactions WHERE category_id = ?)"
            " + (SELECT COUNT(*) FROM txn_lines WHERE category_id = ?) AS n",
            (category_id, category_id))["n"]

    def delete_category(self, category_id: int) -> None:
        if self.category_txn_count(category_id):
            raise ValueError("此分類已被交易使用，無法刪除。建議改用「隱藏」。")
        self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        self.conn.commit()

    def move_category(self, category_id: int, direction: int) -> None:
        cat = self.get_category(category_id)
        if not cat:
            return
        ids = [c["id"] for c in self.list_categories(cat["kind"], include_archived=True)]
        i = ids.index(category_id)
        j = i + direction
        if not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        for order, cid in enumerate(ids):
            self.conn.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (order, cid))
        self.conn.commit()

    # ================================================================== 修改紀錄
    def _log(self, action: str, txn_id: int | None, summary: str, detail=None) -> None:
        self.conn.execute(
            "INSERT INTO audit_log(at, action, txn_id, voucher, summary, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), action, txn_id, voucher_no(txn_id), summary,
             json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else ""))

    def list_audit(self, txn_id: int | None = None, limit: int = 500) -> list[dict]:
        if txn_id:
            return self._q("SELECT * FROM audit_log WHERE txn_id = ? ORDER BY id DESC", (txn_id,))
        return self._q("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    def describe(self, txn_id: int) -> str:
        t = self.get_transaction(txn_id)
        if not t:
            return ""
        lines = self.txn_lines_of(t)
        parts = [f"{TYPE_LABELS[t['type']]}　{t['date'].replace('-', '/')}"]
        for ln in lines:
            side = f"借 {ln['debit']:,.2f}" if ln["debit"] else f"貸 {ln['credit']:,.2f}"
            link = ""
            if ln.get("security_id"):
                sec = self._q1("SELECT code, name FROM securities WHERE id = ?", (ln["security_id"],))
                if sec:
                    link = f"（{sec['code']} {sec['name']} {fmt_shares(ln['shares'])} 股）".replace("（ ", "（")
            parts.append(f"{ln['name']}{link} {side}")
        if t["note"]:
            parts.append(f"摘要：{t['note']}")
        return "；".join(parts)

    # ================================================================== 傳票（簡式）
    def _validate_txn(self, t: dict) -> dict:
        ttype = t["type"]
        if ttype not in ("income", "expense", "transfer", "adjust"):
            raise ValueError("交易類型錯誤")
        amount = money_round(t.get("amount") or 0)
        if ttype != "adjust" and amount <= 0:
            raise ValueError("金額必須大於 0")
        if ttype == "adjust" and amount == 0:
            raise ValueError("調整金額不可為 0")
        if not t.get("account_id") or not self.get_account(t["account_id"]):
            raise ValueError("請選擇帳戶")
        to_account_id = t.get("to_account_id")
        to_amount = t.get("to_amount")
        category_id = t.get("category_id")
        if ttype == "transfer":
            if not to_account_id or not self.get_account(to_account_id):
                raise ValueError("請選擇轉入帳戶")
            if to_account_id == t["account_id"]:
                raise ValueError("轉出與轉入帳戶不可相同")
            to_amount = money_round(to_amount if to_amount else amount)
            if to_amount <= 0:
                raise ValueError("轉入金額必須大於 0")
            category_id = None
        else:
            to_account_id = None
            to_amount = None
        if ttype in ("income", "expense"):
            cat = self.get_category(category_id) if category_id else None
            if not cat or cat["kind"] != ttype:
                raise ValueError("請選擇分類")
        if ttype == "adjust":
            category_id = None
        date = t.get("date") or _today()
        _dt.date.fromisoformat(date)
        return {
            "date": date, "type": ttype, "account_id": t["account_id"],
            "to_account_id": to_account_id, "amount": amount, "to_amount": to_amount,
            "category_id": category_id, "note": (t.get("note") or "").strip(),
        }

    def add_transaction(self, source: str = "", log: str = "新增", **t) -> int:
        v = self._validate_txn(t)
        self._check_open(v["date"])
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO transactions(date, type, account_id, to_account_id, amount, to_amount,"
            " category_id, note, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (v["date"], v["type"], v["account_id"], v["to_account_id"], v["amount"],
             v["to_amount"], v["category_id"], v["note"], source, now, now),
        )
        tid = cur.lastrowid
        if log:
            self._log(log, tid, self.describe(tid))
        self.conn.commit()
        return tid

    def update_transaction(self, txn_id: int, **t) -> None:
        old = self.get_transaction(txn_id)
        if not old:
            raise ValueError("找不到這筆傳票")
        if old["type"] == "journal":
            raise ValueError("分錄請使用分錄視窗修改")
        self._guard_editable(old)
        v = self._validate_txn(t)
        self._check_open(v["date"])
        before = self.describe(txn_id)
        self.conn.execute(
            "UPDATE transactions SET date = ?, type = ?, account_id = ?, to_account_id = ?,"
            " amount = ?, to_amount = ?, category_id = ?, note = ?, updated_at = ? WHERE id = ?",
            (v["date"], v["type"], v["account_id"], v["to_account_id"], v["amount"],
             v["to_amount"], v["category_id"], v["note"], _now(), txn_id),
        )
        self._log("修改", txn_id, self.describe(txn_id), {"修改前": before})
        self.conn.commit()

    def _guard_editable(self, t: dict) -> None:
        self._check_open(t["date"])
        if t["void"]:
            raise ValueError("此傳票已作廢，如需使用請先「取消作廢」。")
        if t["source"].startswith("inv:"):
            raise ValueError("此傳票由「投資管理」自動產生，請到投資管理修改交易。")

    # ================================================================== 傳票（分錄）
    def _normalize_lines(self, lines: list[dict]) -> list[dict]:
        out = []
        for ln in lines:
            debit = money_round(ln.get("debit") or 0)
            credit = money_round(ln.get("credit") or 0)
            if not debit and not credit:
                continue
            if debit < 0 or credit < 0:
                raise ValueError("借方、貸方金額不可為負數")
            if debit and credit:
                raise ValueError("同一行不可同時填借方與貸方")
            targets = [k for k in ("account_id", "category_id", "special") if ln.get(k)]
            if len(targets) != 1:
                raise ValueError("每一行都要選擇一個會計科目")
            item = {"account_id": ln.get("account_id"), "category_id": ln.get("category_id"),
                    "special": ln.get("special"), "debit": debit, "credit": credit,
                    "memo": (ln.get("memo") or "").strip(), "orig": None,
                    "security_id": ln.get("security_id") or None, "shares": 0.0}
            if item["security_id"]:
                sec = self._q1("SELECT * FROM securities WHERE id = ?", (item["security_id"],))
                if not sec or sec["account_id"] != item["account_id"]:
                    raise ValueError("投資標的與會計科目不符，請重新選擇標的")
                shares = float(ln.get("shares") or 0)
                if shares <= 0:
                    raise ValueError(f"請輸入「{sec['name']}」的股數（單位數）")
                item["shares"] = round(shares, 4)
            if item["account_id"]:
                acc = self.get_account(item["account_id"])
                if not acc:
                    raise ValueError("科目不存在")
                orig = ln.get("orig")
                if orig is None:
                    orig = (debit - credit) / (acc["rate"] or 1)
                item["orig"] = round(orig, 4)
            elif item["category_id"]:
                if not self.get_category(item["category_id"]):
                    raise ValueError("科目不存在")
            elif item["special"] not in SPECIALS:
                raise ValueError("科目不存在")
            out.append(item)
        if len(out) < 2:
            raise ValueError("分錄至少需要兩行（借方與貸方）")
        d = round(sum(x["debit"] for x in out), 2)
        c = round(sum(x["credit"] for x in out), 2)
        if abs(d - c) > 0.004:
            raise ValueError(f"借貸不平衡：借方合計 {d:,.2f}，貸方合計 {c:,.2f}，差額 {d - c:,.2f}")
        if not any(x["account_id"] for x in out):
            raise ValueError("分錄至少要包含一個帳戶（資產或負債科目）")
        return out

    def add_journal(self, date: str, note: str, lines: list[dict], source: str = "",
                    log: str = "新增") -> int:
        _dt.date.fromisoformat(date)
        self._check_open(date)
        items = self._normalize_lines(lines)
        total = round(sum(x["debit"] for x in items), 2)
        first_acc = next(x["account_id"] for x in items if x["account_id"])
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO transactions(date, type, account_id, amount, note, source, created_at,"
            " updated_at) VALUES (?, 'journal', ?, ?, ?, ?, ?, ?)",
            (date, first_acc, total, (note or "").strip(), source, now, now))
        tid = cur.lastrowid
        self._insert_lines(tid, items)
        if log:
            self._log(log, tid, self.describe(tid))
        self._sync_securities({x["security_id"] for x in items if x["security_id"]}, date)
        self.conn.commit()
        return tid

    def _insert_lines(self, tid: int, items: list[dict]) -> None:
        for seq, x in enumerate(items):
            self.conn.execute(
                "INSERT INTO txn_lines(txn_id, seq, account_id, category_id, special, debit, credit,"
                " orig, memo, security_id, shares) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tid, seq, x["account_id"], x["category_id"], x["special"], x["debit"], x["credit"],
                 x["orig"], x["memo"], x.get("security_id"), x.get("shares") or 0))

    def linked_securities(self, txn_id: int) -> set[int]:
        return {r["security_id"] for r in self._q(
            "SELECT DISTINCT security_id FROM txn_lines WHERE txn_id = ? AND security_id IS NOT NULL",
            (txn_id,))}

    def _sync_securities(self, sids: set[int], from_date: str) -> None:
        """分錄連結投資標的時，重算持股並自該日起重新產生系統分錄。
        持股計算失敗（例如賣出超過持股）時復原本次變更並回報錯誤。"""
        if not sids:
            return
        from .investments import Investments
        inv = Investments(self)
        try:
            for sid in sids:
                inv.replay(sid)
        except ValueError:
            self.conn.rollback()
            raise
        for sid in sids:
            inv.rebuild(sid, from_date)

    def update_journal(self, txn_id: int, date: str, note: str, lines: list[dict]) -> None:
        old = self.get_transaction(txn_id)
        if not old or old["type"] != "journal":
            raise ValueError("找不到這筆分錄")
        self._guard_editable(old)
        self._check_open(date)
        items = self._normalize_lines(lines)
        before = self.describe(txn_id)
        total = round(sum(x["debit"] for x in items), 2)
        first_acc = next(x["account_id"] for x in items if x["account_id"])
        self.conn.execute(
            "UPDATE transactions SET date = ?, account_id = ?, amount = ?, note = ?, updated_at = ?"
            " WHERE id = ?", (date, first_acc, total, (note or "").strip(), _now(), txn_id))
        sids = self.linked_securities(txn_id) | {x["security_id"] for x in items if x["security_id"]}
        self.conn.execute("DELETE FROM txn_lines WHERE txn_id = ?", (txn_id,))
        self._insert_lines(txn_id, items)
        self._log("修改", txn_id, self.describe(txn_id), {"修改前": before})
        self._sync_securities(sids, min(date, old["date"]))
        self.conn.commit()

    def get_lines(self, txn_id: int) -> list[dict]:
        return self._q("SELECT * FROM txn_lines WHERE txn_id = ? ORDER BY seq, id", (txn_id,))

    # ================================================================== 作廢、迴轉、刪除
    def void_transactions(self, ids: Iterable[int], reason: str = "") -> None:
        ids = list(ids)
        for i in ids:
            t = self.get_transaction(i)
            if not t:
                continue
            if t["source"].startswith("inv:"):
                raise ValueError(f"{voucher_no(i)} 由投資管理自動產生，請到「投資管理」刪除該筆交易。")
            self._check_open(t["date"])
        sids: set[int] = set()
        first = None
        for i in ids:
            t = self.get_transaction(i)
            if t and not t["void"]:
                self.conn.execute("UPDATE transactions SET void = 1, void_reason = ?, updated_at = ?"
                                  " WHERE id = ?", (reason.strip(), _now(), i))
                self.conn.execute("DELETE FROM recon_items WHERE txn_id = ?", (i,))
                self._log("作廢", i, self.describe(i), {"原因": reason})
                linked = self.linked_securities(i)
                if linked:
                    sids |= linked
                    first = min(first or t["date"], t["date"])
        try:
            self._sync_securities(sids, first or "")
        except ValueError as e:
            raise ValueError(f"無法作廢：作廢後會造成之後的賣出股數超過持股（{e}）。"
                             "請先作廢之後的賣出分錄。") from None
        self.conn.commit()

    def unvoid_transaction(self, txn_id: int) -> None:
        t = self.get_transaction(txn_id)
        if not t or not t["void"]:
            return
        self._check_open(t["date"])
        self.conn.execute("UPDATE transactions SET void = 0, void_reason = '', updated_at = ?"
                          " WHERE id = ?", (_now(), txn_id))
        self._log("取消作廢", txn_id, self.describe(txn_id))
        self._sync_securities(self.linked_securities(txn_id), t["date"])
        self.conn.commit()

    def reverse_transaction(self, txn_id: int, date: str | None = None) -> int:
        """迴轉：以相反借貸產生一張新分錄，原傳票保留。"""
        t = self.get_transaction(txn_id)
        if not t or t["void"]:
            raise ValueError("找不到可迴轉的傳票")
        date = date or _today()
        lines = []
        for ln in self.txn_lines_of(t, live=False):
            item = {"debit": ln["credit"], "credit": ln["debit"], "memo": ""}
            if ln["kind"] == "account":
                item["account_id"] = ln["id"]
                item["orig"] = -ln["orig"]
                if ln.get("security_id"):
                    item["security_id"] = ln["security_id"]
                    item["shares"] = ln["shares"]
            elif ln["kind"] == "category":
                item["category_id"] = ln["id"]
            else:
                item["special"] = ln["id"]
            lines.append(item)
        note = f"迴轉 {voucher_no(txn_id)}" + (f"：{t['note']}" if t["note"] else "")
        new_id = self.add_journal(date, note, lines, log="迴轉")
        self._log("被迴轉", txn_id, f"已由 {voucher_no(new_id)} 迴轉")
        self.conn.commit()
        return new_id

    def delete_transactions(self, ids: Iterable[int]) -> None:
        """永久刪除（僅供系統內部與測試使用；介面上一律使用作廢）。"""
        ids = list(ids)
        for i in ids:
            old = self.get_transaction(i)
            if old:
                self._check_open(old["date"])
        sids: set[int] = set()
        first = None
        for i in ids:
            desc = self.describe(i)
            linked = self.linked_securities(i)
            if linked:
                sids |= linked
                d = self.get_transaction(i)["date"]
                first = min(first or d, d)
            self.conn.execute("DELETE FROM txn_lines WHERE txn_id = ?", (i,))
            self.conn.execute("DELETE FROM recon_items WHERE txn_id = ?", (i,))
            self.conn.execute("DELETE FROM transactions WHERE id = ?", (i,))
            self._log("刪除", i, desc)
        self._sync_securities(sids, first or "")
        self.conn.commit()

    def get_transaction(self, txn_id: int) -> dict | None:
        return self._q1("SELECT * FROM transactions WHERE id = ?", (txn_id,))

    # ================================================================== 查詢
    def query_transactions(self, start=None, end=None, ttype=None, account_id=None,
                           category_id=None, keyword=None, limit=None,
                           include_void: bool = False) -> list[dict]:
        base = self.base_currency
        sql = """
            SELECT t.*,
                   a.name  AS account_name, a.currency AS currency, a.rate AS rate,
                   ta.name AS to_account_name, ta.currency AS to_currency,
                   c.name  AS category_name,
                   COALESCE(cp.inc, 0) AS inc, COALESCE(cp.exp, 0) AS exp,
                   (SELECT COUNT(*) FROM attachments x WHERE x.txn_id = t.id) AS n_attach,
                   (SELECT COUNT(*) FROM recon_items r WHERE r.txn_id = t.id) AS n_cleared
              FROM transactions t
              LEFT JOIN accounts a   ON a.id = t.account_id
              LEFT JOIN accounts ta  ON ta.id = t.to_account_id
              LEFT JOIN categories c ON c.id = t.category_id
              LEFT JOIN (SELECT txn_id,
                                SUM(CASE kind WHEN 'income' THEN base ELSE 0 END) AS inc,
                                SUM(CASE kind WHEN 'expense' THEN base ELSE 0 END) AS exp
                           FROM v_cat_post GROUP BY txn_id) cp ON cp.txn_id = t.id
             WHERE 1 = 1
        """
        params: list = []
        if not include_void:
            sql += " AND t.void = 0"
        if start:
            sql += " AND t.date >= ?"
            params.append(start)
        if end:
            sql += " AND t.date <= ?"
            params.append(end)
        if ttype:
            sql += " AND t.type = ?"
            params.append(ttype)
        if account_id:
            sql += (" AND (t.account_id = ? OR t.to_account_id = ? OR EXISTS (SELECT 1 FROM txn_lines l"
                    " WHERE l.txn_id = t.id AND l.account_id = ?))")
            params += [account_id, account_id, account_id]
        if category_id:
            sql += (" AND (t.category_id = ? OR EXISTS (SELECT 1 FROM txn_lines l"
                    " WHERE l.txn_id = t.id AND l.category_id = ?))")
            params += [category_id, category_id]
        if keyword:
            like = f"%{keyword.strip()}%"
            sql += (" AND (t.note LIKE ? OR c.name LIKE ? OR a.name LIKE ? OR COALESCE(ta.name, '') LIKE ?"
                    " OR EXISTS (SELECT 1 FROM txn_lines l LEFT JOIN accounts la ON la.id = l.account_id"
                    " LEFT JOIN categories lc ON lc.id = l.category_id WHERE l.txn_id = t.id AND"
                    " (la.name LIKE ? OR lc.name LIKE ? OR l.memo LIKE ?)))")
            params += [like] * 7
        sql += " ORDER BY t.date DESC, t.id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self._q(sql, params)
        jids = [r["id"] for r in rows if r["type"] == "journal"]
        names: dict[int, tuple[list[str], list[str]]] = {}
        if jids:
            marks = ",".join("?" * len(jids))
            for ln in self._q(
                    f"SELECT l.txn_id, l.special, la.name AS an, lc.name AS cn FROM txn_lines l"
                    f" LEFT JOIN accounts la ON la.id = l.account_id"
                    f" LEFT JOIN categories lc ON lc.id = l.category_id"
                    f" WHERE l.txn_id IN ({marks}) ORDER BY l.seq", jids):
                accs, others = names.setdefault(ln["txn_id"], ([], []))
                if ln["an"]:
                    if ln["an"] not in accs:
                        accs.append(ln["an"])
                else:
                    label = ln["cn"] or SPECIALS[ln["special"]][1]
                    if label not in others:
                        others.append(label)
        for r in rows:
            if r["type"] == "journal":
                accs, others = names.get(r["id"], ([], []))
                r["account_name"] = "、".join(accs)
                r["category_name"] = "、".join(others) or "帳戶間分錄"
                r["currency"] = base
                r["rate"] = 1.0
                r["base_amount"] = r["amount"]
            else:
                r["base_amount"] = money_round(r["amount"] * (r["rate"] or 1))
        return rows

    def recent_notes(self, limit: int = 300) -> list[str]:
        rows = self._q(
            "SELECT note, MAX(date) AS d FROM transactions WHERE note <> '' AND void = 0"
            " GROUP BY note ORDER BY d DESC LIMIT ?", (limit,))
        return [r["note"] for r in rows]

    def date_range(self) -> tuple[str, str]:
        row = self._q1("SELECT MIN(date) AS a, MAX(date) AS b FROM transactions")
        acc = self._q1("SELECT MIN(opening_date) AS a FROM accounts")
        today = _today()
        lo = min(x for x in (row["a"], acc["a"], today) if x)
        hi = max(x for x in (row["b"], today) if x)
        return lo, hi

    # ================================================================== 統計
    def income_expense_totals(self, start: str, end: str) -> dict:
        row = self._q1(
            "SELECT SUM(CASE kind WHEN 'income' THEN base ELSE 0 END) AS income,"
            " SUM(CASE kind WHEN 'expense' THEN base ELSE 0 END) AS expense"
            " FROM v_cat_post WHERE date BETWEEN ? AND ?", (start, end))
        inc = money_round(row["income"] or 0)
        exp = money_round(row["expense"] or 0)
        return {"income": inc, "expense": exp, "net": money_round(inc - exp)}

    def monthly_totals(self, start: str, end: str) -> dict[str, dict]:
        result = {ym: {"income": 0.0, "expense": 0.0} for ym in month_keys(start, end)}
        for r in self._q(
                "SELECT substr(date, 1, 7) AS ym, kind, SUM(base) AS total FROM v_cat_post"
                " WHERE date BETWEEN ? AND ? GROUP BY ym, kind", (start, end)):
            if r["ym"] in result:
                result[r["ym"]][r["kind"]] = money_round(r["total"])
        return result

    def category_totals(self, start: str, end: str, kind: str) -> list[dict]:
        rows = self._q(
            """
            SELECT c.id, c.name, c.budget, c.sort_order, c.tax_tag, SUM(p.base) AS total,
                   COUNT(DISTINCT p.txn_id) AS count
              FROM v_cat_post p JOIN categories c ON c.id = p.category_id
             WHERE p.date BETWEEN ? AND ? AND p.kind = ?
             GROUP BY c.id HAVING ABS(SUM(p.base)) > 0.004 ORDER BY total DESC
            """, (start, end, kind))
        for r in rows:
            r["total"] = money_round(r["total"] or 0)
        return rows

    def category_month_matrix(self, start: str, end: str, kind: str) -> dict[int, dict[str, float]]:
        out: dict[int, dict[str, float]] = {}
        for r in self._q(
                "SELECT category_id AS cid, substr(date, 1, 7) AS ym, SUM(base) AS total"
                " FROM v_cat_post WHERE date BETWEEN ? AND ? AND kind = ? GROUP BY cid, ym",
                (start, end, kind)):
            out.setdefault(r["cid"], {})[r["ym"]] = money_round(r["total"])
        return out

    def special_total(self, special: str, start: str, end: str) -> float:
        row = self._q1("SELECT SUM(gain) AS s FROM v_special_post WHERE special = ?"
                       " AND date BETWEEN ? AND ?", (special, start, end))
        return money_round(row["s"] or 0)

    def adjust_totals(self, start: str, end: str) -> float:
        return self.special_total("adjust", start, end)

    def fx_totals(self, start: str, end: str) -> float:
        return self.special_total("fx", start, end)

    def realized_totals(self, start: str, end: str) -> float:
        return self.special_total("realized", start, end)

    def net_worth_series(self, month_list: list[str]) -> list[dict]:
        out = []
        for ym in month_list:
            nw = self.net_worth(month_end(ym))
            nw["month"] = ym
            out.append(nw)
        return out

    def allocation_by_category(self, as_of: str | None = None) -> list[tuple[str, float]]:
        totals: dict[str, float] = {}
        for acc in self.account_summaries(as_of, include_archived=True):
            if acc["kind"] == "asset" and acc["base_value"] > 0:
                totals[acc["category"]] = totals.get(acc["category"], 0) + acc["base_value"]
        return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)

    # ================================================================== 會計
    @staticmethod
    def is_current(acc: dict) -> bool:
        if acc["kind"] == "asset":
            return acc["category"] in CURRENT_ASSET_CATEGORIES
        return acc["category"] in CURRENT_LIABILITY_CATEGORIES

    # ---------------------------------------------------------------- 科目代號
    def code_prefix(self, kind: str, category: str = "") -> str:
        """編碼原則：11 流動資產、12 非流動資產、21 流動負債、22 非流動負債、41 收入、51 費用。"""
        if kind in ("income", "expense"):
            return "41" if kind == "income" else "51"
        current = self.is_current({"kind": kind, "category": category})
        return ("1" if kind == "asset" else "2") + ("1" if current else "2")

    def used_codes(self, exclude: tuple | None = None) -> set[str]:
        used = {code for code, _, _ in SPECIALS.values()} | {EQUITY_CODE}
        for table, key in (("accounts", "account"), ("categories", "category")):
            for r in self._q(f"SELECT id, code FROM {table} WHERE code <> ''"):
                if exclude != (key, r["id"]):
                    used.add(r["code"])
        return used

    def next_code(self, prefix: str, used: set[str] | None = None) -> str:
        used = self.used_codes() if used is None else used
        n = 1
        while f"{prefix}{n:02d}" in used:
            n += 1
        return f"{prefix}{n:02d}"

    def validate_code(self, code: str, kind: str, exclude: tuple | None = None) -> str:
        code = (code or "").strip()
        if not code.isdigit() or not 3 <= len(code) <= 6:
            raise ValueError("科目代號請輸入 3～6 位數字，例如 1105")
        first = CODE_FIRST_DIGITS[kind]
        if code[0] not in first:
            allowed = "、".join(first)
            raise ValueError(f"{NATURE_LABELS[kind]}科目的代號須以 {allowed} 開頭")
        if code in self.used_codes(exclude):
            raise ValueError(f"科目代號 {code} 已被使用，請換一個")
        return code

    def _ensure_codes(self) -> None:
        """為尚未設定代號的科目自動編號（舊資料升級時沿用原本的編號順序）。"""
        used = self.used_codes()
        for acc in self._q("SELECT * FROM accounts WHERE code = '' ORDER BY id"):
            code = self.next_code(self.code_prefix(acc["kind"], acc["category"]), used)
            used.add(code)
            self.conn.execute("UPDATE accounts SET code = ? WHERE id = ?", (code, acc["id"]))
        for c in self._q("SELECT * FROM categories WHERE code = '' ORDER BY kind DESC, id"):
            code = self.next_code(self.code_prefix(c["kind"]), used)
            used.add(code)
            self.conn.execute("UPDATE categories SET code = ? WHERE id = ?", (code, c["id"]))

    def account_codes(self) -> dict[int, str]:
        return {r["id"]: r["code"] for r in self._q("SELECT id, code FROM accounts")}

    def category_codes(self) -> dict[int, str]:
        return {r["id"]: r["code"] for r in self._q("SELECT id, code FROM categories")}

    def chart_of_accounts(self, include_archived: bool = False) -> list[dict]:
        """完整會計科目表（供分錄選擇科目）。"""
        acodes = self.account_codes()
        ccodes = self.category_codes()
        out = []
        inv_accounts = {r["account_id"] for r in self._q("SELECT DISTINCT account_id FROM securities")}
        for a in self.list_accounts(include_archived=include_archived):
            out.append({"key": ("account", a["id"]), "code": acodes[a["id"]], "name": a["name"],
                        "group": "資產" if a["kind"] == "asset" else "負債", "currency": a["currency"],
                        "kind": a["kind"], "category": a["category"], "archived": a["archived"],
                        "current": self.is_current(a),
                        "investment": a["kind"] == "asset" and (a["category"] in INVESTMENT_CATEGORIES
                                                                or a["id"] in inv_accounts)})
        for c in self.list_categories(include_archived=include_archived):
            out.append({"key": ("category", c["id"]), "code": ccodes[c["id"]], "name": c["name"],
                        "group": "收入" if c["kind"] == "income" else "費用", "currency": None,
                        "kind": c["kind"], "category": "", "archived": c["archived"],
                        "investment": False})
        for key, (code, name, group) in SPECIALS.items():
            out.append({"key": ("special", key), "code": code, "name": name, "group": group,
                        "currency": None, "kind": "special", "category": "", "archived": 0,
                        "investment": False})
        return sorted(out, key=lambda x: x["code"])

    def txn_lines_of(self, t: dict, live: bool = True) -> list[dict]:
        """將任何傳票轉為本位幣借貸分錄行。live=True 時帳戶行依目前匯率重估。"""
        accs = getattr(self, "_acc_cache", None)
        if accs is None:
            accs = {a["id"]: a for a in self._q("SELECT * FROM accounts")}
        cats = {c["id"]: c for c in self._q("SELECT * FROM categories")} \
            if t["type"] in ("income", "expense", "journal") else {}
        acodes = self._codes_cache if getattr(self, "_codes_cache", None) else self.account_codes()
        ccodes = self.category_codes() if cats else {}

        def acc_line(aid, orig, base=None):
            a = accs[aid]
            b = orig * a["rate"] if base is None else base
            return {"kind": "account", "id": aid, "code": acodes[aid], "name": a["name"],
                    "group": "資產" if a["kind"] == "asset" else "負債", "orig": orig,
                    "debit": money_round(b) if b > 0 else 0.0,
                    "credit": money_round(-b) if b < 0 else 0.0}

        def cat_line(cid, debit, credit):
            c = cats[cid]
            return {"kind": "category", "id": cid, "code": ccodes[cid], "name": c["name"],
                    "group": "收入" if c["kind"] == "income" else "費用",
                    "debit": money_round(debit), "credit": money_round(credit)}

        def sp_line(key, gain):
            code, name, group = SPECIALS[key]
            return {"kind": "special", "id": key, "code": code, "name": name, "group": group,
                    "debit": money_round(-gain) if gain < 0 else 0.0,
                    "credit": money_round(gain) if gain > 0 else 0.0}

        ty = t["type"]
        if ty == "expense":
            base = t["amount"] * accs[t["account_id"]]["rate"]
            return [cat_line(t["category_id"], base, 0), acc_line(t["account_id"], -t["amount"])]
        if ty == "income":
            base = t["amount"] * accs[t["account_id"]]["rate"]
            return [acc_line(t["account_id"], t["amount"]), cat_line(t["category_id"], 0, base)]
        if ty == "transfer":
            out = [acc_line(t["to_account_id"], t["to_amount"]), acc_line(t["account_id"], -t["amount"])]
            fx = t["to_amount"] * accs[t["to_account_id"]]["rate"] - t["amount"] * accs[t["account_id"]]["rate"]
            if abs(fx) >= 0.005:
                out.append(sp_line("fx", fx))
            return out
        if ty == "adjust":
            base = t["amount"] * accs[t["account_id"]]["rate"]
            line = acc_line(t["account_id"], t["amount"])
            return [line, sp_line("adjust", base)] if base >= 0 else [sp_line("adjust", base), line]
        out = []
        fx = 0.0
        for ln in self.get_lines(t["id"]):
            if ln["account_id"]:
                stored = ln["debit"] - ln["credit"]
                if live:
                    item = acc_line(ln["account_id"], ln["orig"])
                    fx += ln["orig"] * accs[ln["account_id"]]["rate"] - stored
                else:
                    item = acc_line(ln["account_id"], ln["orig"], stored)
            elif ln["category_id"]:
                item = cat_line(ln["category_id"], ln["debit"], ln["credit"])
            else:
                item = sp_line(ln["special"], ln["credit"] - ln["debit"])
            item["memo"] = ln["memo"]
            item["security_id"] = ln["security_id"]
            item["shares"] = ln["shares"]
            out.append(item)
        if live and abs(fx) >= 0.005:
            out.append(sp_line("fx", fx))
        return out

    def ledger(self, account_id: int, start: str, end: str) -> dict:
        """分類帳：期初餘額、逐筆借貸與累計餘額（原幣；借方 = 帶號餘額增加）。"""
        acc = self.get_account(account_id)
        prev = (_dt.date.fromisoformat(start) - _dt.timedelta(days=1)).isoformat()
        opening_signed = self.signed_balances(prev).get(account_id, 0.0)
        sign = 1 if acc["kind"] == "asset" else -1
        rows = []
        running = opening_signed
        if start <= acc["opening_date"] <= end and acc["opening_balance"]:
            ob = acc["opening_balance"] * sign
            running += ob
            rows.append({"id": None, "date": acc["opening_date"], "voucher": "開帳",
                         "summary": "期初開帳", "counter": EQUITY_ACCOUNT,
                         "debit": ob if ob > 0 else 0.0, "credit": -ob if ob < 0 else 0.0,
                         "balance": money_round(running * sign)})
        posts = self._q(
            """
            SELECT p.txn_id, p.date, SUM(p.delta) AS delta, t.type, t.note
              FROM v_acc_post p JOIN transactions t ON t.id = p.txn_id
             WHERE p.account_id = ? AND p.date BETWEEN ? AND ?
             GROUP BY p.txn_id ORDER BY p.date, p.txn_id
            """, (account_id, start, end))
        for p in posts:
            t = self.get_transaction(p["txn_id"])
            others = [ln["name"] for ln in self.txn_lines_of(t, live=False)
                      if not (ln["kind"] == "account" and ln["id"] == account_id)]
            delta = p["delta"]
            running += delta
            rows.append({
                "id": p["txn_id"], "date": p["date"], "voucher": voucher_no(p["txn_id"]),
                "summary": p["note"] or TYPE_LABELS[p["type"]], "counter": "、".join(dict.fromkeys(others)),
                "debit": money_round(delta) if delta > 0 else 0.0,
                "credit": money_round(-delta) if delta < 0 else 0.0,
                "balance": money_round(running * sign), "type": p["type"],
            })
        return {
            "account": acc,
            "opening": money_round(opening_signed * sign),
            "closing": money_round(running * sign),
            "debit_total": money_round(sum(r["debit"] for r in rows)),
            "credit_total": money_round(sum(r["credit"] for r in rows)),
            "rows": rows,
            "normal_side": "借" if acc["kind"] == "asset" else "貸",
        }

    def journal(self, start: str, end: str) -> list[dict]:
        """日記簿：每張傳票的借貸分錄（以本位幣表示，帳戶行依目前匯率重估）。"""
        self._acc_cache = {a["id"]: a for a in self._q("SELECT * FROM accounts")}
        self._codes_cache = self.account_codes()
        try:
            entries = []
            for t in self._q("SELECT * FROM transactions WHERE void = 0 AND date BETWEEN ? AND ?"
                             " ORDER BY date, id", (start, end)):
                entries.append({"id": t["id"], "voucher": voucher_no(t["id"]), "date": t["date"],
                                "summary": t["note"] or TYPE_LABELS[t["type"]],
                                "lines": self.txn_lines_of(t)})
            return entries
        finally:
            self._acc_cache = None
            self._codes_cache = None

    def equity_opening(self, start: str, end: str) -> float:
        """期初淨值 = 期初日前一日淨資產 + 期間內新開立帳戶之期初金額。"""
        prev = (_dt.date.fromisoformat(start) - _dt.timedelta(days=1)).isoformat()
        equity = self.net_worth(prev)["net"]
        for acc in self._q("SELECT * FROM accounts WHERE opening_date BETWEEN ? AND ?", (start, end)):
            sign = 1 if acc["kind"] == "asset" else -1
            equity += acc["opening_balance"] * sign * acc["rate"]
        return money_round(equity)

    def trial_balance(self, start: str, end: str) -> list[dict]:
        """試算表：資產負債科目取期末餘額，損益科目取本期發生額，以期初淨值平衡。"""
        acodes = self.account_codes()
        ccodes = self.category_codes()
        rows = []
        for acc in self.account_summaries(end, include_archived=True):
            v = acc["base_value"]
            if not v:
                continue
            rows.append({"code": acodes[acc["id"]], "name": acc["name"],
                         "group": "資產" if acc["kind"] == "asset" else "負債",
                         "debit": v if v > 0 else 0.0, "credit": -v if v < 0 else 0.0})
        equity = self.equity_opening(start, end)
        rows.append({"code": "3101", "name": EQUITY_ACCOUNT, "group": "權益",
                     "debit": -equity if equity < 0 else 0.0, "credit": equity if equity > 0 else 0.0})
        for kind, group in (("income", "收入"), ("expense", "費用")):
            for c in self.category_totals(start, end, kind):
                v = c["total"]
                if kind == "income":
                    rows.append({"code": ccodes[c["id"]], "name": c["name"], "group": group,
                                 "debit": -v if v < 0 else 0.0, "credit": v if v > 0 else 0.0})
                else:
                    rows.append({"code": ccodes[c["id"]], "name": c["name"], "group": group,
                                 "debit": v if v > 0 else 0.0, "credit": -v if v < 0 else 0.0})
        for key, (code, name, group) in SPECIALS.items():
            g = self.special_total(key, start, end)
            if g:
                rows.append({"code": code, "name": name, "group": group,
                             "debit": -g if g < 0 else 0.0, "credit": g if g > 0 else 0.0})
        rows.sort(key=lambda r: r["code"])
        return rows

    def balance_sheet(self, as_of: str) -> dict:
        groups = {"流動資產": [], "非流動資產": [], "流動負債": [], "非流動負債": []}
        for acc in self.account_summaries(as_of, include_archived=True):
            if acc["opening_date"] > as_of and not acc["signed"]:
                continue
            if acc["archived"] and not acc["signed"]:
                continue
            if acc["kind"] == "asset":
                key = "流動資產" if self.is_current(acc) else "非流動資產"
            else:
                key = "流動負債" if self.is_current(acc) else "非流動負債"
            groups[key].append(acc)
        tot = {k: money_round(sum(a["base_value"] for a in v) * (1 if "資產" in k else -1))
               for k, v in groups.items()}
        assets = tot["流動資產"] + tot["非流動資產"]
        liabs = tot["流動負債"] + tot["非流動負債"]
        cash = sum(a["base_value"] for a in groups["流動資產"]
                   if a["category"] in CASH_EQUIVALENT_CATEGORIES)
        return {"groups": groups, "totals": tot, "assets": money_round(assets),
                "liabilities": money_round(liabs), "net": money_round(assets - liabs),
                "cash": money_round(cash)}

    def ratios(self, as_of: str, months: int = 12) -> dict:
        bs = self.balance_sheet(as_of)
        end = _dt.date.fromisoformat(as_of)
        mk = last_n_months(months, end)
        start = month_start(mk[0])
        ie = self.income_expense_totals(start, as_of)
        avg_exp = ie["expense"] / months if months else 0
        return {
            "debt_ratio": bs["liabilities"] / bs["assets"] if bs["assets"] else None,
            "current_ratio": (bs["totals"]["流動資產"] / bs["totals"]["流動負債"]
                              if bs["totals"]["流動負債"] else None),
            "savings_rate": ie["net"] / ie["income"] if ie["income"] else None,
            "emergency_months": bs["cash"] / avg_exp if avg_exp else None,
            "avg_monthly_expense": money_round(avg_exp),
            "liquid_ratio": bs["totals"]["流動資產"] / bs["assets"] if bs["assets"] else None,
        }

    def income_statement(self, start: str, end: str) -> dict:
        inc = self.category_totals(start, end, "income")
        exp = self.category_totals(start, end, "expense")
        ti = money_round(sum(c["total"] for c in inc))
        te = money_round(sum(c["total"] for c in exp))
        adj = self.adjust_totals(start, end)
        fx = self.fx_totals(start, end)
        realized = self.realized_totals(start, end)
        return {"income": inc, "expense": exp, "total_income": ti, "total_expense": te,
                "operating": money_round(ti - te), "adjust": adj, "fx": fx, "realized": realized,
                "comprehensive": money_round(ti - te + adj + fx + realized)}

    def account_delta_for(self, txn_id: int, account_id: int) -> float:
        row = self._q1("SELECT SUM(delta) AS d FROM v_acc_post WHERE txn_id = ? AND account_id = ?",
                       (txn_id, account_id))
        return money_round(row["d"] or 0)

    # ================================================================== 定期交易
    def list_recurring(self) -> list[dict]:
        rows = self._q("SELECT * FROM recurring ORDER BY active DESC, id")
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows

    def save_recurring(self, rec_id: int | None, name: str, data: dict, freq: str, day: int,
                       start_date: str, end_date: str = "", active: bool = True) -> int:
        payload = json.dumps(data, ensure_ascii=False)
        if rec_id:
            self.conn.execute(
                "UPDATE recurring SET name = ?, data = ?, freq = ?, day = ?, start_date = ?,"
                " end_date = ?, active = ? WHERE id = ?",
                (name, payload, freq, day, start_date, end_date or "", int(active), rec_id))
        else:
            cur = self.conn.execute(
                "INSERT INTO recurring(name, data, freq, day, start_date, end_date, active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, payload, freq, day, start_date, end_date or "", int(active)))
            rec_id = cur.lastrowid
        self.conn.commit()
        return rec_id

    def delete_recurring(self, rec_id: int) -> None:
        self.conn.execute("DELETE FROM recurring WHERE id = ?", (rec_id,))
        self.conn.commit()

    @staticmethod
    def recurring_dates(rec: dict, upto: str) -> list[str]:
        start = _dt.date.fromisoformat(rec["start_date"])
        stop = _dt.date.fromisoformat(upto)
        if rec.get("end_date"):
            stop = min(stop, _dt.date.fromisoformat(rec["end_date"]))
        after = rec.get("last_date") or ""
        step = {"monthly": 1, "quarterly": 3, "yearly": 12}[rec["freq"]]
        y, m = start.year, start.month
        out = []
        for _ in range(1200):
            last = (_dt.date(y + (m // 12), m % 12 + 1, 1) - _dt.timedelta(days=1)).day
            d = _dt.date(y, m, min(rec["day"], last))
            if d > stop:
                break
            if d >= start and d.isoformat() > after:
                out.append(d.isoformat())
            m += step
            while m > 12:
                m -= 12
                y += 1
        return out

    def due_recurring(self, upto: str | None = None) -> list[tuple[dict, str]]:
        upto = upto or _today()
        out = []
        for rec in self.list_recurring():
            if rec["active"]:
                for d in self.recurring_dates(rec, upto):
                    out.append((rec, d))
        return sorted(out, key=lambda x: x[1])

    def post_recurring(self, rec: dict, date: str, amount: float | None = None) -> int:
        data = dict(rec["data"])
        if amount is not None:
            data["amount"] = amount
        data["date"] = date
        data.setdefault("note", rec["name"])
        tid = self.add_transaction(log="定期交易入帳", **data)
        self.conn.execute("UPDATE recurring SET last_date = ? WHERE id = ? AND last_date < ?",
                          (date, rec["id"], date))
        self.conn.commit()
        return tid

    def skip_recurring(self, rec: dict, date: str) -> None:
        self.conn.execute("UPDATE recurring SET last_date = ? WHERE id = ? AND last_date < ?",
                          (date, rec["id"], date))
        self.conn.commit()

    # ================================================================== 銀行對帳
    def cleared_balance(self, account_id: int) -> float:
        acc = self.get_account(account_id)
        sign = 1 if acc["kind"] == "asset" else -1
        ob = acc["opening_balance"] * sign
        row = self._q1(
            "SELECT SUM(p.delta) AS d FROM v_acc_post p JOIN recon_items r"
            " ON r.txn_id = p.txn_id AND r.account_id = p.account_id WHERE p.account_id = ?",
            (account_id,))
        return money_round((ob + (row["d"] or 0)) * sign)

    def recon_candidates(self, account_id: int, statement_date: str) -> list[dict]:
        acc = self.get_account(account_id)
        sign = 1 if acc["kind"] == "asset" else -1
        rows = self._q(
            """
            SELECT p.txn_id, p.date, SUM(p.delta) AS delta, t.type, t.note
              FROM v_acc_post p JOIN transactions t ON t.id = p.txn_id
             WHERE p.account_id = ? AND p.date <= ?
               AND NOT EXISTS (SELECT 1 FROM recon_items r WHERE r.txn_id = p.txn_id
                                                             AND r.account_id = p.account_id)
             GROUP BY p.txn_id ORDER BY p.date, p.txn_id
            """, (account_id, statement_date))
        for r in rows:
            r["voucher"] = voucher_no(r["txn_id"])
            r["effect"] = money_round(r["delta"] * sign)
        return rows

    def save_reconciliation(self, account_id: int, statement_date: str, statement_balance: float,
                            txn_ids: list[int]) -> int:
        cur = self.conn.execute(
            "INSERT INTO reconciliations(account_id, statement_date, statement_balance, created_at)"
            " VALUES (?, ?, ?, ?)", (account_id, statement_date, money_round(statement_balance), _now()))
        rid = cur.lastrowid
        for t in txn_ids:
            self.conn.execute("INSERT OR IGNORE INTO recon_items(recon_id, txn_id, account_id)"
                              " VALUES (?, ?, ?)", (rid, t, account_id))
        self.conn.commit()
        return rid

    def list_reconciliations(self, account_id: int) -> list[dict]:
        return self._q("SELECT r.*, (SELECT COUNT(*) FROM recon_items i WHERE i.recon_id = r.id) AS n"
                       " FROM reconciliations r WHERE account_id = ? ORDER BY statement_date DESC, id DESC",
                       (account_id,))

    # ================================================================== 附件
    def add_attachment(self, txn_id: int, src: str, folder: str) -> int:
        os.makedirs(folder, exist_ok=True)
        base = os.path.basename(src)
        dest = os.path.join(folder, f"{voucher_no(txn_id)}_{_dt.datetime.now():%Y%m%d%H%M%S}_{base}")
        shutil.copy2(src, dest)
        cur = self.conn.execute("INSERT INTO attachments(txn_id, name, path, added_at) VALUES (?, ?, ?, ?)",
                                (txn_id, base, dest, _now()))
        self._log("新增附件", txn_id, base)
        self.conn.commit()
        return cur.lastrowid

    def list_attachments(self, txn_id: int) -> list[dict]:
        return self._q("SELECT * FROM attachments WHERE txn_id = ? ORDER BY id", (txn_id,))

    def remove_attachment(self, att_id: int) -> None:
        row = self._q1("SELECT * FROM attachments WHERE id = ?", (att_id,))
        if not row:
            return
        self.conn.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
        self._log("移除附件", row["txn_id"], row["name"])
        self.conn.commit()

    # ================================================================== 維護
    def backup_to(self, dest: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        target = sqlite3.connect(dest)
        try:
            self.conn.backup(target)
        finally:
            target.close()

    @staticmethod
    def is_valid_ledger(path: str) -> bool:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")}
            finally:
                conn.close()
            return {"accounts", "categories", "transactions", "settings"} <= names
        except sqlite3.Error:
            return False

    def restore_from(self, src: str) -> None:
        if not self.is_valid_ledger(src):
            raise ValueError("所選檔案不是有效的理財帳本備份檔。")
        safety = self.path + ".before-restore"
        self.backup_to(safety)
        self.close()
        try:
            shutil.copyfile(src, self.path)
        except OSError:
            shutil.copyfile(safety, self.path)
            raise
        finally:
            self._open()

    def reset_all(self) -> None:
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.executescript(
            "DELETE FROM txn_lines; DELETE FROM recon_items; DELETE FROM reconciliations;"
            "DELETE FROM attachments; DELETE FROM sec_events; DELETE FROM securities;"
            "DELETE FROM recurring; DELETE FROM transactions; DELETE FROM accounts;"
            "DELETE FROM categories; DELETE FROM audit_log; DELETE FROM sqlite_sequence;")
        self._insert_default_categories()
        self._ensure_codes()
        self.conn.execute("UPDATE settings SET value = '0' WHERE key = 'sample_data'")
        self.conn.commit()
        self.conn.execute("PRAGMA foreign_keys = ON")

    def start_fresh(self) -> None:
        """清除所有資料並建立基本帳戶（用於清除範例資料後正式開始）。"""
        self.reset_all()
        self.set_setting("closed_until", "")
        start = _dt.date.today().replace(month=1, day=1).isoformat()
        self.add_account("現金", "asset", "現金", opening_date=start)
        self.add_account("銀行存款", "asset", "銀行存款", opening_date=start)

    def auto_backup(self, folder: str, keep: int = 30) -> str | None:
        """每天第一次開啟時自動備份，保留最近 keep 份。"""
        os.makedirs(folder, exist_ok=True)
        name = f"帳本自動備份_{_dt.date.today():%Y%m%d}.db"
        dest = os.path.join(folder, name)
        if os.path.exists(dest):
            return None
        self.backup_to(dest)
        files = sorted(f for f in os.listdir(folder) if f.startswith("帳本自動備份_") and f.endswith(".db"))
        for old in files[:-keep]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        return dest


# ---------------------------------------------------------------------- 日期工具
def month_keys(start: str, end: str) -> list[str]:
    s = _dt.date.fromisoformat(start)
    e = _dt.date.fromisoformat(end)
    y, m = s.year, s.month
    out = []
    while (y, m) <= (e.year, e.month):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def month_end(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    nxt = _dt.date(y + 1, 1, 1) if m == 12 else _dt.date(y, m + 1, 1)
    return (nxt - _dt.timedelta(days=1)).isoformat()


def month_start(ym: str) -> str:
    return f"{ym}-01"


def last_n_months(n: int, ref: _dt.date | None = None) -> list[str]:
    ref = ref or _dt.date.today()
    y, m = ref.year, ref.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))
