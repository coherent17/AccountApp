"""財務報表：資產負債表、收支損益表、現金流量表、月度收支、分類與預算、標籤／專案、日記帳、分類帳、
試算表、報稅彙總，以及列印（與 v2 相同的報表 HTML，由 Edge 列印或另存 PDF）。"""

from __future__ import annotations

from app import statements as st
from app.database import month_keys

from v3.rpc import exposed

SETTING_KEYS = {"report_compare_bs", "report_compare_is", "print_compare", "annual_sections"}


class ReportsApi:
    @exposed
    def reports_meta(self) -> dict:
        db = self._db
        lo, hi = db.date_range()
        codes = db.account_codes()
        return {"range": [lo, hi], "closed_until": db.closed_until,
                "compare_modes": st.COMPARE_MODES,
                "compare_bs": db.get_setting("report_compare_bs", "none"),
                "compare_is": db.get_setting("report_compare_is", "none"),
                "years": list(range(int(hi[:4]), int(lo[:4]) - 1, -1)),
                "accounts": [{"id": a["id"], "label": f"{codes[a['id']]}　{a['name']}", "code": codes[a["id"]]}
                             for a in sorted(db.list_accounts(include_archived=True), key=lambda a: codes[a["id"]])]}

    @exposed
    def set_setting(self, key: str, value: str) -> None:
        if key not in SETTING_KEYS:
            raise ValueError("不支援的設定")
        self._db.set_setting(key, value)

    # ------------------------------------------------------------------ 資產負債表
    @exposed
    def report_bs(self, start: str, end: str, mode: str) -> dict:
        db = self._db
        cdate = st.compare_date(mode, start, end)
        data = st.balance_sheet(db, end, cdate)
        rows, liab = [], False
        for r in data["rows"]:
            if r["style"] == "section":
                liab = r["name"].startswith("負債")
            d, dp = st.change(r["cur"], r["prev"]) if r["cur"] is not None else (None, None)
            # 增減：對淨值有利為綠色、不利為紅色（負債增加為不利）
            bad = liab and not r["name"].startswith(("淨資產", "負債及淨值"))
            rows.append({"name": r["name"], "level": r["level"], "style": r["style"], "cur": r["cur"],
                         "prev": r["prev"], "orig": r["orig"], "currency": r["currency"], "share": r["share"],
                         "change": d, "change_pct": dp, "good": None if not d else (d > 0) != bad,
                         "net": r["name"].startswith("淨資產")})
        crange = st.compare_range(mode, start, end)
        ratios = [{"name": x["name"], "help": x["help"], "cur": st.fmt_ratio(x["cur"], x["kind"], x["note"]),
                   "prev": st.fmt_ratio(x["prev"], x["kind"]) if cdate else "",
                   "change": st.fmt_ratio_change(x["cur"], x["prev"], x["kind"]) if cdate else ""}
                  for x in st.ratios(db, start, end, crange)]
        eq = db.equity_statement(start, end)
        closed = db.year_closings()
        return {"cdate": cdate, "rows": rows, "has_orig": any(r["orig"] is not None for r in rows), "ratios": ratios,
                "equity": [{"name": n, "value": v} for n, v in eq["rows"]], "equity_closing": eq["closing"],
                "closed_years": [y for y in range(int(start[:4]), int(end[:4]) + 1) if y in closed]}

    # ------------------------------------------------------------------ 收支損益表
    @exposed
    def report_is(self, start: str, end: str, mode: str) -> dict:
        crange = st.compare_range(mode, start, end)
        data = st.income_statement(self._db, start, end, crange)
        rows = []
        for r in data["rows"]:
            d, dp = st.change(r["cur"], r["prev"]) if r["cur"] is not None else (None, None)
            rows.append({**{k: r[k] for k in ("name", "level", "style", "cur", "prev", "count", "kind", "share", "code")},
                         "change": d, "change_pct": dp,
                         "good": None if not d else (d > 0) != (r["kind"] == "expense")})
        return {"crange": crange, "rows": rows}

    # ------------------------------------------------------------------ 現金流量表、報稅
    @exposed
    def report_cf(self, start: str, end: str) -> dict:
        from app.analytics import cash_flow
        cf = cash_flow(self._db, start, end)
        return {k: cf[k] for k in ("opening", "operating", "investing", "financing", "other", "op_total", "inv_total",
                                   "fin_total", "other_total", "net", "closing", "check")}

    @exposed
    def report_tax(self, year: int) -> dict:
        from app.analytics import tax_summary
        ts = tax_summary(self._db, int(year))
        return {k: ts[k] for k in ("incomes", "deductions", "realized", "realized_note")}

    # ------------------------------------------------------------------ 月度、分類、標籤
    @exposed
    def report_monthly(self, start: str, end: str) -> dict:
        mt = self._db.monthly_totals(start, end)
        keys = month_keys(start, end)
        return {"months": [{"ym": k, **mt[k]} for k in keys]}

    @exposed
    def report_categories(self, start: str, end: str, kind: str) -> list[dict]:
        rows = self._db.category_totals(start, end, kind)
        months = len(month_keys(start, end))
        total = sum(r["total"] for r in rows) or 1
        return [{"id": r["id"], "name": r["name"], "count": r["count"], "total": r["total"], "share": r["total"] / total,
                 "budget": (r["budget"] or 0) * months if kind == "expense" else 0} for r in rows]

    @exposed
    def report_tags(self, start: str, end: str) -> list[dict]:
        return self._db.tag_summary(start, end)

    @exposed
    def report_tag_detail(self, tag: str, start: str, end: str) -> list[dict]:
        return self._db.tag_categories(tag, start, end)

    @exposed
    def tag_rename(self, old: str, new: str) -> int:
        return self._db.rename_tag(old, new)

    @exposed
    def tag_delete(self, tag: str) -> int:
        return self._db.delete_tag(tag)

    # ------------------------------------------------------------------ 日記帳、分類帳、試算表
    @exposed
    def report_journal(self, start: str, end: str, kw: str = "") -> list[dict]:
        entries = self._db.journal(start, end)
        kw = (kw or "").strip()
        if kw:
            entries = [e for e in entries if kw in e["summary"] or kw in e["voucher"]
                       or any(kw in ln["name"] or kw in ln["code"] for ln in e["lines"])]
        return [{"id": e["id"], "date": e["date"], "voucher": e["voucher"], "summary": e["summary"],
                 "lines": [{k: ln[k] for k in ("code", "name", "debit", "credit")} for ln in e["lines"]]}
                for e in entries]

    @exposed
    def report_ledger(self, aid: int, start: str, end: str) -> dict:
        lg = self._db.ledger(aid, start, end)
        return {"currency": lg["account"]["currency"], "opening": lg["opening"], "closing": lg["closing"],
                "debit_total": lg["debit_total"], "credit_total": lg["credit_total"], "side": lg["normal_side"],
                "rows": [{k: r.get(k) for k in ("id", "date", "voucher", "summary", "counter", "debit", "credit",
                                                "balance")} for r in lg["rows"]]}

    @exposed
    def report_tb(self, start: str, end: str) -> list[dict]:
        return self._db.trial_balance(start, end)

    # ------------------------------------------------------------------ 列印（Edge 列印／另存 PDF）
    @exposed
    def print_options(self) -> dict:
        from app.printing import ANNUAL_SECTIONS, REPORTS
        db = self._db
        saved = db.get_setting("annual_sections", "")
        return {"reports": REPORTS, "annual": ANNUAL_SECTIONS, "compare": db.get_setting("print_compare", "none"),
                "annual_saved": [s for s in saved.split(",") if s] if saved else None,
                "first_year": db.first_year()}

    @exposed
    def print_html(self, keys: list[str], start: str, end: str, compare: str = "none") -> str:
        from app.printing import Report
        if not keys:
            raise ValueError("請至少勾選一種報表")
        return Report(self._db).build(keys, start, end, compare)

    @exposed
    def annual_html(self, year: int, sections: list[str]) -> str:
        from app.printing import Report
        return Report(self._db).annual(int(year), sections)

    @exposed
    def voucher_html(self, tid: int) -> str:
        from app.printing import Report
        return Report(self._db).build_voucher(tid)
