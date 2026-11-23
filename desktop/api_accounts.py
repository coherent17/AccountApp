"""帳戶管理：帳戶清單、新增／編輯帳戶、封存、刪除、更新餘額／市值。"""

from __future__ import annotations

import datetime as dt

from core.database import ASSET_CATEGORIES, CURRENCIES, LIABILITY_CATEGORIES

from desktop.rpc import exposed

GROUPS = {"11": "流動資產", "12": "非流動資產", "21": "流動負債", "22": "非流動負債"}


class AccountsApi:
    @exposed
    def accounts_page(self, archived: bool = False) -> dict:
        db = self._db
        accs = db.account_summaries(include_archived=archived)
        nw = db.net_worth()
        soon = (dt.date.today() + dt.timedelta(days=60)).isoformat()
        has_secs = {r["account_id"] for r in db._q("SELECT DISTINCT account_id FROM securities WHERE archived = 0")}
        out = {"assets": nw["assets"], "liabilities": nw["liabilities"], "net": nw["net"], "groups": {}}
        for kind in ("asset", "liability"):
            rows = [a for a in accs if a["kind"] == kind]
            for a in rows:      # 資產為正、負債以欠款為正；透支等反向餘額顯示負數
                a["value"] = a["base_value"] if kind == "asset" else -a["base_value"]
            total = sum(a["value"] for a in rows) or 1
            out["groups"][kind] = [{
                "id": a["id"], "code": a["code"], "name": a["name"], "category": a["category"],
                "current": db.is_current(a), "currency": a["currency"], "balance": a["balance"], "rate": a["rate"],
                "value": a["value"], "share": a["value"] / total, "maturity": a["maturity_date"] or "",
                "maturity_soon": bool(a["maturity_date"] and a["maturity_date"] <= soon),
                "note": a["note"], "interest": a["interest_rate"] or 0, "archived": bool(a["archived"]),
                "invest": a["id"] in has_secs,
            } for a in rows]
        return out

    @exposed
    def account_form(self, aid: int | None = None) -> dict:
        db = self._db
        acc = db.get_account(aid) if aid else None
        return {
            "account": dict(acc) if acc else None,
            "asset_categories": ASSET_CATEGORIES, "liability_categories": LIABILITY_CATEGORIES,
            "currencies": [{"code": k, "name": v[0]} for k, v in CURRENCIES.items()],
            "base": db.base_currency,
            "default_opening": dt.date.today().replace(month=1, day=1).isoformat(),
            "txn_count": db.account_txn_count(aid) if aid else 0,
        }

    @exposed
    def account_code_hint(self, kind: str, category: str, aid: int | None = None) -> dict:
        """依性質與類別建議代號（11 流動資產、12 非流動資產、21 流動負債、22 非流動負債）。"""
        db = self._db
        prefix = db.code_prefix(kind, (category or "").strip())
        return {"prefix": prefix, "group": GROUPS[prefix], "suggest": "" if aid else db.next_code(prefix)}

    @exposed
    def account_save(self, data: dict, aid: int | None = None) -> dict:
        db = self._db
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("請輸入帳戶名稱")
        opening = data.get("opening_balance") or 0.0
        if opening < 0:
            raise ValueError("期初金額請輸入正數（負債請改選「負債」性質）")
        fields = dict(name=name, kind=data["kind"], category=(data.get("category") or "").strip() or "其他資產",
                      currency=data["currency"], rate=float(data.get("rate") or 1), opening_balance=opening,
                      opening_date=data["opening_date"], note=(data.get("note") or "").strip(),
                      maturity_date=data.get("maturity_date") or "", interest_rate=float(data.get("interest_rate") or 0))
        if fields["rate"] <= 0:
            raise ValueError("匯率必須大於 0")
        code = (data.get("code") or "").strip()
        if aid:
            if code != db.get_account(aid)["code"]:
                fields["code"] = code
            db.update_account(aid, **fields)
        else:
            aid = db.add_account(**fields, code=code)
        return {"id": aid, "name": name}

    @exposed
    def account_archive(self, aid: int, archived: bool) -> None:
        self._db.update_account(aid, archived=1 if archived else 0)

    @exposed
    def account_delete(self, aid: int) -> None:
        db = self._db
        n = db.account_txn_count(aid)
        if n:
            raise ValueError(f"「{db.get_account(aid)['name']}」已有 {n} 筆交易紀錄，無法刪除。\n"
                             "如果不再使用，建議改用「封存」，歷史紀錄會保留。")
        db.delete_account(aid)

    # ------------------------------------------------------------------ 更新餘額／市值
    @exposed
    def adjust_info(self, aid: int | None, date: str) -> dict:
        db = self._db
        accs = [{"id": a["id"], "name": a["name"], "kind": a["kind"], "currency": a["currency"]}
                for a in db.list_accounts()]
        acc = db.get_account(aid) if aid else (db.get_account(accs[0]["id"]) if accs else None)
        if not acc:
            return {"accounts": accs, "account": None}
        signed = db.signed_balances(date).get(acc["id"], 0.0)
        invest = bool(db._q1("SELECT 1 FROM securities WHERE account_id = ? AND archived = 0", (acc["id"],)))
        return {"accounts": accs, "account": acc["id"], "kind": acc["kind"], "currency": acc["currency"],
                "current": signed if acc["kind"] == "asset" else -signed, "invest": invest}

    @exposed
    def adjust_save(self, aid: int, date: str, value: float, note: str) -> str:
        db = self._db
        acc = db.get_account(aid)
        if db._q1("SELECT 1 FROM securities WHERE account_id = ? AND archived = 0", (aid,)):
            raise ValueError("此帳戶的持股由「投資管理」維護，請到投資管理使用「市價評價」，選擇日期並輸入市價後產生評價分錄。")
        signed = db.signed_balances(date).get(aid, 0.0)
        cur = signed if acc["kind"] == "asset" else -signed
        delta = value - cur
        if abs(delta) < 0.005:
            raise ValueError("金額與帳本相同，不需要調整。")
        db.add_transaction(date=date, type="adjust", account_id=aid,
                           amount=delta if acc["kind"] == "asset" else -delta, note=note)
        return acc["name"]
