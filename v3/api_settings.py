"""設定：個人設定、收支分類與預算、會計科目表、結帳、網路、資料管理與備份（含第二份備份）。"""

from __future__ import annotations

import datetime as dt
import os

from app.database import (ASSET_CATEGORIES, CLOSING, CURRENCIES, EQUITY_ACCOUNT, EQUITY_CODE, EXPENSE_TAX_TAGS,
                          INCOME_TAX_TAGS, INVESTMENT_CATEGORIES, LIABILITY_CATEGORIES, NATURE_LABELS, SPECIALS,
                          TAX_TAGS, Database, voucher_no)

from v3.rpc import exposed

GROUPS = {"11": "流動資產", "12": "非流動資產", "21": "流動負債", "22": "非流動負債", "41": "收入", "51": "費用"}


class SettingsApi:
    @property
    def _backup_dir(self) -> str:
        return os.path.join(self._folder, "自動備份")

    # ------------------------------------------------------------------ 頁面資料
    @exposed
    def settings_page(self) -> dict:
        from app import backup
        db = self._db
        st = backup.status(db)
        done = db.year_closings()
        first = db.first_year() or dt.date.today().year
        cats = {k: [{"id": c["id"], "code": c["code"], "name": c["name"], "budget": c["budget"], "archived": bool(c["archived"]),
                     "tax_tag": c["tax_tag"], "tax_label": TAX_TAGS.get(c["tax_tag"], "") if c["tax_tag"] else ""}
                    for c in db.list_categories(k, include_archived=True)] for k in ("expense", "income")}
        return {
            "owner": db.get_setting("owner_name"), "base": db.base_currency,
            "currencies": [[k, f"{v[0]}（{k}）"] for k, v in CURRENCIES.items()],
            "font_scale": db.get_setting("font_scale", "large"), "theme": db.get_setting("theme_mode", "light"),
            "animations": db.get_setting("animations", "1") == "1",
            "online": db.get_setting("online_updates", "0") == "1", "update_auto": db.get_setting("update_auto", "1") == "1",
            "categories": cats,
            "tax_tags": {"income": [[t, TAX_TAGS[t]] for t in INCOME_TAX_TAGS],
                         "expense": [[t, TAX_TAGS[t]] for t in EXPENSE_TAX_TAGS]},
            "closed_until": db.closed_until, "year_closings": sorted(done),
            "close_years": [{"year": y, "done": y in done} for y in range(dt.date.today().year - 1, first - 1, -1)],
            "db_path": db.path if hasattr(db, "path") else os.path.join(self._folder, "理財帳本.db"),
            "folder": self._folder, "backup_dir": self._backup_dir,
            "extra": {"dir": st["dir"], "target": backup.target_dir(st["dir"]) if st["dir"] else "",
                      "last": st["last"], "days": st["days"], "error": st["error"], "remind": st["remind"],
                      "onedrive": backup.onedrive_dir() or ""},
        }

    @exposed
    def set_pref_setting(self, key: str, value) -> None:
        """設定頁的開關與文字（只接受這幾個鍵）。"""
        allowed = {"owner_name", "online_updates", "update_auto", "animations", "font_scale", "theme_mode"}
        if key not in allowed:
            raise ValueError("不支援的設定")
        if isinstance(value, bool):
            value = "1" if value else "0"
        self._db.set_setting(key, str(value).strip())

    @exposed
    def set_base_currency(self, code: str) -> None:
        db = self._db
        if code not in CURRENCIES:
            raise ValueError("不支援的幣別")
        db.set_setting("base_currency", code)
        for a in db.list_accounts(include_archived=True):
            if a["currency"] == code:
                db.update_account(a["id"], rate=1.0)

    # ------------------------------------------------------------------ 收支分類
    @exposed
    def category_update(self, cid: int, fields: dict) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("budget", "tax_tag", "archived")}
        if "budget" in allowed:
            allowed["budget"] = max(0.0, float(allowed["budget"] or 0))
        if "archived" in allowed:
            allowed["archived"] = 1 if allowed["archived"] else 0
        self._db.update_category(cid, **allowed)

    @exposed
    def category_move(self, cid: int, d: int) -> None:
        self._db.move_category(cid, d)

    @exposed
    def category_delete(self, cid: int) -> None:
        db = self._db
        n = db.category_txn_count(cid)
        if n:
            raise ValueError(f"「{db.get_category(cid)['name']}」已有 {n} 筆紀錄使用，無法刪除。\n可改用「隱藏」，歷史紀錄會保留。")
        db.delete_category(cid)

    # ------------------------------------------------------------------ 會計科目
    @exposed
    def subject_form(self, cid: int | None = None) -> dict:
        db = self._db
        c = db.get_category(cid) if cid else None
        return {"category": dict(c) if c else None,
                "asset_categories": ASSET_CATEGORIES, "liability_categories": LIABILITY_CATEGORIES,
                "invest_categories": sorted(INVESTMENT_CATEGORIES),
                "currencies": [[k, f"{v[0]}（{k}）"] for k, v in CURRENCIES.items()], "base": db.base_currency,
                "tax_tags": {"income": [[t, TAX_TAGS[t]] for t in INCOME_TAX_TAGS],
                             "expense": [[t, TAX_TAGS[t]] for t in EXPENSE_TAX_TAGS]},
                "default_opening": dt.date.today().replace(month=1, day=1).isoformat()}

    @exposed
    def subject_code(self, nature: str, category: str) -> dict:
        db = self._db
        prefix = db.code_prefix(nature, (category or "").strip())
        return {"prefix": prefix, "group": GROUPS[prefix], "suggest": db.next_code(prefix)}

    @exposed
    def subject_save(self, d: dict, cid: int | None = None) -> dict:
        db = self._db
        n, name, code = d["nature"], (d.get("name") or "").strip(), (d.get("code") or "").strip()
        if cid:
            if not name:
                raise ValueError("請輸入科目名稱")
            old = db.get_category(cid)
            dup = db.find_category(old["kind"], name)
            if dup and dup["id"] != cid:
                raise ValueError(f"已有同名的{NATURE_LABELS[old['kind']]}科目「{name}」")
            fields = {"name": name, "tax_tag": d.get("tax_tag") or ""}
            if code != old["code"]:
                fields["code"] = code
            if old["kind"] == "expense":
                fields["budget"] = max(0.0, d.get("budget") or 0)
            db.update_category(cid, **fields)
            return {"key": ["category", cid], "code": code, "name": name}
        if n in ("asset", "liability"):
            if (d.get("opening") or 0) < 0:
                raise ValueError("期初金額請輸入正數")
            aid = db.add_account(name, n, (d.get("category") or "").strip() or ("其他資產" if n == "asset" else "其他負債"),
                                 currency=d.get("currency") or db.base_currency, rate=1.0,
                                 opening_balance=d.get("opening") or 0, opening_date=d.get("opening_date"), code=code)
            return {"key": ["account", aid], "code": code, "name": name}
        new = db.add_category(name, n, budget=(d.get("budget") or 0) if n == "expense" else 0,
                              tax_tag=d.get("tax_tag") or "", code=code)
        return {"key": ["category", new], "code": code, "name": name}

    @exposed
    def chart(self, archived: bool = False) -> list[dict]:
        """會計科目表：依代號排列，含分組標題、餘額或本年累計。"""
        db = self._db
        chart = db.chart_of_accounts(include_archived=archived)
        bal = {a["id"]: a["base_value"] for a in db.account_summaries(include_archived=True)}
        y0, today = dt.date.today().replace(month=1, day=1).isoformat(), dt.date.today().isoformat()
        ytd = {c["id"]: c["total"] for k in ("income", "expense") for c in db.category_totals(y0, today, k)}
        cats = {c["id"]: c for c in db.list_categories(include_archived=True)}
        rows: list[dict] = []

        def add(items):
            for a in items:
                kind, ident = a["key"]
                r = {"code": a["code"], "name": a["name"], "key": list(a["key"]), "archived": bool(a["archived"]),
                     "level": 2, "amount": None, "label": ""}
                if kind == "account":
                    r["label"] = a["category"] + ("・可連結投資" if a["investment"] else "")
                    v = bal.get(ident, 0.0)
                    r["amount"] = v if a["kind"] == "asset" else -v
                elif kind == "category":
                    c = cats[ident]
                    r["label"] = TAX_TAGS.get(c["tax_tag"], "") if c["tax_tag"] else ""
                    r["amount"] = ytd.get(ident, 0.0)
                else:
                    r["label"] = "系統科目"
                rows.append(r)

        def section(code, name):
            rows.append({"code": code, "name": name, "style": "section", "level": 0})

        def sub(name):
            rows.append({"code": "", "name": name, "style": "subtotal", "level": 1})

        accs = [a for a in chart if a["key"][0] == "account"]
        section("1", "資產")
        for label, current in (("流動資產", True), ("非流動資產", False)):
            sub(label)
            add([a for a in accs if a["kind"] == "asset" and a["current"] == current])
        section("2", "負債")
        for label, current in (("流動負債", True), ("非流動負債", False)):
            sub(label)
            add([a for a in accs if a["kind"] == "liability" and a["current"] == current])
        section("3", "權益")
        rows.append({"code": EQUITY_CODE, "name": EQUITY_ACCOUNT, "label": "系統科目", "key": ["special", "opening"],
                     "level": 2, "amount": None})
        add([a for a in chart if a["key"] == ("special", "equity")])
        section("4", "收入")
        add([a for a in chart if a["kind"] == "income"])
        section("5", "費用")
        add([a for a in chart if a["kind"] == "expense"])
        section("7", "業外損益")
        add([a for a in chart if a["kind"] == "special" and SPECIALS[a["key"][1]][2] == "業外損益"])
        return rows

    # ------------------------------------------------------------------ 結帳
    @exposed
    def set_closed(self, date: str) -> None:
        if date and date > dt.date.today().isoformat():
            raise ValueError("結帳日不可晚於今天。")
        self._db.set_closed_until(date)

    @exposed
    def year_close_preview(self, year: int) -> dict:
        from app.investments import Investments
        db = self._db
        year = int(year)
        start, end = f"{year}-01-01", f"{year}-12-31"
        tb = db.trial_balance(start, end)
        diff = round(sum(r["debit"] - r["credit"] for r in tb), 2)
        due = [d for _, d in db.due_recurring(end)]
        stale = [h["name"] for h in Investments(db).holdings(end)
                 if not h["price_date"] or h["price_date"] < f"{year}-12-01"]
        checks = [(abs(diff) < 0.5, "試算表借貸平衡" if abs(diff) < 0.5 else f"試算表不平衡，差額 {diff:,.2f}"),
                  (not due, "定期交易皆已入帳" if not due else f"尚有 {len(due)} 筆 {year} 年以前的定期交易未入帳（可先到收支明細處理）"),
                  (not stale, "持股皆已於 12 月辦理市價評價" if not stale else
                   "年底前尚未評價：" + "、".join(stale) + "（可先到投資管理「市價評價」）")]
        eq = db.equity_statement(start, end)
        chart = {f"{a['key'][0]}:{a['key'][1]}": a for a in db.chart_of_accounts(include_archived=True)}
        lines = []
        for ln in db.closing_lines(year):
            key = f"category:{ln['category_id']}" if ln.get("category_id") else f"special:{ln['special']}"
            a = chart.get(key) or {"code": CLOSING[0], "name": CLOSING[1]}
            lines.append({"code": a["code"], "name": a["name"], "debit": ln["debit"], "credit": ln["credit"]})
        closed = db.year_closings()
        return {"year": year, "checks": [{"ok": ok, "text": t} for ok, t in checks], "blocked": abs(diff) >= 0.5,
                "equity": [{"name": n, "value": v} for n, v in eq["rows"]], "closing": eq["closing"], "lines": lines,
                "done": voucher_no(closed[year]) if year in closed else ""}

    @exposed
    def year_close(self, year: int) -> int:
        return len(self._db.close_year(int(year)))

    # ------------------------------------------------------------------ 備份與還原
    @exposed(db=False)
    def pick_folder(self, title: str, start: str = "") -> str:
        import webview
        res = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start or os.path.expanduser("~"))
        return (res[0] if isinstance(res, (list, tuple)) else res) if res else ""

    @exposed(db=False)
    def pick_backup_save(self) -> str:
        import webview
        name = f"理財帳本備份_{dt.datetime.now():%Y%m%d_%H%M}.db"
        res = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=os.path.join(os.path.expanduser("~"), "Desktop"),
                                              save_filename=name, file_types=("帳本備份檔 (*.db)",))
        if not res:
            return ""
        p = res if isinstance(res, str) else res[0]
        return p if p.lower().endswith(".db") else p + ".db"

    @exposed(db=False)
    def pick_restore(self) -> str:
        import webview
        res = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=self._backup_dir,
                                              file_types=("帳本備份檔 (*.db)", "所有檔案 (*.*)"))
        return (res[0] if res else "") or ""

    @exposed
    def backup_to(self, path: str) -> str:
        self._db.backup_to(path)
        return path

    @exposed
    def restore_from(self, path: str) -> None:
        if not Database.is_valid_ledger(path):
            raise ValueError("這個檔案不是帳本備份檔。")
        self._db.restore_from(path)

    @exposed
    def reset_all(self, word: str) -> None:
        if word != "清除":
            raise ValueError("已取消，資料未變更。")
        db = self._db
        db.backup_to(os.path.join(self._backup_dir, f"清除前備份_{dt.datetime.now():%Y%m%d_%H%M%S}.db"))
        db.reset_all()
        db.set_setting("closed_until", "")

    @exposed
    def extra_set(self, folder: str, confirmed: bool = False) -> dict:
        """設定第二份備份位置；同一顆硬碟時先傳回 need_confirm 讓她確認。"""
        from app import backup
        folder = os.path.normpath(folder)
        data = os.path.normpath(self._folder)
        if folder == data or folder.startswith(data + os.sep):
            raise ValueError("第二份備份不能放在帳本自己的資料夾裡，請選擇隨身碟、外接硬碟或 OneDrive。")
        od = backup.onedrive_dir()
        in_cloud = bool(od) and folder.lower().startswith(os.path.normpath(od).lower())
        if backup.same_drive(folder, self._folder) and not in_cloud and not confirmed:
            return {"need_confirm": True}
        self._db.set_setting(backup.DIR_KEY, folder)
        self._db.set_setting(backup.ERROR_KEY, "")
        return {"path": backup.run(self._db, self._folder)}

    @exposed
    def extra_run(self) -> str:
        from app import backup
        try:
            return backup.run(self._db, self._folder)
        except OSError as e:
            raise ValueError(f"第二份備份失敗：{e}") from None

    @exposed
    def extra_disable(self) -> None:
        from app import backup
        for k in (backup.DIR_KEY, backup.LAST_KEY, backup.ERROR_KEY):
            self._db.set_setting(k, "")

    @exposed
    def extra_folder(self) -> str:
        from app import backup
        d = self._db.get_setting(backup.DIR_KEY, "")
        if not d or not os.path.isdir(backup.target_dir(d)):
            raise ValueError("目前找不到這個資料夾（隨身碟是否已插上？）")
        return backup.target_dir(d)
