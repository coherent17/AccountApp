"""投資管理：持股、交易紀錄、已實現損益、報酬分析、標的設定、買賣股利、市價評價、更新匯率。"""

from __future__ import annotations

import datetime as dt

from core.database import CURRENCIES, INVESTMENT_CATEGORIES
from core.investments import ETF_TAX, FEE_MIN, FEE_RATE, KIND_LABELS, Investments, default_tax_rate

from desktop.rpc import exposed


def _sec(s: dict) -> dict:
    return {k: s[k] for k in ("id", "code", "name", "account_id", "note", "fee_rate", "fee_min", "tax_rate",
                              "type_name", "archived") if k in s} | {
        "account_name": s.get("account_name", ""), "currency": s.get("currency", ""),
        "label": f"{s['code']}　{s['name']}".strip()}


class InvestApi:
    def _inv(self) -> Investments:
        return Investments(self._db)

    def _data_range(self, inv: Investments) -> list[str]:
        dates = [e["date"] for e in inv.events()]
        today = dt.date.today().isoformat()
        return [min(dates) if dates else today, max(dates + [today])]

    @exposed
    def invest_page(self, as_of: str | None = None) -> dict:
        db, inv = self._db, self._inv()
        rng = self._data_range(inv)
        as_of = as_of or rng[1]
        hold = inv.holdings(as_of)
        rates = {a["id"]: a["rate"] for a in db.list_accounts(include_archived=True)}
        mv = sum(h["market_value"] * rates.get(h["account_id"], 1) for h in hold)
        cost = sum(h["cost"] * rates.get(h["account_id"], 1) for h in hold)
        y = dt.date.today().year
        ps = inv.period_summary(f"{y}-01-01", f"{y}-12-31")
        return {
            "as_of": as_of, "latest": rng[1], "range": rng,
            "market_value": mv, "cost": cost, "unrealized": mv - cost,
            "realized_year": ps["realized"], "dividends_year": ps["dividends"], "nhi_year": ps["nhi"],
            "holdings": [{k: h[k] for k in ("id", "code", "name", "shares", "avg_cost", "price", "price_date", "cost",
                                            "market_value", "unrealized", "return_pct", "currency", "account_id")}
                         | {"base_value": h["market_value"] * rates.get(h["account_id"], 1)} for h in hold],
            "securities": [_sec(s) for s in inv.list_securities(include_archived=True)],
            "has_invest_account": any(a["kind"] == "asset" and a["category"] in INVESTMENT_CATEGORIES
                                      for a in db.list_accounts()),
        }

    @exposed
    def invest_events(self, sid: int | None, start: str, end: str) -> list[dict]:
        rows = [e for e in self._inv().events(sid) if start <= e["date"] <= end]
        return [{"id": e["id"], "txn_id": e.get("txn_id"), "date": e["date"], "kind": e["kind"],
                 "kind_label": KIND_LABELS.get(e["kind"], e["kind"]), "code": e["code"], "name": e["sec_name"],
                 "shares": e["shares"], "price": e["price"], "fee": (e["fee"] or 0) + (e["tax"] or 0),
                 "amount": e["amount"], "nhi": e["nhi"], "cash": e["cash_name"] or "", "note": e["note"] or ""}
                for e in reversed(rows)]

    @exposed
    def invest_realized(self, start: str, end: str) -> dict:
        ps = self._inv().period_summary(start, end)
        return {"realized": ps["realized"], "dividends": ps["dividends"], "nhi": ps["nhi"],
                "rows": [{k: r.get(k) for k in ("date", "code", "name", "shares", "proceeds", "cost", "gain")}
                         for r in ps["realized_rows"]]}

    @exposed
    def invest_performance(self, as_of: str | None = None) -> dict:
        from core.performance import portfolio_performance
        inv = self._inv()
        as_of = as_of or max(dt.date.today().isoformat(), self._data_range(inv)[1])
        p = portfolio_performance(inv, as_of)
        keys = ("invested", "value", "realized", "dividends", "unrealized", "gain", "total_return", "xirr", "years")
        rows = sorted(p["rows"], key=lambda r: (r["shares"] <= 1e-9, r["code"]))
        return {"as_of": as_of, "total": {k: p["total"].get(k) for k in keys + ("first_date",)},
                "rows": [{"id": r["id"], "code": r["code"], "name": r["name"], "shares": r["shares"],
                          **{k: (r[k] * r.get("rate", 1) if k in ("invested", "value", "realized", "dividends",
                                                                  "unrealized", "gain") else r.get(k))
                             for k in keys}} for r in rows]}

    # ------------------------------------------------------------------ 標的設定
    @exposed
    def security_form(self, sid: int | None = None, account_id: int | None = None) -> dict:
        db, inv = self._db, self._inv()
        accs = [a for a in db.list_accounts() if a["kind"] == "asset"]
        accs.sort(key=lambda a: (a["category"] not in INVESTMENT_CATEGORIES, a["id"]))
        sec = inv.get_security(sid) if sid else None
        return {"security": _sec(sec) if sec else None,
                "accounts": [{"id": a["id"], "label": f"{a['name']}（{a['category']}）",
                              "invest": a["category"] in INVESTMENT_CATEGORIES} for a in accs],
                "account_id": sec["account_id"] if sec else account_id,
                "types": inv.security_types(),
                "defaults": {"fee_rate": FEE_RATE, "fee_min": FEE_MIN, "etf_tax": ETF_TAX}}

    @exposed
    def default_tax(self, code: str) -> float:
        return default_tax_rate(code)

    @exposed
    def security_save(self, data: dict, sid: int | None = None) -> dict:
        inv = self._inv()
        rates = {"fee_rate": round(float(data["fee_rate"]), 6), "fee_min": float(data["fee_min"]),
                 "tax_rate": round(float(data["tax_rate"]), 6), "type_name": data.get("type_name") or ""}
        if sid:
            inv.update_security(sid, data.get("code", ""), data.get("name", ""), data.get("note", ""), **rates)
        else:
            if not data.get("account_id"):
                raise ValueError("請先到「帳戶管理」新增投資帳戶（例如：證券戶）")
            sid = inv.add_security(data["account_id"], data.get("code", ""), data.get("name", ""),
                                   data.get("note", ""), **rates)
        return {"id": sid, "name": data.get("name", "")}

    @exposed
    def security_types_save(self, rows: list[dict]) -> list[str]:
        return self._inv().save_security_types(rows)

    @exposed
    def security_archive(self, sid: int, archived: bool) -> None:
        inv = self._inv()
        if archived and abs(inv.replay(sid)["shares"]) > 1e-9:
            raise ValueError(f"「{inv.get_security(sid)['name']}」還有持股，無法封存")
        inv.archive_security(sid, archived)

    # ------------------------------------------------------------------ 買進、賣出、股利
    @exposed
    def trade_form(self, sid: int | None, date: str) -> dict:
        db, inv = self._db, self._inv()
        secs = [_sec(s) for s in inv.list_securities()]
        sid = sid if any(s["id"] == sid for s in secs) else (secs[0]["id"] if secs else None)
        if not sid:
            return {"securities": secs, "security": None}
        s = inv.get_security(sid)
        cash = [{"id": a["id"], "name": a["name"]} for a in db.list_accounts()
                if a["currency"] == s["currency"] and a["id"] != s["account_id"] and a["kind"] == "asset"
                and a["category"] not in INVESTMENT_CATEGORIES]
        st = inv.replay(sid, date)
        return {"securities": secs, "security": sid, "currency": s["currency"], "cash": cash,
                "last_cash": inv.last_cash_account(sid),
                "state": {k: st[k] for k in ("shares", "avg_cost", "price")}}

    @exposed
    def trade_fees(self, sid: int, kind: str, shares: float, price: float) -> list[float]:
        return list(self._inv().fees_for(sid, kind, shares or 0, price or 0))

    @exposed
    def suggest_nhi(self, amount: float) -> float:
        return Investments.suggest_nhi(amount or 0)

    @exposed
    def trade_save(self, sid: int, kind: str, d: dict) -> str:
        self._inv().add_event(sid, kind, d["date"], shares=d.get("shares") or 0, price=d.get("price") or 0,
                              fee=d.get("fee") or 0, tax=d.get("tax") or 0, amount=d.get("amount") or 0,
                              nhi=d.get("nhi") or 0, cash_account_id=d.get("cash"), note=d.get("note") or "")
        return KIND_LABELS[kind]

    @exposed
    def event_delete(self, eid: int) -> None:
        self._inv().delete_event(eid)

    # ------------------------------------------------------------------ 市價評價
    @exposed
    def price_form(self, date: str) -> list[dict]:
        return [{"id": h["id"], "code": h["code"], "name": h["name"], "shares": h["shares"], "price": h["price"],
                 "market_value": h["market_value"], "sold": h["shares"] <= 1e-9}
                for h in self._inv().holdings(date)]

    @exposed
    def price_paste(self, text: str, date: str) -> dict:
        """把從 Excel 複製的「代號、價格」對應到持股（只解析，不寫入）。"""
        from core import pricepaste
        return pricepaste.parse(text or "", [{"id": h["id"], "code": h["code"], "name": h["name"], "price": h["price"],
                                              "sold": h["shares"] <= 1e-9} for h in self._inv().holdings(date)])

    @exposed
    def price_save(self, date: str, prices: list[list]) -> int:
        inv = self._inv()
        prices = [(int(sid), float(p)) for sid, p in prices if p]
        sold = [h for h in inv.holdings(date) if h["shares"] <= 1e-9]
        if not prices and not sold:
            raise ValueError("請至少輸入一檔的市價")
        n = inv.set_prices(prices, date)
        for h in sold:   # 已全數賣出、仍有評價調整的標的：評價歸零（股數為 0，價格不影響金額）
            inv.add_event(h["id"], "price", date, price=inv.last_price(h["id"]) or 1.0, note="已全數賣出，剩餘評價歸零")
            n += 1
        return n

    @exposed(db=False)
    def fetch_prices(self) -> dict:
        from core import online
        try:
            return {"prices": {k: v[1] for k, v in online.fetch_tw_prices().items()}, "source": online.PRICE_SOURCE}
        except online.OfflineError as e:
            raise ValueError(str(e)) from None

    # ------------------------------------------------------------------ 匯率
    @exposed
    def rate_form(self) -> list[dict]:
        db = self._db
        accs = [a for a in db.list_accounts() if a["currency"] != db.base_currency]
        out = {}
        for a in accs:
            out.setdefault(a["currency"], {"code": a["currency"], "name": CURRENCIES.get(a["currency"], (a["currency"],))[0],
                                           "rate": a["rate"], "accounts": []})["accounts"].append(a["name"])
        return sorted(out.values(), key=lambda x: x["code"])

    @exposed
    def rate_save(self, rates: dict) -> None:
        db = self._db
        for a in db.list_accounts():
            if a["currency"] in rates and a["currency"] != db.base_currency:
                if float(rates[a["currency"]]) <= 0:
                    raise ValueError("匯率必須大於 0")
                db.update_account(a["id"], rate=float(rates[a["currency"]]))

    @exposed(db=False)
    def fetch_rates(self, base: str) -> dict:
        from core import online
        try:
            return {"rates": online.fetch_fx_rates(base), "source": online.FX_SOURCE}
        except online.OfflineError as e:
            raise ValueError(str(e)) from None
