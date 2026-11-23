"""其他功能：定期交易、銀行對帳、匯入 Excel／CSV、全域搜尋、第一次開啟的歡迎畫面、範例資料、提醒。"""

from __future__ import annotations

import datetime as dt
import os

from core.database import TYPE_LABELS, voucher_no

from desktop.rpc import exposed

FREQ_LABELS = {"monthly": "每月", "quarterly": "每季", "yearly": "每年"}


class MoreApi:
    # ------------------------------------------------------------------ 定期交易
    @exposed
    def recurring_list(self) -> dict:
        db = self._db
        accs = {a["id"]: a["name"] for a in db.list_accounts(include_archived=True)}
        cats = {c["id"]: c["name"] for c in db.list_categories(include_archived=True)}
        upto = (dt.date.today() + dt.timedelta(days=400)).isoformat()
        rows = []
        for r in db.list_recurring():
            d = r["data"]
            nxt = db.recurring_dates(r, upto)
            rows.append({**r, "type": d["type"], "type_label": TYPE_LABELS[d["type"]],
                         "account": accs.get(d.get("account_id"), ""),
                         "target": cats.get(d.get("category_id"), "") or accs.get(d.get("to_account_id"), ""),
                         "amount": d["amount"], "freq_label": f"{FREQ_LABELS[r['freq']]} {r['day']} 日",
                         "next": nxt[0] if nxt else "", "active": bool(r["active"])})
        return {"rows": rows, "freqs": list(FREQ_LABELS.items())}

    @exposed
    def recurring_save(self, rid: int | None, d: dict) -> str:
        name, amt, t = (d.get("name") or "").strip(), d.get("amount"), d.get("type")
        if not name:
            raise ValueError("請輸入名稱")
        if not amt or amt <= 0:
            raise ValueError("請輸入金額")
        data = {"type": t, "account_id": d.get("account_id"), "amount": amt, "note": (d.get("note") or "").strip() or name}
        if t == "transfer":
            data["to_account_id"] = d.get("to_account_id")
            if data["to_account_id"] == data["account_id"]:
                raise ValueError("轉出與轉入帳戶不可相同")
        else:
            data["category_id"] = d.get("category_id")
            if not data["category_id"]:
                raise ValueError("請選擇分類")
        self._db.save_recurring(rid, name, data, d["freq"], int(d["day"]), d["start_date"], d.get("end_date") or "",
                                bool(d.get("active", True)))
        return name

    @exposed
    def recurring_toggle(self, rid: int) -> None:
        r = next(x for x in self._db.list_recurring() if x["id"] == rid)
        self._db.save_recurring(r["id"], r["name"], r["data"], r["freq"], r["day"], r["start_date"], r["end_date"],
                                not r["active"])

    @exposed
    def recurring_delete(self, rid: int) -> None:
        self._db.delete_recurring(rid)

    @exposed
    def due_list(self) -> list[dict]:
        return [{"rec_id": rec["id"], "date": date, "name": rec["name"], "type": rec["data"]["type"],
                 "type_label": TYPE_LABELS[rec["data"]["type"]], "amount": rec["data"]["amount"]}
                for rec, date in self._db.due_recurring()]

    @exposed
    def due_post(self, items: list[dict], skip: bool = False) -> dict:
        """入帳（或略過）所選的到期定期交易。items：[{rec_id, date, amount}]"""
        db = self._db
        recs = {r["id"]: r for r in db.list_recurring()}
        n, errors = 0, []
        for it in items:
            rec = recs.get(it["rec_id"])
            if not rec:
                continue
            try:
                if skip:
                    db.skip_recurring(rec, it["date"])
                else:
                    db.post_recurring(rec, it["date"], it.get("amount"))
                n += 1
            except ValueError as e:
                errors.append(f"{rec['name']}：{e}")
        return {"n": n, "errors": errors}

    # ------------------------------------------------------------------ 銀行對帳
    @exposed
    def recon_load(self, aid: int | None, date: str) -> dict:
        db = self._db
        accs = [{"id": a["id"], "name": a["name"], "kind": a["kind"]} for a in db.list_accounts()]
        aid = aid or (accs[0]["id"] if accs else None)
        if not aid:
            return {"accounts": accs, "account": None}
        acc = db.get_account(aid)
        items = db.recon_candidates(aid, date)
        book = next((a["balance"] for a in db.account_summaries(date, True) if a["id"] == aid), 0.0)
        return {"accounts": accs, "account": aid, "currency": acc["currency"], "name": acc["name"],
                "cleared": db.cleared_balance(aid), "book": book,
                "items": [{"txn_id": i["txn_id"], "date": i["date"], "voucher": i["voucher"],
                           "note": i["note"] or TYPE_LABELS[i["type"]], "effect": i["effect"]} for i in items],
                "history": db.list_reconciliations(aid)}

    @exposed
    def recon_save(self, aid: int, date: str, balance: float, ids: list[int]) -> None:
        self._db.save_reconciliation(aid, date, balance or 0, ids)

    # ------------------------------------------------------------------ 匯入
    @exposed
    def import_read(self, path: str) -> dict:
        from core.importer import FIELDS, find_header, guess_mapping, read_table
        try:
            rows = read_table(path)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"無法讀取檔案：{e}") from None
        header = find_header(rows)
        head = rows[header] if rows else []
        self._import = {"rows": rows, "header": header}
        return {"name": os.path.basename(path), "header": header, "fields": list(FIELDS.items()),
                "columns": [f"第 {i + 1} 欄：{h if h is not None else ''}" for i, h in enumerate(head)],
                "mapping": guess_mapping(head),
                "accounts": [{"id": a["id"], "name": a["name"]} for a in self._db.list_accounts()]}

    @exposed
    def import_preview(self, mapping: dict, default_acc: int | None, sign: str, create_cat: bool) -> dict:
        from core.importer import build_rows
        st = getattr(self, "_import", None)
        if not st:
            raise ValueError("請先選擇檔案")
        items = build_rows(self._db, st["rows"], st["header"], {k: v for k, v in mapping.items()}, default_acc, sign, create_cat)
        st["items"] = items
        ok = sum(1 for i in items if not i["error"])
        return {"total": len(items), "ok": ok,
                "rows": [{"row": i["row"], "error": i["error"] or "", "new_category": bool(i["new_category"]), "date": i["date"] or "",
                          "type": TYPE_LABELS.get(i["type"], ""), "category": i["category_name"] or "",
                          "account": i["account_name"] or "（預設帳戶）", "note": i["note"] or "", "amount": i["amount"] or 0}
                         for i in items[:500]]}

    @exposed
    def import_run(self) -> dict:
        from core.importer import do_import
        st = getattr(self, "_import", None)
        if not st or not st.get("items"):
            raise ValueError("沒有可以匯入的資料")
        self._db.backup_to(os.path.join(self._folder, "自動備份", f"匯入前備份_{dt.datetime.now():%Y%m%d_%H%M%S}.db"))
        n, skipped = do_import(self._db, st["items"])
        self._import = None
        return {"n": n, "skipped": skipped}

    @exposed(db=False)
    def import_template(self) -> str:
        import webview
        res = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=self._folder,
                                              save_filename="匯入範本.xlsx", file_types=("Excel 活頁簿 (*.xlsx)",))
        if not res:
            return ""
        path = res if isinstance(res, str) else res[0]
        from core.importer import write_template
        write_template(path)
        os.startfile(path)  # noqa: S606
        return path

    # ------------------------------------------------------------------ 全域搜尋
    @exposed
    def search(self, text: str) -> dict:
        from core import search
        r = search.search(self._db, text)
        return {"rows": r["rows"], "total": r["total_vouchers"], "truncated": r["truncated"]}

    # ------------------------------------------------------------------ 歡迎、範例資料、提醒
    @exposed
    def first_run(self) -> bool:
        db = self._db
        return db.get_setting("first_run_done") != "1" and not db.list_accounts(include_archived=True)

    @exposed
    def welcome_finish(self, name: str, choice: str) -> None:
        from core.sample_data import load_sample_data
        db = self._db
        db.set_setting("owner_name", (name or "").strip())
        if choice == "sample":
            load_sample_data(db)
        else:
            db.start_fresh()
        db.set_setting("first_run_done", "1")
        from core.version import APP_VERSION
        db.set_setting("last_seen_version", APP_VERSION)     # 全新安裝不需要「已更新到…」
        db.clear_undo()

    @exposed
    def clear_sample(self) -> None:
        db = self._db
        db.backup_to(os.path.join(self._folder, "自動備份", f"範例資料備份_{dt.datetime.now():%Y%m%d_%H%M%S}.db"))
        db.start_fresh()

    @exposed
    def backup_reminder(self) -> dict:
        from core import backup
        return backup.status(self._db)

    @exposed
    def voucher_label(self, tid: int) -> str:
        return voucher_no(tid)
