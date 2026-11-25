# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

「我的理財帳本」: a Traditional Chinese desktop ledger for Windows, for one user: a retired professional accountant. The UI is a web UI (Preact + ECharts) in Edge WebView2 via pywebview; the accounting is a SQLite core in Python. It ships as a single exe built with PyInstaller and published on GitHub Releases as `MyLedger.exe`. She thinks in accounting terms (會計科目, 借貸, 日記帳/分類帳/試算表, 短期投資/長期投資), so keep UI text and features framed that way, and keep all user-facing text in Traditional Chinese.

The app is still evolving: expect more feature requests from her. Each release replaces the exe on her PC and must open her existing data **without crashing**. See "Release checklist" below.

**Data from earlier releases must never be lost.** This applies to every change, not only to releases: every feature, fix or refactor must leave her existing data loadable. Before calling any work done, prove that a ledger created by **each** released version (not just the latest; she may skip updates) still opens with the new code without errors, and that nothing in it changed (see release checklist item 4). If a change cannot meet this, stop and ask instead of shipping it. After upgrading, all of her accounts, vouchers, investments, settings and attachments must still be there with the same balances. The only exception is a change she explicitly asked for, such as v4 removing automatic valuation or v5 valuing at the net sale price; the affected accounts must then differ only by that change. Never delete, reset or overwrite her data folder or existing rows during an upgrade. Stored setting keys keep their old names (e.g. `v3_tour_done`, `update_last_check`) even where they look dated.

## Repo layout

- `core/`: accounting engine with no UI (`database`, `investments`, `statements`, `analytics`, `performance`, `printing` HTML, `exporter`, `importer`, `search`, `backup`, `undo`, `updater`, `online`, `journal_templates`, `sample_data`, `fmt`, `version`). Called `app/` up to v3.4.1.
- `desktop/`: the shipped app. `run.py` (entry point), `api.py` + `api_*.py` (methods the UI calls), `rpc.py`, `paths.py`, `webview2.py`, `screenshot.py`/`devshots.py` (test hooks), `whatsnew.md` (release notes), `ui/` (HTML/JS/CSS). Called `v3/` up to v3.4.1.
- `tests/`: `test_core.py` (accounting core), `test_api.py` (every UI method on every fixture), `fixtures/` (one ledger per release with its books snapshot, plus `ledger_tools.py`).
- `tools/`: `sync_win.sh`, `smoke.py` (exe smoke test), `make_fixtures.py`, `make_icon.py`.
- `packaging/`: `myledger.spec`, `build.bat`, `app.ico`, `version_info.txt`.
- `docs/images/`: README screenshots.

## Environment and commands

Source lives in WSL (`~/accountApp`), but WebView2, the tests that need openpyxl, and the build run on Windows. The Windows venv is `C:\Users\User\accountApp_build\venv3` (pywebview, pythonnet, openpyxl, pyinstaller; `requirements.txt`), and the source copy is `C:\Users\User\accountApp_build\src`. PyInstaller cannot cross-compile from Linux.

```sh
bash tools/sync_win.sh            # copy core/ desktop/ tools/ tests/ packaging/ to the Windows src copy (do this after every edit)
cd /mnt/c/Users/User/accountApp_build/src
MY_LEDGER_DEMO=1 ../venv3/Scripts/python.exe desktop/run.py    # run the app on a throwaway sample ledger (WSLENV=MY_LEDGER_DEMO)
../venv3/Scripts/python.exe tests/test_api.py                  # prints "ALL PASSED"
../venv3/Scripts/python.exe tests/test_core.py                 # prints "ALL PASSED 0"
cd packaging && ../../venv3/Scripts/pyinstaller.exe --noconfirm --clean myledger.spec   # -> src/packaging/dist/我的理財帳本.exe
PYTHONIOENCODING=utf-8 ../venv3/Scripts/python.exe tools/smoke.py 'packaging\dist\我的理財帳本.exe'   # from src (WSLENV=PYTHONIOENCODING)
```

- The tests are plain scripts, with no pytest. Every `test_*` function runs automatically.
- To run a single core test: `python3 -c "import tests.test_core as t; t.test_journal_linked_investment()"` (WSL `python3` works for tests that don't need openpyxl).
- There is no linter config.
- Don't dismiss smoke-test timeouts as flaky: until v3.8.0 they were a real startup bug.

Environment variables (pass from WSL with `WSLENV=...` and Windows paths):
- `MY_LEDGER_DATA_DIR`: data folder override. Without it, `MY_LEDGER_DEMO=1` uses a throwaway sample ledger.
- `MY_LEDGER_SMOKE_DIR`: smoke mode. Loads the data, screenshots all 6 pages as `exe_*.png`, then quits.
- `MY_LEDGER_SHOT=<dir>` + `MY_LEDGER_SCENES=<name>`: scripted scenes and screenshots (`desktop/devshots.py`). `readme` = README screenshots (copy `readme_*.png` into `docs/images/` without the prefix), `mom` = her 1151123 list-size checks, `audit` = every page, tab and list dialog with visible-row counts. These resize to 1280×720 unless `MY_LEDGER_VIEW=<w>x<h>@<scale>` is set (use `1024x528@1.875`, her real screen).
- `MY_LEDGER_CLOSE_TEST=<dir>`: captures the farewell screen on a real close.

## Desktop app (`desktop/`)

- `run.py`: WebView2 check (`webview2.py`, offers Microsoft's installer if missing), `core.updater.cleanup_old_exe`, daily auto backup and second backup on open, second backup on close if data changed, then a pywebview window (`gui="edgechromium"`, maximized) on `desktop/ui/index.html`. The WebView2 profile is `%LOCALAPPDATA%\MyLedger\WebView2` (temporary in test modes).
- Startup: the page loads ~30 files from pywebview's local server, whose default listen queue is 5, so a connection could be refused and the app stuck on the splash screen. `run.py` raises `TCPServer.request_queue_size`, and `index.html` reloads (max 3) when a script fails to load. Keep both. A dev-driver exception is written to `driver_error.txt` (with the page state) and closes the window.
- `api.py` composes `Api` from `api_*.py` mixins (one per page/area). Every method is wrapped by `rpc.exposed`: it runs on the single `DbThread` (SQLite is thread-bound), converts `ValueError` to `{"__error__": msg}` (shown to her), logs other exceptions to `錯誤紀錄.log` and returns a friendly message, and makes results JSON-safe. `db=False` methods (file dialogs, network) run off the DB thread. All accounting stays in `core/`.
- UI: Preact + htm + ECharts, vendored in `desktop/ui/vendor`, no build step. `lib/core.js` (api(), `changed()`/`useLoad` refresh, formatting, 民國 dates, amount formulas), `lib/ui.js` (dialogs via `openModal`, fields, `DataTable`, `Combo`, `Portal`, menus, `Tabs`, `PeriodChips`), `lib/charts.js`, `lib/caticon.js`, `pages/*.js` (6 pages), `dialogs/*.js`. Printing previews `core/printing.Report` HTML in an iframe and prints through Edge.
- Look: design tokens at the top of `style.css` (indigo brand `--primary/--primary-2`, `--hero-a/-b`, semantic income/expense/transfer/adjust/gold, radii, shadows, `--ring`), light and dark. Sizes are in rem (標準 13px / 大 / 特大 change the root font size) and switch instantly. Never hard-code colours in JS except the chart `PALETTE`. The opening screen is `#splash` in `index.html`; closing shows a farewell screen (`window.__farewell`, driven by the `closing` handler in `run.py`, which also runs the second backup). The icon is `desktop/ui/logo.svg` (sizes ≤ 24 px use the simpler `logo-small.svg`); `tools/make_icon.py` renders them with headless Edge and Pillow to `packaging/app.ico` and `desktop/ui/logo-256.png` (dev only). UI icons are all our own in `desktop/ui/icons.js`: 24 grid, 1.75 stroke, round caps, `class="d"` for the duotone fill. Category icons (`c_*`, chosen by name in `lib/caticon.js`, tinted with `--tone-*`) replaced emoji in v3.9.0; don't bring emoji back. Text colours keep at least 4.5:1 contrast on white.
- Her PC: 1920×1080, Windows scale 125%, and (inferred from a devicePixelRatio of 1.875) accessibility text size 150%, so the page's usable area is only **1024×528** CSS px. Always check layouts with `MY_LEDGER_VIEW=1024x528@1.875`; 1280×720 was a wrong guess used up to v3.6.0. WebView2 multiplies the text size into the scale, unlike page zoom, which leaves `screen.width` alone.
- Short screens: the `@media (max-height: 860px)` sections and the extra-compact `@media (max-height: 640px)` one (spacing only, never text size) in `style.css` compact headers, filters, rows and dialogs. List pages fill the window (`.page.fill`, `.table-card`), and list dialogs use `cls="listdlg"` so their table takes the remaining height. Her targets: 10+ rows per list and 15+ per report at 標準, with every column visible without sideways scrolling. Check with the `audit` and `mom` scenes after any UI change, and look at the screenshots (a dropdown can be "open" but off-screen).
- Toasts ending in 「（Ctrl+Z 可復原）」 get a 復原 button. Updates are checked on open and every 4 h; 稍後再說 turns into a sidebar 「有新版本」 pill. There is a three-slide tour (`v3_tour_done`) and a 「已更新到…」 dialog on first start of a new version (`whats_new`, keyed by `last_seen_version`).
- Unsaved input (v3.9.0): form dialogs pass `guard=${[...form values]}` to `Dialog`. If the user touched the body and the JSON differs from the opening state, Esc, the backdrop, ✕ and (via `modal.tryClose`) 取消 ask first, and closing the window asks through `window.__unsaved`/`__askQuit`. **Every new form dialog must pass `guard`**; leave out values that load by themselves, or it will ask for nothing. Never name a CSS rule with a bare generic class (`.wide`, `.todo`, `.note`): they have clashed more than once, so scope it.
- 側邊欄 can collapse to icons (Ctrl+B, `data-side` on `<html>`, kept in localStorage). 總覽 must show net worth, month figures, reminders and recent vouchers on the first 1024×528 screen. 設定 is split into tabs (`TABS` in `settings.js`); texts elsewhere refer to them as 「設定 → 收支分類」 and 「設定 → 資料管理與備份」.
- `window.__t` hooks drive `devshots.py`; `screenshot.py` captures only our own window with PrintWindow (placed off-screen, unfocused), never the screen. JS errors are written to `錯誤紀錄.log`.
- New `core`/`desktop` modules must be added to `hidden` in `packaging/myledger.spec`.

## Accounting core (`core/`)

**Data layer (`core/database.py`).** All accounting is derived from three SQL views. `v_acc_post` holds account postings in the original currency, `v_cat_post` holds income/expense postings in base currency, and `v_special_post` holds the 7101 評價, 7201 兌換, 7301 處分 and 3102 淨值調整 postings. Void vouchers are excluded everywhere. Reports never hand-sum the transactions tables.

- **Signed balances:** assets are positive, liabilities negative. Debit means the signed balance increases.
- **Voucher types:** income, expense, transfer and adjust are single-row types. `journal` stores multi-line 借/貸 in `txn_lines`, in base currency, with each account line's original-currency amount in `orig`.
- **FX:** foreign accounts are revalued at the current rate, and the difference goes to 兌換損益. This keeps the trial balance balanced.
- **Chart of accounts:**
  - Asset/liability 科目 are rows in `accounts`; their `category` (e.g. 短期投資 or 長期投資) decides 流動 vs 非流動.
  - Income/expense 科目 are rows in `categories`.
  - Both have a stored `code`: auto-assigned by prefix (11/12/21/22/41/51) or user-defined and validated (`validate_code`).
  - The fixed system 科目 live in `SPECIALS` plus 3101.
  - `chart_of_accounts()` is the single list the UI uses.
- **Ledgers:** `ledger(account_id)` (accounts, original currency) and `subject_ledger(key)` for any 會計科目 (`ledger_subjects()`: accounts, categories, `SPECIALS`, 3101). Income, expense and special 科目 start each period at 0, so every closing balance equals the trial balance (tested on every fixture). Used by the 分類帳 tab, 總分類帳 printing and the Excel 分類帳 sheet.
- **Journals need no account line** (her request, v3.7.0): `transactions.account_id` is then NULL, as for closing vouchers; never INNER JOIN accounts for journals.
- **Immutability:** records are voided or reversed, never deleted. A closing date (`closed_until`) locks earlier periods. Every change is written to `audit_log`.
- **Voucher numbers** are `V` + `transactions.id`. `Investments.rebuild()` reinserts regenerated system vouchers with their old ids (matched by date + note, then by order within the day), so numbers, reconciliation marks and attachments survive a rebuild. Only vouchers that are no longer needed disappear.
- **Equity is perpetual:** 期初淨值 is net worth the day before a period starts (`equity_opening`), so every period already starts "closed". 年度結帳 (`close_year`) still records a closing entry (`source = 'close:<year>'`, special line `closing` = 3201 本期損益) for the 日記簿 and locks the year. The views exclude `close:%` vouchers so reports never change, and any code that reads `txn_lines` directly must skip them too (e.g. the Excel 收支明細). Moving `closed_until` earlier (`set_closed_until`) voids later closing entries; `refresh_year_closings()` regenerates stale ones after a system rebuild.
- **Trial balance** is six-column (`open_*`, `period_*`, closing `debit`/`credit`); each pair must balance. `equity_statement()` is the 權益變動表.
- **Schema:**
  - `SCHEMA_VERSION` is currently 9.
  - `_open()` copies the DB to `理財帳本_升級前備份_v<N>.db`, then runs migrations in order (`_migrate_v1_to_v2`, `_migrate_v2_to_v3`, `_migrate_v4_to_v5`, `_migrate_v7_to_v8`, `_migrate_v8_to_v9`) **before** `executescript(_TABLES)`.
  - The ALTERs are guarded by `PRAGMA table_info`.
  - v5 adds `txn_lines.price` (unit price on investment journal lines) and `securities.fee_rate`/`fee_min`/`tax_rate` (ETF codes starting `00` get 0.1% tax, other stocks 0.3%). v6 and v7 have no new columns; they only trigger the restate (v6 removes the old sale-reversal vouchers, v7 the journal-sell cost adjustments). v8 adds `securities.type_name` (filled when a security's rates exactly match a default type) and its restate merges valuation vouchers per date.
  - v9 adds the `txn_tags` table (標籤／專案) only; no restate.
  - `_restate_investments` runs at the end of `_open()` for any DB older than `RESTATE_BELOW` (8), because it needs the views. A schema bump that changes no investment rule must not raise `RESTATE_BELOW`. It rebuilds all investment system vouchers, including closed periods, and reattaches reconciliation marks and attachments. `user_version` stays 4 until it finishes, so an interrupted upgrade only repeats the rebuild.
  - `_ensure_codes()` then fills any missing 科目代號.

**Investment sub-ledger (`core/investments.py`).**
- Holdings are never stored. `replay(sid)` recomputes shares, average cost, realized gains and the vouchers each event implies, from two sources: `sec_events` (buy, sell, dividends, prices) plus **journal lines linked to a security** (`txn_lines.security_id`/`shares` → events `jbuy`/`jsell`; on an **income** category line such as 4104 股利 → `jdiv`, with `shares` = shares held and `price` = dividend per share, counted in that security's dividends and creating no voucher).
- `rebuild(sid, from_date)` deletes and regenerates the system vouchers (`transactions.source = 'inv:<sid>'`) from that date. Those vouchers are read-only in the UI.
- `Database._sync_securities()` (lazy-imports Investments) runs replay as validation, and rolls back on errors such as overselling. Then it runs rebuild after any journal add, update, void, unvoid, reverse or delete that touches a linked security.
- Valuation is manual only: buys, sells and stock dividends never create valuation vouchers. Only a `price` event (投資管理 → 市價評價: a date and market price she enters) does. Since v2.5.0 (her request) a sale does **not** reverse the valuation booked on the shares sold: `val_adj` stays in the investment account until the next 市價評價 adjusts the whole holding. A fully sold security with leftover `val_adj` still shows in `holdings()` (0 shares) and 市價評價 zeroes it automatically.
- Journal sells (v2.6.0, her request): if the voucher has her own 處分投資損益 (7301) line, the system creates **no** voucher and the cost removed is exactly what she credited to the investment account (she may use FIFO/specific cost; the remaining holding's cost absorbs the difference). Only a sell credited at net proceeds with no 7301 line still gets the average-cost split voucher. A sold-out security with leftover cost or `val_adj` stays in `holdings()`; its 市價評價 zeroes it (cost residual → 7301, valuation → 7101).
- Valuation vouchers (v2.7.0, her request): all `price` events on one date share **one** voucher, `source = 'inv:val'`, one line pair per security with the security/price as memo. `rebuild(sid)` regenerates per-security vouchers (`inv:<sid>`, buys/sells/dividends) and then `_rebuild_valuations(from_date)` regenerates the shared ones for all securities, reusing the lowest old voucher id of that date.
- Security types (股票, ETF, …, each with fee rate, min fee, tax rate) are JSON in the `security_types` setting (`Investments.security_types`, default `DEFAULT_SECURITY_TYPES`); editing a type re-rates its securities (`save_security_types`). 投資管理 → 標的設定 edits any security.
- System (`inv:`) vouchers can be deleted from 收支明細 or the opened voucher: `Investments.delete_vouchers` maps each voucher to its `sec_events` rows (`voucher_events`; an `inv:val` voucher maps to every price event of its date) and deletes the event, all-or-nothing.
- Journal sells: fee/tax shown = shares × unit price − net proceeds, where net proceeds = credit to the investment account + 處分投資損益 (7301) booked in the same voucher.
- Valuation is at the **estimated net sale price**: price × shares − estimated sell fee − securities tax. So 未實現損益 already includes trading costs, as she asked; cost already includes the buy fee because she debits it into 1201/1202.
- Fees come from `trade_costs()` using the security's rates. They are rounded **down** to the yuan (Taiwan broker practice) with a minimum fee. Changing a security's rates rebuilds its valuation vouchers and is refused if a valuation falls in a closed period.
- Invariant: an investment account's balance equals the book value of its holdings, i.e. cost + booked valuation (`state["market_value"]`; `tests/test_core.py::investment_accounts_match`).

**Other modules:**
- `analytics.py`: cash flow (direct method, self-checking) and tax summary. The 退休規劃 page was removed in v2.3.0; its settings keys (`birth_year`, `retire_params`, `allocation_targets`) are left in old DBs untouched.
- `statements.py`: comparative statements and ratios, shared by the 財務報表 page and printing. `COMPARE_MODES` = 不比較 / 與上一期比較 (資產負債表 vs the day before the period starts; 收支損益表 vs the previous period of the same length, whole months shift by months) / 與去年同期比較. `balance_sheet`, `income_statement` and `ratios` return rows with `cur`/`prev`; the page's 比較 selectors persist as `report_compare_bs`/`report_compare_is`, printing as `print_compare`.
- `performance.py`: 總報酬率 and 年化報酬率 (XIRR). `Investments.replay` records investor cash flows in `state["flows"]` (buys −cost, sells +net proceeds, cash dividends +net of 補充保費, journal buys/sells/dividends too); the terminal value is the book value. Total gain = realized + dividends + unrealized (tested). XIRR is shown only after one full year of holding (`MIN_YEARS`). The portfolio converts foreign securities at the account's current rate. Shown in 投資管理 → 報酬分析 and in the 財務比率 block (up to min(period end, today)).
- `fmt.py`: number/money/date formatters.
- `printing.py`: `Report` builds print HTML (vouchers with sign-off boxes, 日記簿, 總分類帳, six-column 試算表, statements (比較資產負債表／比較收支損益表 when `build(..., compare=)` is set), 權益變動表, 財務比率分析, 現金流量表, 年度財務報告). The UI previews it in an iframe and prints through Edge (「另存為 PDF」); `<thead>` repeats per page.
- `exporter.py`: a 13-sheet Excel workbook with live formulas and ✓ balance checks, including 分類帳. She picks sheets in the export dialog (`SHEET_INFO`); an unselected sheet that a selected one references (`SHEET_DEPS`) is kept hidden so the formulas still work.
- `importer.py`: Excel/CSV import.
- `online.py`: GitHub release lookup for updates, plus optional closing prices and exchange rates (**off by default**; manual entry must always work).
- **Tags (標籤／專案, v2.11.0):** `txn_tags(txn_id, tag)`. Only user vouchers can be tagged (`source = ''`), and tagging is allowed in closed periods because it never changes amounts. Use `add_transaction`/`add_journal`/`update_*` with `tags=`, or `set_tags`/`add_tag`/`remove_tag_from`/`rename_tag`/`delete_tag`. `tag_summary`/`tag_categories` sum `v_cat_post`, the same source as the 收支損益表. The UI has a 標籤 field in 記一筆 and 複式分錄, a 收支明細 tag filter plus right-click 加上標籤, the 財務報表 → 標籤／專案 tab, search matching and an Excel 收支明細 column M. `delete_transactions` also deletes tags.
- **Undo (復原, Ctrl+Z, v2.11.0):** `Database.undo_stack` is in memory for this session only; it is cleared by `reset_all`/`restore_from`/sample data. `_record` is called by add/update/void/unvoid, tags, recurring post/skip and `Investments.add_event`/`delete_event`/`delete_vouchers`; `undo_group` merges a batch (import, multi-void, 市價評價). `core/undo.py` applies it: an added voucher is **voided** (never deleted), an edit is restored from its snapshot, voids are unvoided (with reconciliation marks), and investment events are deleted or re-inserted with their old id. Every step is logged, plus a 「復原」 audit row. System code (rebuilds, `inv:`/`close:` vouchers) is not recorded. The UI asks before undoing.
- `backup.py`: 第二份備份 (設定 → 資料管理與備份) to a USB drive or OneDrive folder (`backup_extra_dir`), into a `我的理財帳本備份` subfolder: one `帳本備份_YYYYMMDD.db` per day (overwritten, last 30 kept), plus new attachment files (never deletes there). It runs on the first launch of the day (`desktop/run.py`) and on close when the session changed data (the window's `closing` handler). Failures only set `backup_extra_error`; 設定 shows the status and 總覽 reminds her after 7 days without success.
- 年度財務報告 (`printing.Report.annual(year, sections)`, `ANNUAL_SECTIONS`, the 財務報表 header button): a cover with key figures and contents, then 年度摘要 (prior year, expense ranking, budgets), 比較資產負債表／收支損益表 (`prior_year` when there is earlier data), 權益變動表, 現金流量表 (`Report.cashflow`, also in `REPORTS`), 財務比率, 月度收支, 投資績效, 標籤彙總, 報稅參考, and optionally the trial balance and 日記簿. Sections are remembered in `annual_sections`.
- `search.py`: 全域搜尋 (Ctrl+F or the sidebar button). It finds vouchers, 科目, securities and recurring entries. Space-separated tokens are ANDed. A token is typed by shape: `V000123` is a voucher number, `2025-03` or `114/3/5` (民國) is a date prefix, a number matches amounts/prices/shares or a code, and anything else matches text (notes, memos, names, attachment names, void reasons). Opening a result goes to the voucher, an account's 分類帳, a category's 收支明細, a security's 交易紀錄 or the recurring entry. It is read-only.
- Updates (`desktop/api_update.py` + `core/online.py` + `core/updater.py`): checked on open and every 4 h while open (`update_auto`, default on; `update_last_check_at`; `update_skip` silences one version). `online.fetch_latest_release()` reads the GitHub latest release, and the asset `digest` gives the SHA-256. 「立即更新」 (frozen exe only) downloads next to the exe and verifies it, backs up the ledger to `自動備份/更新前備份_v<old>_<time>.db`, renames the running exe to `.old`, moves the new one into place and restarts with PyInstaller env vars cleared (`PYINSTALLER_RESET_ENVIRONMENT`). `cleanup_old_exe()` deletes the `.old` on the next start. If the folder is not writable, the new exe goes to 下載 and she replaces it by hand. This depends on the release asset staying named `MyLedger.exe`.

**Assistant features (v3.5.0, `desktop/api_tools.py`, `desktop/ui/dialogs/tools.js`).** All stored as JSON settings, no schema change:
- `core/monthclose.py`: 月結小幫手 steps (recurring posted, bank accounts reconciled since month start, holdings valued within 10 days of month end are auto-checked; budget/health/report are ticked by her). Progress in `month_close` ({ym: {checked, finished}}); the once-a-month startup prompt uses `month_close_prompted`.
- `core/reminders.py`: 到期提醒中心. Custom reminders in `reminders` (once/monthly/yearly; monthly clamps to month end) plus derived events (定存 maturities, next recurring date, May tax season). `upcoming()` feeds the 總覽 「近期行事曆」 card; urgent ones (within `lead` days) also go to 提醒事項.
- `core/health.py`: 資料健康檢查 (integrity_check, trial balance pairs, every voucher balanced, investment accounts = book value, backups, due recurring, unreconciled > 60 days, stale valuations, missing attachments, year-end close hint). Records `health_last`. `printing.Report.health()` prints it.
- `core/quick.py`: 快速記帳 chips (`frequent`: same note+category ≥ 2 times in 180 days) and note → category/account hints, returned by `txn_form` for new entries only.
- `core/bankmatch.py`: 智慧對帳 reads a bank Excel/CSV (date + 金額 or 存入/提出, optional 餘額), matches by equal amount within ±3 days one-to-one (tries both signs for card statements); the 銀行對帳 dialog only pre-ticks, she still saves.
- `printing.Report.monthly(ym)`: one-page 月報 (財務報表 header button, also step 6 of 月結).
- `core/forecast.py` (v3.6.0): 現金流預測. Projects liquid accounts (現金/銀行存款/外幣存款/信用卡, plus any account a projected item touches) from recurring entries (overdue ones count as today) and custom reminders that have both an amount and `account_id` (除息 = inflow, others outflow). 定存 maturities are listed but not applied. Warns below `forecast_low` (default 10,000 base currency); warnings within 60 days go to 總覽 提醒事項. Invariant (tested on every fixture): start + Σ event amounts = end for each account.
- 意見回饋 (v3.6.0, the chat icon next to ⏻ in the sidebar, badge = pending count): she can collect several items over time (drafts in `<data>\意見回饋\待傳送\items.json` + `<id>.png`), each with tag, note, page name and a screenshot taken **before** the dialog opens (`feedback_capture`, PrintWindow of our window only). 「產生 PDF」 draws A4 pages on a canvas in JS (cover list, one page per item with screenshot, diagnostics page with version/Windows/window size/font/counts/last error-log lines, no amounts), and `feedback_pdf` writes them with `core/pdfimages.py` (stdlib-only JPEG→PDF, so no CJK font needed) to `<data>\意見回饋\意見回饋_<time>.pdf`, clears the drafts and copies the file to the clipboard (file drop list via pythonnet, STA thread) so Ctrl+V in LINE attaches it. Never uploads anything: the repo is public and a token in the exe could be extracted. Tests stub `_copy_file` so they never touch the real clipboard.
- Scenes: `MY_LEDGER_SCENES=features` screenshots all of these (標準 and 大); clipboard copying is skipped whenever `MY_LEDGER_SHOT` is set.

**Ledger flow features (v3.8.0).** No schema change:
- Drill-down: `trial_balance` rows, `statements` rows and the 權益變動 rows carry a `key` (`account:`/`category:`/`special:`/`equity:`); `Reports.toLedger(key)` opens the 分類帳 for the same period and 「← 回到…」 restores the tab and scroll. Every linked figure equals that ledger's closing balance (tested on every fixture). `ledger_html` / `ledger_export` print or export one 科目.
- 定期分錄: `recurring.data` with `type: "journal"` and normalized `lines` (`recurring_journal_data`); lines with a security, or on an account that has securities, are refused. `post_recurring_journal` posts (optionally edited, on another date; `due` keeps the reminder date) inside one undo group. Any code reading `recurring.data` must handle this type.
- `quick.journals` / `note_key` (digits and months stripped) suggest the last voucher with the same 摘要; `journal_reuse` clears shares, prices and amounts when the voucher has securities. Offered, never auto-filled. `txn_copy` keeps the security link.
- `core/pricepaste.py`: parses pasted 代號／價格 for 市價評價. A number counts as a code only in first position or when it clearly is one, so `1234 ⇥ 2330` is never read as 2330. Only fills the fields; flags jumps over 30%.
- `core/yearclose.py`: 年度結帳小幫手 steps and progress (`year_close_progress`); 總覽 reminder 12/15–3/31. `year_close` backs up to 自動備份 first.
- Scenes: `MY_LEDGER_SCENES=flow`, plus (v3.9.0) `guard` (unsaved-input checks, prints GUARD ALL PASSED) and `xl` (特大 and dark). `MY_LEDGER_CLOSE_TEST` + `MY_LEDGER_CLOSE_DIRTY=1` tests closing the window with unsaved input. Scenes close dialogs with `__t.closeTop()`, which never asks; use `REAL_ESC` to test the real key. PrintWindow sometimes returns a stale frame; the scene prints the open dialog titles so check those before suspecting the UI.

**User data.**
- Everything is under `文件\我的理財帳本\`:
  - `理財帳本.db`
  - `自動備份\` (one copy on the first launch each day, last 30 kept)
  - optional second copy elsewhere (`backup.py`)
  - `匯出報表\`
  - `憑證附件\`
- The app has no background process.
- A fresh install starts empty; sample data loads only if she chooses it (`sample_data.py`).

## Release checklist (avoid crashes in the new release)

1. **Migrations:** if you change the schema, bump `SCHEMA_VERSION`, add a guarded `_migrate_vN_to_vN+1`, and add a migration test like `test_migration_v2_codes`. Never put an index or view on a new column into `_TABLES`/`_VIEWS` unless the migration adds that column first.
2. **Tests:** run `tests/test_api.py` and `tests/test_core.py` on Windows.
3. **Packaging:** build from `packaging/myledger.spec`. It excludes `PySide6`, `tkinter`, `unittest`, `numpy`, `PIL` and others; importing one of them from `core/` or `desktop/` works in dev but crashes the exe, so update `excluded` if you need one.
4. **Old data still loads (required for every change):**
   - `tests/fixtures/ledger_<tag>.db` is a realistic ledger built by that release's own code, saved with its books snapshot (`.json`).
     - `test_core.py::test_old_version_ledgers_load` opens each fixture with the current code and requires everything to match, except investment balances under `APPROVED_INVESTMENT_CHANGES`, which must still equal the holdings' book value. It also checks the books balance and that the upgrade backup exists.
     - `test_api.py` runs every read method on every fixture and cross-checks the numbers against `core/`, plus every write path with `check_books`.
     - **After tagging a release that changes the schema or the accounting**, run `python3 tools/make_fixtures.py <tag>` and commit the new `ledger_<tag>.*` (it extracts `app/` from tags up to v3.4.1 and `core/` after that). If a future change intentionally alters her numbers, add it to `APPROVED_INVESTMENT_CHANGES` (or extend that mechanism) and say so in the PR; never regenerate old fixtures to make a test pass.
     - `tests/fixtures/ledger_tools.py` must keep working with every old version's code, so use only APIs every release has.
   - **Expected differences:** only a change she explicitly asked for may differ, and the PR must list it.
   - **Smoke-test the exe:** `tools/smoke.py` runs it with `MY_LEDGER_SMOKE_DIR` on a fresh data dir and on a copy of every fixture (4 at a time, about 40 s). Every page must render, no `錯誤紀錄.log` may appear, and a schema upgrade must create `理財帳本_升級前備份_v<N>.db`.
5. **Layout:** run the `audit` and `mom` scenes with `MY_LEDGER_VIEW=1024x528@1.875` (her screen) and at 1280×720, and look at the screenshots.
6. **Version and release:** write the release's user-facing notes (Traditional Chinese, for her) in `desktop/whatsnew.md`; the same text appears in the update dialog and in 「已更新到…」. Bump `APP_VERSION` (`core/version.py`) and `packaging/version_info.txt`. Tag `vX.Y.Z` (push with `git push origin refs/tags/vX.Y.Z`) and publish only the exe, as `MyLedger.exe`: `gh release create vX.Y.Z MyLedger.exe --notes-file desktop/whatsnew.md --verify-tag`. Keep that name so `releases/latest/download/MyLedger.exe` stays valid.
7. **Self-update still works:** before publishing, check the updater code path is unchanged or re-tested. After publishing, run the previous release's exe (downloaded from GitHub) in a scratch folder, update it, and confirm it swaps to the new exe (SHA-256 matches the release `digest`), backs up the ledger, restarts and deletes the `.old`.
