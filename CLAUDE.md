# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

「我的理財帳本」: a Traditional Chinese desktop ledger (PySide6 + SQLite + openpyxl) for a retired professional accountant (游媽媽). It is shipped as a single Windows exe built with PyInstaller, published on GitHub Releases as `MyLedger.exe`. Users think in accounting terms (會計科目, 借貸, 日記帳/分類帳/試算表, 短期投資/長期投資), so keep UI text and features framed that way, and keep all user-facing text in Traditional Chinese.

The app is still evolving: expect more feature requests from her. Each release replaces the exe on her PC and must open her existing data **without crashing**. See "Release checklist" below.

**Data from earlier releases must never be lost.** This applies to every change, not only to releases: every feature, fix or refactor must leave her existing data loadable. Before calling any work done, prove that a ledger created by **each** released version (not just the latest; she may skip updates) still opens with the new code without errors, and that nothing in it changed (see release checklist item 4). If a change cannot meet this, stop and ask instead of shipping it. After upgrading, all of her accounts, vouchers, investments, settings and attachments must still be there with the same balances. The only exception is a change she explicitly asked for, such as v4 removing automatic valuation or v5 valuing at the net sale price; the affected accounts must then differ only by that change. Never delete, reset or overwrite her data folder or existing rows during an upgrade.

## Environment and commands

Source lives in WSL (`~/accountApp`), but Qt, the tests that need Qt, and the build all run on Windows. The Windows venv is at `C:\Users\User\accountApp_build\venv`, and its source copy is `C:\Users\User\accountApp_build\src`. PyInstaller cannot cross-compile from Linux.

```sh
bash tools/sync_win.sh            # copy app/ tools/ tests/ spec etc. to the Windows src copy (do this after every edit)
cd /mnt/c/Users/User/accountApp_build/src
../venv/Scripts/python.exe run.py                     # run the app
../venv/Scripts/python.exe tests/test_db.py           # data/accounting tests; prints "ALL PASSED 0"
../venv/Scripts/python.exe tests/test_gui.py          # drives real dialogs; must print all "... PASSED" lines
../venv/Scripts/pyinstaller.exe --noconfirm --clean accountApp.spec   # -> src/dist/我的理財帳本.exe
```

- The tests are plain scripts, with no pytest. Every `test_*` function in `test_db.py` runs automatically.
- To run a single test (this also works with WSL `python3`, since `test_db` doesn't need Qt): `python3 -c "import tests.test_db as t; t.test_journal_linked_investment()"`
- There is no linter config.

Deliverable generators (run from `src` with the Windows python):

```sh
python tools/screenshots.py ../shots                        # page/dialog PNGs (animations disabled)
python tools/make_guide.py ../shots ../使用說明.pdf          # PDF guide; image names come from screenshots.py
python tools/demo_video.py ../示範影片.mp4 ../excel_shots    # ~7 min; Windows SAPI zh-TW TTS (cached in tts_cache/) + ffmpeg
```

Final deliverables go to `C:\Users\User\accountApp_build\交付_給游媽媽\` and are copied to `~/accountApp/dist/`.

Environment variables:
- `MY_LEDGER_DATA_DIR`: data folder override.
- `MY_LEDGER_SMOKE_DIR`: smoke mode. It loads the data, screenshots all 6 pages as `exe_*.png`, then quits.

To pass these from WSL to the exe, set `WSLENV=MY_LEDGER_DATA_DIR:MY_LEDGER_SMOKE_DIR` and use Windows paths.

## Architecture

**Data layer (`app/database.py`).** All accounting is derived from three SQL views. `v_acc_post` holds account postings in the original currency, `v_cat_post` holds income/expense postings in base currency, and `v_special_post` holds the 7101 評價, 7201 兌換, 7301 處分 and 3102 淨值調整 postings. Void vouchers are excluded everywhere. Reports never hand-sum the transactions tables.

- **Signed balances:** assets are positive, liabilities negative. Debit means the signed balance increases.
- **Voucher types:** income, expense, transfer and adjust are single-row types. `journal` stores multi-line 借/貸 in `txn_lines`, in base currency, with each account line's original-currency amount in `orig`.
- **FX:** foreign accounts are revalued at the current rate, and the difference goes to 兌換損益. This keeps the trial balance balanced.
- **Chart of accounts:**
  - Asset/liability 科目 are rows in `accounts`; their `category` (e.g. 短期投資 or 長期投資) decides 流動 vs 非流動.
  - Income/expense 科目 are rows in `categories`.
  - Both have a stored `code`: auto-assigned by prefix (11/12/21/22/41/51) or user-defined and validated (`validate_code`).
  - The fixed system 科目 live in `SPECIALS` plus 3101.
  - `chart_of_accounts()` is the single list the UI uses.
- **Immutability:** records are voided or reversed, never deleted. A closing date (`closed_until`) locks earlier periods. Every change is written to `audit_log`.
- **Voucher numbers** are `V` + `transactions.id`. `Investments.rebuild()` reinserts regenerated system vouchers with their old ids (matched by date + note, then by order within the day), so numbers, reconciliation marks and attachments survive a rebuild. Only vouchers that are no longer needed disappear.
- **Equity is perpetual:** 期初淨值 is net worth the day before a period starts (`equity_opening`), so every period already starts "closed". 年度結帳 (`close_year`) still records a closing entry (`source = 'close:<year>'`, special line `closing` = 3201 本期損益) for the 日記簿 and locks the year. The views exclude `close:%` vouchers so reports never change, and any code that reads `txn_lines` directly must skip them too (e.g. the Excel 收支明細). Moving `closed_until` earlier (`set_closed_until`) voids later closing entries; `refresh_year_closings()` regenerates stale ones after a system rebuild.
- **Trial balance** is six-column (`open_*`, `period_*`, closing `debit`/`credit`); each pair must balance. `equity_statement()` is the 權益變動表.
- **Schema:**
  - `SCHEMA_VERSION` is currently 8.
  - `_open()` copies the DB to `理財帳本_升級前備份_v<N>.db`, then runs migrations in order (`_migrate_v1_to_v2`, `_migrate_v2_to_v3`, `_migrate_v4_to_v5`, `_migrate_v7_to_v8`) **before** `executescript(_TABLES)`.
  - The ALTERs are guarded by `PRAGMA table_info`.
  - v5 adds `txn_lines.price` (unit price on investment journal lines) and `securities.fee_rate`/`fee_min`/`tax_rate` (ETF codes starting `00` get 0.1% tax, other stocks 0.3%). v6 and v7 have no new columns; they only trigger the restate (v6 removes the old sale-reversal vouchers, v7 the journal-sell cost adjustments). v8 adds `securities.type_name` (filled when a security's rates exactly match a default type) and its restate merges valuation vouchers per date.
  - `_restate_investments` runs at the end of `_open()` for any DB older than the current version, because it needs the views. It rebuilds all investment system vouchers, including closed periods, and reattaches reconciliation marks and attachments. `user_version` stays 4 until it finishes, so an interrupted upgrade only repeats the rebuild.
  - `_ensure_codes()` then fills any missing 科目代號.

**Investment sub-ledger (`app/investments.py`).**
- Holdings are never stored. `replay(sid)` recomputes shares, average cost, realized gains and the vouchers each event implies, from two sources: `sec_events` (buy, sell, dividends, prices) plus **journal lines linked to a security** (`txn_lines.security_id`/`shares` → events `jbuy`/`jsell`; on an **income** category line such as 4104 股利 → `jdiv`, with `shares` = shares held and `price` = dividend per share, counted in that security's dividends and creating no voucher).
- `rebuild(sid, from_date)` deletes and regenerates the system vouchers (`transactions.source = 'inv:<sid>'`) from that date. Those vouchers are read-only in the UI.
- `Database._sync_securities()` (lazy-imports Investments) runs replay as validation, and rolls back on errors such as overselling. Then it runs rebuild after any journal add, update, void, unvoid, reverse or delete that touches a linked security.
- Valuation is manual only: buys, sells and stock dividends never create valuation vouchers. Only a `price` event (投資管理 → 市價評價: a date and market price she enters) does. Since v2.5.0 (her request) a sale does **not** reverse the valuation booked on the shares sold: `val_adj` stays in the investment account until the next 市價評價 adjusts the whole holding. A fully sold security with leftover `val_adj` still shows in `holdings()` (0 shares) and 市價評價 zeroes it automatically.
- Journal sells (v2.6.0, her request): if the voucher has her own 處分投資損益 (7301) line, the system creates **no** voucher and the cost removed is exactly what she credited to the investment account (she may use FIFO/specific cost; the remaining holding's cost absorbs the difference). Only a sell credited at net proceeds with no 7301 line still gets the average-cost split voucher. A sold-out security with leftover cost or `val_adj` stays in `holdings()`; its 市價評價 zeroes it (cost residual → 7301, valuation → 7101).
- Valuation vouchers (v2.7.0, her request): all `price` events on one date share **one** voucher, `source = 'inv:val'`, one line pair per security with the security/price as memo. `rebuild(sid)` regenerates per-security vouchers (`inv:<sid>`, buys/sells/dividends) and then `_rebuild_valuations(from_date)` regenerates the shared ones for all securities, reusing the lowest old voucher id of that date.
- Security types (股票, ETF, …, each with fee rate, min fee, tax rate) are JSON in the `security_types` setting (`Investments.security_types`, default `DEFAULT_SECURITY_TYPES`); editing a type re-rates its securities (`save_security_types`). 投資管理 → 標的設定 (`SecurityListDialog`) edits any security.
- System (`inv:`) vouchers can be deleted from 收支明細 or the opened voucher: `Investments.delete_vouchers` maps each voucher to its `sec_events` rows (`voucher_events`; an `inv:val` voucher maps to every price event of its date) and deletes the event, all-or-nothing.
- Journal sells: fee/tax shown = shares × unit price − net proceeds, where net proceeds = credit to the investment account + 處分投資損益 (7301) booked in the same voucher.
- Valuation is at the **estimated net sale price**: price × shares − estimated sell fee − securities tax. So 未實現損益 already includes trading costs, as she asked; cost already includes the buy fee because she debits it into 1201/1202.
- Fees come from `trade_costs()` using the security's rates. They are rounded **down** to the yuan (Taiwan broker practice) with a minimum fee. Changing a security's rates rebuilds its valuation vouchers and is refused if a valuation falls in a closed period.
- Invariant: an investment account's balance equals the book value of its holdings, i.e. cost + booked valuation (`state["market_value"]`; `tests/test_db.py::investment_accounts_match`).

**Other modules:**
- `analytics.py`: cash flow (direct method, self-checking) and tax summary. The 退休規劃 page was removed in v2.3.0; its settings keys (`birth_year`, `retire_params`, `allocation_targets`) are left in old DBs untouched.
- `printing.py`: print/PDF via `QTextDocument` + `QtPrintSupport` (vouchers with sign-off boxes, 日記簿, 總分類帳, six-column 試算表, statements, 權益變動表). `<thead>` repeats per page and page numbers are automatic; Qt ignores CSS height, so use content for spacing. `dialogs_print.py` is the UI. Tests count PDF pages with QtPdf, which is excluded from the exe, so keep it test-only.
- `exporter.py`: a 13-sheet Excel workbook with live formulas and ✓ balance checks, including 分類帳. She picks sheets in the export dialog (`SHEET_INFO`); an unselected sheet that a selected one references (`SHEET_DEPS`) is kept hidden so the formulas still work.
- `importer.py`: Excel/CSV import.
- `online.py`: optional internet updates, **off by default**; manual entry must always work.
- `search.py` (Qt-free) + `dialogs_search.SearchDialog`: 全域搜尋 (Ctrl+F or the sidebar button, `MainWindow.open_search`). It finds vouchers, 科目, securities and recurring entries. Space-separated tokens are ANDed. A token is typed by shape: `V000123` is a voucher number, `2025-03` or `114/3/5` (民國) is a date prefix, a number matches amounts/prices/shares or a code, and anything else matches text (notes, memos, names, attachment names, void reasons). The dialog is modeless and re-runs on `ctx.dataChanged`. Double-click opens a voucher, goes to an account's 分類帳 / a category's 收支明細 / a security's 交易紀錄 (`InvestmentsPage.apply_filter(security_id=)`), or opens a recurring entry. It is read-only.
- `dialogs_update.py`: 檢查新版本. 設定 → 網路 has 「立即檢查新版本」 plus an opt-in startup check (`update_auto`, default off; at most once a day via `update_last_check`; `update_skip` silences one version). `online.fetch_latest_release()` reads the GitHub latest release, and the asset `digest` gives the SHA-256. 「立即更新」 (frozen exe only) downloads next to the exe and verifies it, backs up the ledger to `自動備份/更新前備份_v<old>_<time>.db`, renames the running exe to `.old`, moves the new one into place and restarts with PyInstaller env vars cleared (`PYINSTALLER_RESET_ENVIRONMENT`). `cleanup_old_exe()` deletes the `.old` on the next start. If the folder is not writable, the new exe goes to 下載 and she replaces it by hand. This depends on the release asset staying named `MyLedger.exe`.

**UI.**
- `main.py` builds `MainWindow` with 6 pages (`app/pages/*`, subclasses of `pages/base.Page`).
- `AppContext` (`context.py`) holds the DB, paths and signals. Call `ctx.changed()` after any data change so all pages refresh, and use `ctx.toast` for messages.
- Dialogs are in `dialogs.py`, `dialogs_more.py` (journal, void, audit, recurring, reconcile, import), `dialogs_invest.py` and `dialogs_chart.py` (會計科目表).
- `widgets.DateEdit` (from `make_date_edit`) is a typed date field on a `QComboBox`, because `QDateEdit` ignores typing. It accepts 西元 and 民國 dates, and `date()` commits pending text.
- 複式分錄 templates are JSON in the `journal_templates` setting (`dialogs_more.load_templates`); `JournalDialog.TEMPLATES` holds the built-in defaults.
- `widgets.AmountEdit(decimals=n)` rounds to `n` places (unit prices use 3, shares 4); `safe_eval` takes the digits.
- 複式分錄 rows on a foreign-currency (non-investment) account show 原幣金額／匯率 instead of the security fields; the line's `orig` is saved as entered.
- `widgets.DataTable`/`Column` is the standard table. A row dict can carry `_bold`/`_bg`, and a delegate paints `_bg`, because the QSS would otherwise ignore it.
- Animations go through `animations.py` and must stay switchable (設定 → 動畫效果).
- `main._install_excepthook` shows a friendly error and appends to `錯誤紀錄.log` in the data folder. Tests restore `sys.__excepthook__` so that tracebacks show.

**User data.**
- Everything is under `文件\我的理財帳本\`:
  - `理財帳本.db`
  - `自動備份\` (one copy on the first launch each day, last 30 kept)
  - `匯出報表\`
  - `憑證附件\`
- The app has no background process.
- A fresh install starts empty; sample data loads only if she chooses it (`sample_data.py`).

## Release checklist (avoid crashes in the new release)

1. **Migrations:** if you change the schema, bump `SCHEMA_VERSION`, add a guarded `_migrate_vN_to_vN+1`, and add a migration test like `test_migration_v2_codes`. Never put an index or view on a new column into `_TABLES`/`_VIEWS` unless the migration adds that column first.
2. **Tests:** run both test scripts on Windows. `test_gui.py` stubs modal boxes (`ask`/`info`/`error`/`warn`) only in the modules it lists. If new code shows a message box from another module, add that module, or the test will hang.
3. **Packaging:** `accountApp.spec` excludes many modules, including `PIL`, `QtNetwork`, `QtPdf`, `QtSql` and `unittest`. Importing one of them from `app/` works in dev but crashes the exe, so update `excluded` if you need one.
4. **Old data still loads (required for every change):**
   - **Automated part:** `tests/fixtures/ledger_<tag>.db` is a realistic ledger built by that release's own code, saved with its books snapshot (`.json`), for every release so far.
     - `test_db.py::test_old_version_ledgers_load` opens each fixture with the current code and requires everything to match, except investment balances under `APPROVED_INVESTMENT_CHANGES`, which must still equal the holdings' book value. It also checks the books balance and that the upgrade backup exists.
     - `test_gui.py` opens each fixture in the real window, visits every page and tab, and runs an export and a print render.
     - **After tagging a release**, run `python3 tools/make_fixtures.py` and commit the new `ledger_<tag>.*`. If a future change intentionally alters her numbers, add it to `APPROVED_INVESTMENT_CHANGES` (or extend that mechanism) and say so in the PR; never regenerate old fixtures to make a test pass.
     - `tests/fixtures/ledger_tools.py` must keep working with every old version's code, so use only APIs every release has.
   - **Make the old ledgers.** For **every** release tag (`git tag`), extract that version's code (`git archive <tag> app | tar -x -C <dir>`). Use it to build a realistic ledger: accounts with codes, journal buys/sells linked to securities, valuations, recurring entries, templates, reconciliation marks, attachments and a closed period.
   - **Compare the books.** Snapshot the books with the old code, open the same file with the new code, and compare everything: every account balance, voucher count and voucher numbers, holdings, realized/unrealized totals, trial-balance difference, settings (name, closed date, templates) and reconciliation marks.
   - **Expected differences:** only a change she explicitly asked for may differ, and the PR must list it.
   - **Smoke-test the exe:** build the exe and run it with `MY_LEDGER_SMOKE_DIR` on a fresh data dir and on a copy of each of those ledgers. Check that the `exe_*.png` pages render and that no `錯誤紀錄.log` appears. A schema change must also create `理財帳本_升級前備份_v<N>.db`.
5. **Layout:** check at about a 1380 px wide window. Page header buttons and the 9 財務報表 tabs have overflowed before.
6. **Version and release:** bump `APP_VERSION` (`context.py`) and `version_info.txt`. Tag `vX.Y.Z` and publish only the exe as `MyLedger.exe`, keeping that name so `releases/latest/download/MyLedger.exe` stays valid. The PDF guide and demo video are no longer shipped (since v2.2.0), though `tools/make_guide.py` and `tools/demo_video.py` remain in the repo.
