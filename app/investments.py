"""投資明細帳：證券持股、平均成本、已實現／未實現損益與股利。

會計處理（帳上投資科目以市價表示）：
* 買進：借 投資帳戶（成本＝股數×價格＋手續費）／貸 交割帳戶；不產生評價分錄。
* 賣出：借 交割帳戶（淨價款）、貸 投資帳戶（平均成本）、差額記「處分投資損益」。
        賣出不迴轉已認列的「未實現評價損益」（v2.5.0 起）；所售股份的評價調整留在投資科目，
        下次市價評價時與剩餘持股一併調整（全數賣出的標的評價為 0）。
* 現金股利：借 交割帳戶（淨額）、借 健保補充保費（如有）／貸 股利收入。
* 股票股利：增加股數，成本不變（平均成本下降），不產生分錄。
* 評價：只有使用者選定日期並手動輸入市價（price 事件）才產生評價分錄。
        評價金額為預估淨售價＝市價×股數－預估賣出手續費－預估證交稅，
        差額記「未實現評價損益」，因此未實現損益已扣除買賣的手續費與稅。
        帳面價值＝成本＋已認列評價，即投資帳戶餘額（state["market_value"]）。
* 手續費與證交稅依標的設定（fee_rate、fee_min、tax_rate），台股券商慣例無條件捨去。
* 分錄連結：使用者在複式分錄中直接借記（買進）或貸記（賣出）投資科目並指定標的與股數，
  分錄由使用者自行輸入；系統只補做後續處理：
    分錄買進：成本＝借記金額（含手續費），不產生評價分錄。
    分錄行可記錄成交單價（txn_lines.price），用來顯示成交價與推算手續費、稅。
    分錄賣出：分錄中已列處分投資損益時不產生任何分錄，貸記投資科目的金額即為出售成本（v2.6.0 起）；
              只貸記淨價款、未列處分損益時，才依平均成本拆出處分投資損益。
              全數賣出後若仍有成本差額或評價，市價評價時歸零（成本差額記處分投資損益）。
    分錄股利：股利收入科目行可連結標的、持有股數與每股股利，計入該標的的股利紀錄，不產生分錄。
系統分錄由系統自動產生（source = 'inv:<證券 id>'），交易變更時自該日起重新產生。
"""

from __future__ import annotations

import datetime as _dt
import math

from .database import Database, fmt_shares, money_round, voucher_no

VAL_SOURCE = "inv:val"   # 市價評價傳票：同一天所有標的合併為一張
KIND_LABELS = {"buy": "買進", "sell": "賣出", "cash_div": "現金股利", "stock_div": "股票股利",
               "price": "市價評價", "jbuy": "買進（分錄）", "jsell": "賣出（分錄）", "jdiv": "股利（分錄）"}
NHI_RATE = 0.0211       # 二代健保補充保費費率
NHI_THRESHOLD = 20000   # 單筆股利達此金額才扣繳
FEE_RATE = 0.001425     # 台股手續費率（未打折）
FEE_MIN = 20.0          # 最低手續費
STOCK_TAX = 0.003       # 股票證交稅
ETF_TAX = 0.001         # ETF 證交稅


DEFAULT_SECURITY_TYPES = [
    {"name": "股票", "fee_rate": FEE_RATE, "fee_min": FEE_MIN, "tax_rate": STOCK_TAX},
    {"name": "ETF", "fee_rate": FEE_RATE, "fee_min": FEE_MIN, "tax_rate": ETF_TAX},
    {"name": "債券 ETF", "fee_rate": FEE_RATE, "fee_min": FEE_MIN, "tax_rate": 0.0},
]


def default_tax_rate(code: str) -> float:
    return ETF_TAX if code.strip().startswith("00") else STOCK_TAX


def trade_costs(sec: dict, kind: str, shares: float, price: float) -> tuple[float, float]:
    """依標的設定計算手續費與證交稅（賣出才有稅），無條件捨去至元。"""
    gross = shares * price
    if gross <= 0:
        return 0.0, 0.0
    fee = max(float(sec.get("fee_min", FEE_MIN)), math.floor(gross * sec.get("fee_rate", FEE_RATE) + 1e-6))
    tax = math.floor(gross * sec.get("tax_rate", STOCK_TAX) + 1e-6) if kind in ("sell", "jsell") else 0.0
    return float(fee), float(tax)


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


class Investments:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------ 標的
    def list_securities(self, account_id: int | None = None, include_archived=False) -> list[dict]:
        sql = ("SELECT s.*, a.name AS account_name, a.currency AS currency FROM securities s"
               " JOIN accounts a ON a.id = s.account_id WHERE 1 = 1")
        params: list = []
        if account_id:
            sql += " AND s.account_id = ?"
            params.append(account_id)
        if not include_archived:
            sql += " AND s.archived = 0"
        return self.db._q(sql + " ORDER BY s.code, s.id", params)

    def get_security(self, sid: int) -> dict | None:
        return self.db._q1("SELECT s.*, a.name AS account_name, a.currency AS currency, a.rate AS rate"
                           " FROM securities s JOIN accounts a ON a.id = s.account_id WHERE s.id = ?",
                           (sid,))

    def add_security(self, account_id: int, code: str, name: str, note: str = "",
                     fee_rate: float | None = None, fee_min: float | None = None,
                     tax_rate: float | None = None, type_name: str = "") -> int:
        if not name.strip():
            raise ValueError("請輸入標的名稱")
        acc = self.db.get_account(account_id)
        if not acc or acc["kind"] != "asset":
            raise ValueError("請選擇投資帳戶（資產）")
        rates = self._check_rates(FEE_RATE if fee_rate is None else fee_rate,
                                  FEE_MIN if fee_min is None else fee_min,
                                  default_tax_rate(code) if tax_rate is None else tax_rate)
        if not type_name:   # 未指定類型時，費率與某類型完全相同就歸入該類型
            type_name = next((t["name"] for t in self.security_types()
                              if (t["fee_rate"], t["fee_min"], t["tax_rate"]) == rates), "")
        cur = self.db.conn.execute(
            "INSERT INTO securities(account_id, code, name, note, fee_rate, fee_min, tax_rate, type_name)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, code.strip(), name.strip(), note.strip(), *rates, type_name.strip()))
        self.db.conn.commit()
        return cur.lastrowid

    @staticmethod
    def _check_rates(fee_rate: float, fee_min: float, tax_rate: float) -> tuple[float, float, float]:
        if not (0 <= fee_rate < 0.05 and 0 <= fee_min < 10000 and 0 <= tax_rate < 0.05):
            raise ValueError("手續費率與證交稅率請輸入合理的百分比（例如 0.1425%、0.3%）")
        return float(fee_rate), float(fee_min), float(tax_rate)

    def update_security(self, sid: int, code: str, name: str, note: str = "",
                        fee_rate: float | None = None, fee_min: float | None = None,
                        tax_rate: float | None = None, type_name: str | None = None) -> None:
        sec = self.get_security(sid)
        type_name = sec["type_name"] if type_name is None else type_name.strip()
        rates = self._check_rates(sec["fee_rate"] if fee_rate is None else fee_rate,
                                  sec["fee_min"] if fee_min is None else fee_min,
                                  sec["tax_rate"] if tax_rate is None else tax_rate)
        if not name.strip():
            raise ValueError("請輸入標的名稱")
        # 評價以預估淨售價計算，費率改變時自第一筆評價起重編分錄（先檢查結帳，避免留下未完成的變更）
        changed = rates != (sec["fee_rate"], sec["fee_min"], sec["tax_rate"])
        first = self.db._q1("SELECT MIN(date) AS d FROM sec_events WHERE security_id = ? AND kind = 'price'",
                            (sid,))["d"] if changed else None
        if first:
            c = self.db.closed_until
            if c and first <= c:
                raise ValueError(f"此標的在已結帳期間（{c.replace('-', '/')} 以前）有評價分錄，無法變更費率；"
                                 "請先到「設定」解除結帳。")
        self.db.conn.execute("UPDATE securities SET code = ?, name = ?, note = ?, fee_rate = ?, fee_min = ?,"
                             " tax_rate = ?, type_name = ? WHERE id = ?",
                             (code.strip(), name.strip(), note.strip(), *rates, type_name, sid))
        if first:
            self.rebuild(sid, first)
        self.db.conn.commit()

    # ------------------------------------------------------------------ 類型
    def security_types(self) -> list[dict]:
        """標的類型（股票、ETF…），各有手續費率、最低手續費與證交稅率；可在「標的設定」新增與修改。"""
        import json
        raw = self.db.get_setting("security_types", "")
        try:
            types = json.loads(raw) if raw else None
        except ValueError:
            types = None
        return [dict(t) for t in (types or DEFAULT_SECURITY_TYPES)]

    def save_security_types(self, rows: list[dict], apply: bool = True) -> list[str]:
        """儲存類型。rows 每筆含 name、fee_rate、fee_min、tax_rate，以及原名稱 old（新增的類型為空白）。
        改名時屬於該類型的標的一併改名；刪除的類型，其標的改為「自訂」（費率不變）。
        apply 為 True 時，屬於該類型的標的改用新費率（已結帳期間有評價者無法變更，傳回其訊息）。"""
        import json
        names = [r["name"].strip() for r in rows]
        if any(not n for n in names):
            raise ValueError("類型名稱不可空白")
        if len(set(names)) != len(names):
            raise ValueError("類型名稱不可重複")
        clean = []
        for r in rows:
            fee_rate, fee_min, tax_rate = self._check_rates(r["fee_rate"], r["fee_min"], r["tax_rate"])
            clean.append({"name": r["name"].strip(), "fee_rate": fee_rate, "fee_min": fee_min,
                          "tax_rate": tax_rate})
        kept = {r.get("old") for r in rows if r.get("old")}
        for t in self.security_types():
            if t["name"] not in kept:
                self.db.conn.execute("UPDATE securities SET type_name = '' WHERE type_name = ?", (t["name"],))
        for r, c in zip(rows, clean):
            if r.get("old") and r["old"] != c["name"]:
                self.db.conn.execute("UPDATE securities SET type_name = ? WHERE type_name = ?",
                                     (c["name"], r["old"]))
        self.db.set_setting("security_types", json.dumps(clean, ensure_ascii=False))
        self.db._log("修改標的類型", None, "、".join(
            f"{c['name']}（手續費 {c['fee_rate']:.4%}、最低 {c['fee_min']:,.0f} 元、證交稅 {c['tax_rate']:.3%}）"
            for c in clean))
        self.db.conn.commit()
        problems = []
        if apply:
            for c in clean:
                for sec in self.db._q("SELECT * FROM securities WHERE type_name = ?", (c["name"],)):
                    if (sec["fee_rate"], sec["fee_min"], sec["tax_rate"]) == (c["fee_rate"], c["fee_min"],
                                                                             c["tax_rate"]):
                        continue
                    try:
                        self.update_security(sec["id"], sec["code"], sec["name"], sec["note"],
                                             c["fee_rate"], c["fee_min"], c["tax_rate"])
                    except ValueError as e:
                        problems.append(f"{sec['name']}：{e}")
        return problems

    def archive_security(self, sid: int, archived: bool = True) -> None:
        self.db.conn.execute("UPDATE securities SET archived = ? WHERE id = ?", (int(archived), sid))
        self.db.conn.commit()

    def delete_security(self, sid: int) -> None:
        if self.db._q1("SELECT 1 FROM sec_events WHERE security_id = ?", (sid,)):
            raise ValueError("此標的已有交易紀錄，無法刪除，可改用「封存」。")
        self.db.conn.execute("DELETE FROM securities WHERE id = ?", (sid,))
        self.db.conn.commit()

    # ------------------------------------------------------------------ 交易
    def events(self, sid: int | None = None, start: str | None = None, end: str | None = None) -> list[dict]:
        sql = ("SELECT e.*, s.code, s.name AS sec_name, s.account_id, c.name AS cash_name"
               " FROM sec_events e JOIN securities s ON s.id = e.security_id"
               " LEFT JOIN accounts c ON c.id = e.cash_account_id WHERE 1 = 1")
        params: list = []
        if sid:
            sql += " AND e.security_id = ?"
            params.append(sid)
        if start:
            sql += " AND e.date >= ?"
            params.append(start)
        if end:
            sql += " AND e.date <= ?"
            params.append(end)
        rows = self.db._q(sql, params)
        rows += self.journal_events(sid, start, end)
        rows.sort(key=lambda e: (e["date"], e["kind"] == "price", e["created_at"], e.get("txn_id") or 0,
                                 e["id"] or 0))
        return rows

    def journal_events(self, sid: int | None = None, start: str | None = None,
                       end: str | None = None) -> list[dict]:
        """複式分錄中連結投資標的之買進／賣出與股利（作廢的分錄不計入）。"""
        where, params = "", []
        for cond, val in ((" AND l.security_id = ?", sid), (" AND t.date >= ?", start),
                          (" AND t.date <= ?", end)):
            if val:
                where += cond
                params.append(val)
        sql = ("SELECT t.id AS txn_id, t.date, t.note, t.created_at, l.security_id, s.code,"
               " s.name AS sec_name, s.account_id, a.rate, SUM(l.orig) AS orig, MAX(l.price) AS unit_price,"
               " SUM(CASE WHEN l.debit > 0 THEN l.shares ELSE -l.shares END) AS net_shares,"
               " (SELECT COALESCE(SUM(x.credit - x.debit), 0) FROM txn_lines x"
               "   WHERE x.txn_id = t.id AND x.special = 'realized') AS booked_gain"
               " FROM txn_lines l JOIN transactions t ON t.id = l.txn_id"
               " JOIN securities s ON s.id = l.security_id JOIN accounts a ON a.id = s.account_id"
               " WHERE t.void = 0 AND t.type = 'journal' AND l.security_id IS NOT NULL"
               " AND l.account_id IS NOT NULL" + where)
        out = []
        for r in self.db._q(sql + " GROUP BY t.id, l.security_id", params):
            shares = abs(r["net_shares"] or 0)
            value = abs(r["orig"] or 0)
            if shares < 1e-9:
                continue
            buy = (r["orig"] or 0) > 0
            # 有輸入成交單價時，金額與「單價×股數」的差額即為手續費（賣出時含證交稅）
            unit = r["unit_price"] or 0.0
            fee = tax = 0.0
            if unit > 0:
                # 賣出淨價款＝貸記投資科目＋同傳票記入處分投資損益的金額（例：65,092＋19,532＝84,624）
                net = value if buy else value + (r["booked_gain"] or 0) / (r["rate"] or 1)
                diff = money_round(net - shares * unit) if buy else money_round(shares * unit - net)
                if diff > 0:
                    if not buy:
                        sec = self.get_security(r["security_id"])
                        tax = min(diff, trade_costs(sec, "sell", shares, unit)[1])
                    fee = money_round(diff - tax)
            out.append({
                "id": None, "txn_id": r["txn_id"], "security_id": r["security_id"],
                "date": r["date"], "kind": "jbuy" if buy else "jsell", "shares": shares,
                "price": unit or value / shares, "fee": fee, "tax": tax, "amount": 0.0, "nhi": 0.0,
                "value": value, "booked_gain": r["booked_gain"] or 0.0,
                "cash_account_id": None, "cash_name": f"分錄 {voucher_no(r['txn_id'])}",
                "note": r["note"], "created_at": r["created_at"], "code": r["code"],
                "sec_name": r["sec_name"], "account_id": r["account_id"]})
        out += self._journal_dividends(where, params)
        return out

    def _journal_dividends(self, where: str, params: list) -> list[dict]:
        """複式分錄中，股利收入科目行連結的標的（股數、每股股利）。"""
        sql = ("SELECT t.id AS txn_id, t.date, t.note, t.created_at, l.security_id, s.code,"
               " s.name AS sec_name, s.account_id, a.rate, SUM(l.credit - l.debit) AS amount,"
               " MAX(l.shares) AS shares, MAX(l.price) AS unit_price"
               " FROM txn_lines l JOIN transactions t ON t.id = l.txn_id"
               " JOIN securities s ON s.id = l.security_id JOIN accounts a ON a.id = s.account_id"
               " WHERE t.void = 0 AND t.type = 'journal' AND l.security_id IS NOT NULL"
               " AND l.category_id IS NOT NULL" + where + " GROUP BY t.id, l.security_id")
        out = []
        for r in self.db._q(sql, params):
            amount = money_round((r["amount"] or 0) / (r["rate"] or 1))
            if abs(amount) < 0.005:
                continue
            out.append({
                "id": None, "txn_id": r["txn_id"], "security_id": r["security_id"],
                "date": r["date"], "kind": "jdiv", "shares": r["shares"] or 0.0,
                "price": r["unit_price"] or 0.0, "fee": 0.0, "tax": 0.0, "amount": amount, "nhi": 0.0,
                "value": 0.0, "booked_gain": 0.0,
                "cash_account_id": None, "cash_name": f"分錄 {voucher_no(r['txn_id'])}",
                "note": r["note"], "created_at": r["created_at"], "code": r["code"],
                "sec_name": r["sec_name"], "account_id": r["account_id"]})
        return out

    def add_event(self, sid: int, kind: str, date: str, shares: float = 0, price: float = 0,
                  fee: float = 0, tax: float = 0, amount: float = 0, nhi: float = 0,
                  cash_account_id: int | None = None, note: str = "") -> int:
        sec = self.get_security(sid)
        if not sec:
            raise ValueError("找不到投資標的")
        _dt.date.fromisoformat(date)
        self.db._check_open(date)
        if kind in ("buy", "sell"):
            if shares <= 0 or price <= 0:
                raise ValueError("股數與成交價必須大於 0")
        if kind == "stock_div" and shares <= 0:
            raise ValueError("配股股數必須大於 0")
        if kind == "cash_div" and amount <= 0:
            raise ValueError("股利金額必須大於 0")
        if kind == "price" and price <= 0:
            raise ValueError("價格必須大於 0")
        if fee < 0 or tax < 0 or nhi < 0:
            raise ValueError("費用不可為負數")
        if kind in ("buy", "sell", "cash_div"):
            cash = self.db.get_account(cash_account_id) if cash_account_id else None
            if not cash:
                raise ValueError("請選擇交割（扣款／入帳）帳戶")
            if cash["currency"] != sec["currency"]:
                raise ValueError("交割帳戶的幣別必須與投資帳戶相同")
            if cash["id"] == sec["account_id"]:
                raise ValueError("交割帳戶不可與投資帳戶相同")
        if kind == "price":
            self.db.conn.execute("DELETE FROM sec_events WHERE security_id = ? AND kind = 'price'"
                                 " AND date = ?", (sid, date))
        cur = self.db.conn.execute(
            "INSERT INTO sec_events(security_id, date, kind, shares, price, fee, tax, amount, nhi,"
            " cash_account_id, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, date, kind, float(shares), float(price), money_round(fee), money_round(tax),
             money_round(amount), money_round(nhi), cash_account_id, note.strip(), _now()))
        eid = cur.lastrowid
        try:
            self.replay(sid)
        except ValueError:
            self.db.conn.execute("DELETE FROM sec_events WHERE id = ?", (eid,))
            self.db.conn.commit()
            raise
        self.rebuild(sid, date)
        return eid

    def delete_event(self, eid: int) -> None:
        ev = self.db._q1("SELECT * FROM sec_events WHERE id = ?", (eid,))
        if not ev:
            return
        self.db._check_open(ev["date"])
        self.db.conn.execute("DELETE FROM sec_events WHERE id = ?", (eid,))
        try:
            self.replay(ev["security_id"])
        except ValueError:
            self.db.conn.rollback()
            raise ValueError("刪除後會造成之後的賣出股數超過持股，請先刪除之後的賣出交易。")
        self.rebuild(ev["security_id"], ev["date"])

    def set_prices(self, prices: list[tuple[int, float]], date: str) -> int:
        n = 0
        for sid, price in prices:
            if price and price > 0:
                self.add_event(sid, "price", date, price=price)
                n += 1
        return n

    # ------------------------------------------------------------------ 計算
    def replay(self, sid: int, upto: str | None = None) -> dict:
        """依時間順序重算持股，並產生每筆交易應有的分錄。"""
        sec = self.get_security(sid)
        state = {"shares": 0.0, "cost": 0.0, "val_adj": 0.0, "price": 0.0, "price_date": "",
                 "realized": [], "dividends": [], "vouchers": [],
                 "flows": []}    # 投資人的現金流量（投入為負、收回為正），供計算報酬率（performance.py）
        inv = sec["account_id"]
        for e in self.events(sid):
            if upto and e["date"] > upto:
                break
            lines: list[dict] = []
            note = ""
            k = e["kind"]
            if k == "buy":
                gross = e["shares"] * e["price"] + e["fee"]
                state["shares"] += e["shares"]
                state["cost"] += gross
                lines += [{"account": inv, "amt": gross}, {"account": e["cash_account_id"], "amt": -gross}]
                state["flows"].append((e["date"], -gross))
                note = f"買進 {sec['name']} {e['shares']:,.0f} 股 @ {e['price']:,.2f}"
            elif k == "sell":
                if e["shares"] > state["shares"] + 1e-9:
                    raise ValueError(f"{e['date'].replace('-', '/')} 賣出 {e['shares']:,.0f} 股，"
                                     f"超過當時持股 {state['shares']:,.0f} 股")
                ratio = e["shares"] / state["shares"]
                cost_out = state["cost"] * ratio
                proceeds = e["shares"] * e["price"] - e["fee"] - e["tax"]
                gain = proceeds - cost_out
                lines += [{"account": e["cash_account_id"], "amt": proceeds},
                          {"account": inv, "amt": -cost_out},
                          {"special": "realized", "gain": gain}]
                # 不迴轉評價：已認列的評價調整留待下次市價評價時調整
                state["shares"] -= e["shares"]
                state["cost"] -= cost_out
                if state["shares"] < 1e-9:
                    state["shares"] = state["cost"] = 0.0
                state["realized"].append({"date": e["date"], "gain": gain, "event": e["id"],
                                          "shares": e["shares"], "cost": cost_out, "proceeds": proceeds})
                state["flows"].append((e["date"], proceeds))
                note = f"賣出 {sec['name']} {e['shares']:,.0f} 股 @ {e['price']:,.2f}"
            elif k == "jbuy":
                # 分錄已由使用者借記投資科目、貸記付款科目，這裡只累計成本與股數
                state["shares"] += e["shares"]
                state["cost"] += e["value"]
                state["flows"].append((e["date"], -e["value"]))
            elif k == "jsell":
                if e["shares"] > state["shares"] + 1e-9:
                    raise ValueError(f"{e['date'].replace('-', '/')} 分錄賣出 {fmt_shares(e['shares'])} 股，"
                                     f"超過當時持股 {fmt_shares(state['shares'])} 股")
                gain = e["booked_gain"] / (sec["rate"] or 1)
                if abs(gain) >= 0.005:
                    # 使用者已自行記入處分投資損益：以貸記投資科目的金額為出售成本，系統不產生任何分錄（v2.6.0）
                    cost_out = e["value"]
                else:
                    # 只貸記淨價款、未列處分損益：依平均成本拆出處分投資損益（否則投資科目會多扣）
                    cost_out = state["cost"] * e["shares"] / state["shares"]
                    diff = e["value"] - cost_out
                    if abs(diff) >= 0.005:
                        lines += [{"account": inv, "amt": diff}, {"special": "realized", "gain": diff}]
                        note = f"{sec['name']} 分錄賣出：依平均成本調整處分投資損益（{voucher_no(e['txn_id'])}）"
                    gain = diff
                state["shares"] -= e["shares"]
                state["cost"] -= cost_out
                if state["shares"] < 1e-9:
                    state["shares"] = 0.0
                if abs(state["cost"]) < 0.005:
                    state["cost"] = 0.0
                state["realized"].append({"date": e["date"], "gain": gain, "event": None,
                                          "txn_id": e["txn_id"], "shares": e["shares"], "cost": cost_out,
                                          "proceeds": cost_out + gain})
                state["flows"].append((e["date"], cost_out + gain))
            elif k == "cash_div":
                net = e["amount"] - e["nhi"]
                lines += [{"account": e["cash_account_id"], "amt": net},
                          {"category": ("income", "股利"), "credit": e["amount"]}]
                if e["nhi"]:
                    lines.append({"category": ("expense", "健保補充保費"), "debit": e["nhi"]})
                state["dividends"].append({"date": e["date"], "amount": e["amount"], "nhi": e["nhi"]})
                state["flows"].append((e["date"], net))
                note = f"{sec['name']} 現金股利"
            elif k == "jdiv":
                # 分錄已由使用者記入股利收入，這裡只計入該標的的股利
                state["dividends"].append({"date": e["date"], "amount": e["amount"], "nhi": 0.0})
                state["flows"].append((e["date"], e["amount"]))
            elif k == "stock_div":
                state["shares"] += e["shares"]
            elif k == "price":
                state["price"], state["price_date"] = e["price"], e["date"]
                if state["shares"]:
                    note = f"{sec['name']} 股價更新 @ {e['price']:,.2f}"
                    # 評價至預估淨售價：市價×股數－預估賣出手續費－預估證交稅
                    fee, tax = trade_costs(sec, "sell", state["shares"], state["price"])
                    target = state["shares"] * state["price"] - fee - tax - state["cost"]
                else:
                    # 已全數賣出：剩餘評價歸零；分錄賣出貸記金額與成本的差額轉列處分投資損益
                    note = f"{sec['name']} 已全數賣出：調整剩餘評價"
                    target = 0.0
                    if abs(state["cost"]) >= 0.005:
                        lines += [{"account": inv, "amt": -state["cost"]},
                                  {"special": "realized", "gain": -state["cost"]}]
                        state["realized"].append({"date": e["date"], "gain": -state["cost"], "event": e["id"],
                                                  "shares": 0.0, "cost": state["cost"], "proceeds": 0.0})
                        state["cost"] = 0.0
                delta = target - state["val_adj"]
                if abs(delta) >= 0.005:
                    lines += [{"account": inv, "amt": delta}, {"special": "adjust", "gain": delta}]
                    state["val_adj"] = target
            if state["shares"] < 1e-9:
                state["price"], state["price_date"] = 0.0, ""
            if lines:
                state["vouchers"].append({"event": e["id"], "date": e["date"], "note": note,
                                          "lines": lines, "kind": k})
        state["market_value"] = money_round(state["cost"] + state["val_adj"])
        state["unrealized"] = money_round(state["market_value"] - state["cost"])
        state["avg_cost"] = state["cost"] / state["shares"] if state["shares"] else 0.0
        return state

    def _lines_to_journal(self, sec: dict, spec: list[dict]) -> list[dict]:
        rate = sec["rate"] or 1
        merged: dict[tuple, float] = {}
        for ln in spec:
            if "account" in ln:
                key = ("account", ln["account"])
                merged[key] = merged.get(key, 0.0) + ln["amt"]
        out = []
        for (_, aid), orig in merged.items():
            if abs(orig) < 0.005:
                continue
            base = money_round(orig * rate)
            # 金額以分為單位，避免不足一分的尾數讓分類帳逐筆合計與帳戶餘額差一分
            out.append({"account_id": aid, "orig": money_round(orig),
                        "debit": base if base > 0 else 0, "credit": -base if base < 0 else 0})
        for ln in spec:
            if "special" in ln:
                g = money_round(ln["gain"] * rate)
                if abs(g) >= 0.005:
                    out.append({"special": ln["special"], "debit": -g if g < 0 else 0,
                                "credit": g if g > 0 else 0})
            elif "category" in ln:
                kind, name = ln["category"]
                cat = self.db.find_category(kind, name)
                cid = cat["id"] if cat else self.db.add_category(name, kind)
                out.append({"category_id": cid, "debit": money_round(ln.get("debit", 0) * rate),
                            "credit": money_round(ln.get("credit", 0) * rate)})
        # 四捨五入差額歸入評價損益，確保借貸平衡
        d = round(sum(x.get("debit", 0) for x in out), 2)
        c = round(sum(x.get("credit", 0) for x in out), 2)
        if abs(d - c) >= 0.005:
            diff = round(d - c, 2)
            out.append({"special": "adjust", "debit": -diff if diff < 0 else 0,
                        "credit": diff if diff > 0 else 0})
        return out

    def rebuild(self, sid: int, from_date: str) -> None:
        """刪除該標的自 from_date 起的系統分錄，依交易重新產生。
        重新產生的傳票沿用原傳票號碼（先比對日期與摘要，再依同日順序），
        銀行對帳勾選與憑證附件因此保留；不再需要的傳票才會消失。"""
        sec = self.get_security(sid)
        src = f"inv:{sid}"
        db = self.db
        old = db._q("SELECT id, date, note FROM transactions WHERE source = ? AND date >= ? ORDER BY id",
                    (src, from_date))
        for r in old:
            db.conn.execute("DELETE FROM txn_lines WHERE txn_id = ?", (r["id"],))
            db.conn.execute("DELETE FROM transactions WHERE id = ?", (r["id"],))
        state = self.replay(sid)
        # 市價評價分錄另行彙總：同一天所有標的合併為一張傳票（_rebuild_valuations）
        todo = [v for v in state["vouchers"] if v["date"] >= from_date and v.get("kind") != "price"]
        todo = [(v, ln) for v in todo for ln in [self._lines_to_journal(sec, v["lines"])]
                if len([x for x in ln if x.get("debit") or x.get("credit")]) >= 2]
        reuse, free = self._match_vouchers(old, [v for v, _ in todo])
        n = 0
        for (v, lines), tid in zip(todo, reuse):
            db.add_journal(v["date"], v["note"], lines, source=src, log="", txn_id=tid)
            n += 1
        for o in free:      # 已不需要的傳票：清除其對帳勾選
            db.conn.execute("DELETE FROM recon_items WHERE txn_id = ?", (o["id"],))
        for tid in filter(None, reuse):   # 沿用的傳票若已不含該帳戶，也取消該帳戶的勾選
            db.conn.execute("DELETE FROM recon_items WHERE txn_id = ? AND account_id NOT IN"
                            " (SELECT account_id FROM txn_lines WHERE txn_id = ? AND account_id IS NOT NULL)",
                            (tid, tid))
        db._log("投資分錄產生", None, f"{sec['name']}：自 {from_date.replace('-', '/')} 起重新產生 {n} 張傳票")
        # 舊版（v2.6.0 以前）各標的的評價傳票，號碼可由合併後的評價傳票沿用
        self._rebuild_valuations(from_date, [o for o in free if "股價更新" in o["note"] or "已全數賣出" in o["note"]])
        db.conn.commit()

    def _rebuild_valuations(self, from_date: str, spare: list[dict] | None = None) -> None:
        """重新產生 from_date 起的市價評價傳票：同一天所有標的的評價合併成一張傳票
        （source = 'inv:val'，每一行的行備註為標的名稱與市價）。
        沿用該日原有評價傳票（或 spare 中舊版各標的評價傳票）最小的號碼，其他傳票的附件移到這張。"""
        db = self.db
        old = db._q("SELECT id, date, note FROM transactions WHERE source = ? AND date >= ? ORDER BY id",
                    (VAL_SOURCE, from_date))
        for r in old:
            db.conn.execute("DELETE FROM txn_lines WHERE txn_id = ?", (r["id"],))
            db.conn.execute("DELETE FROM transactions WHERE id = ?", (r["id"],))
        days: dict[str, list[dict]] = {}
        count: dict[str, int] = {}
        for sec in self.list_securities(include_archived=True):
            if not db._q1("SELECT 1 FROM sec_events WHERE security_id = ? AND kind = 'price' AND date >= ?",
                          (sec["id"], from_date)):
                continue
            sec = self.get_security(sec["id"])
            try:
                state = self.replay(sec["id"])
            except ValueError:
                continue
            for v in state["vouchers"]:
                if v.get("kind") != "price" or v["date"] < from_date:
                    continue
                lines = self._lines_to_journal(sec, v["lines"])
                if len([x for x in lines if x.get("debit") or x.get("credit")]) < 2:
                    continue
                memo = v["note"]
                for ln in lines:
                    ln["memo"] = memo
                days.setdefault(v["date"], []).extend(lines)
                count[v["date"]] = count.get(v["date"], 0) + 1
        pool = list(old) + [o for o in (spare or []) if o["date"] >= from_date]
        for date in sorted(days):
            cands = sorted(o["id"] for o in pool if o["date"] == date)
            tid = cands[0] if cands else None
            pool = [o for o in pool if o["date"] != date]
            note = f"市價評價（{count[date]} 檔）"
            tid = db.add_journal(date, note, days[date], source=VAL_SOURCE, log="", txn_id=tid)
            for other in cands[1:]:
                db.conn.execute("UPDATE attachments SET txn_id = ? WHERE txn_id = ?", (tid, other))
            db.conn.execute("DELETE FROM recon_items WHERE txn_id = ? AND account_id NOT IN"
                            " (SELECT account_id FROM txn_lines WHERE txn_id = ? AND account_id IS NOT NULL)",
                            (tid, tid))
        for o in pool:
            db.conn.execute("DELETE FROM recon_items WHERE txn_id = ?", (o["id"],))

    @staticmethod
    def _match_vouchers(old: list[dict], todo: list[dict]) -> tuple[list[int | None], list[dict]]:
        """系統傳票對應原傳票號碼：先以日期＋摘要對應，再以同日先後順序對應（例如股價改變使摘要不同）。"""
        free = list(old)
        reuse: list[int | None] = []
        for v in todo:
            hit = next((o for o in free if o["date"] == v["date"] and o["note"] == v["note"]), None)
            reuse.append(hit["id"] if hit else None)
            if hit:
                free.remove(hit)
        for i, v in enumerate(todo):
            if reuse[i] is None:
                hit = next((o for o in free if o["date"] == v["date"]), None)
                if hit:
                    reuse[i] = hit["id"]
                    free.remove(hit)
        return reuse, free

    def voucher_events(self, txn_id: int) -> list[dict]:
        """系統傳票是由投資管理的哪些交易產生（找不到時傳回空清單）。
        合併的市價評價傳票對應當天所有標的的市價評價。"""
        t = self.db.get_transaction(txn_id)
        if not t or not t["source"].startswith("inv:"):
            return []
        if t["source"] == VAL_SOURCE:
            return self.db._q("SELECT * FROM sec_events WHERE kind = 'price' AND date = ? ORDER BY id", (t["date"],))
        sid = int(t["source"][4:])
        sec = self.get_security(sid)
        if not sec:
            return []
        old = self.db._q("SELECT id, date, note FROM transactions WHERE source = ? ORDER BY id", (t["source"],))
        todo = [v for v in self.replay(sid)["vouchers"] if v.get("kind") != "price"
                and len([x for x in self._lines_to_journal(sec, v["lines"]) if x.get("debit") or x.get("credit")]) >= 2]
        reuse, _ = self._match_vouchers(old, todo)
        for v, tid in zip(todo, reuse):
            if tid == txn_id and v["event"]:
                return self.db._q("SELECT * FROM sec_events WHERE id = ?", (v["event"],))
        return []

    def delete_vouchers(self, txn_ids: list[int]) -> int:
        """刪除系統傳票＝刪除產生它的投資管理交易（之後的成本與分錄自動重算）。傳回刪除的交易筆數。"""
        events, missing = {}, []
        for tid in txn_ids:
            evs = self.voucher_events(tid)
            for ev in evs:
                events[ev["id"]] = ev
            if not evs:
                missing.append(voucher_no(tid))
        if missing:
            raise ValueError(f"{'、'.join(missing)} 是依您的分錄賣出計算的處分投資損益（該分錄只貸記淨價款）。"
                             "請開啟那張賣出分錄，貸記投資科目改為出售成本，並自行列出「處分投資損益」，"
                             "系統就不會再產生這張傳票。")
        first: dict[int, str] = {}
        for ev in events.values():
            self.db._check_open(ev["date"])
        for ev in events.values():
            self.db.conn.execute("DELETE FROM sec_events WHERE id = ?", (ev["id"],))
            sid = ev["security_id"]
            first[sid] = min(first.get(sid, ev["date"]), ev["date"])
        try:
            for sid in first:
                self.replay(sid)
        except ValueError:
            self.db.conn.rollback()
            raise ValueError("刪除後會造成之後的賣出股數超過持股，請先刪除之後的賣出交易。") from None
        for ev in events.values():
            sec = self.get_security(ev["security_id"])
            self.db._log("刪除投資交易", None, f"{ev['date'].replace('-', '/')} {sec['name']} "
                                         f"{KIND_LABELS.get(ev['kind'], ev['kind'])}（由收支明細刪除系統傳票）")
        for sid, d in first.items():
            self.rebuild(sid, d)
        return len(events)

    def holdings(self, as_of: str | None = None, include_zero: bool = False) -> list[dict]:
        out = []
        for sec in self.list_securities(include_archived=True):
            st = self.replay(sec["id"], as_of)
            if st["shares"] <= 1e-9 and not include_zero and abs(st["market_value"]) < 0.005 \
                    and abs(st["cost"]) < 0.005:
                continue   # 全數賣出、但仍有待調整的評價或成本差額時保留（帳面價值＝投資科目餘額）
            row = dict(sec)
            row.update({k: st[k] for k in ("shares", "cost", "price", "price_date", "market_value",
                                           "unrealized", "avg_cost")})
            row["return_pct"] = st["unrealized"] / st["cost"] if st["cost"] else None
            out.append(row)
        return out

    def period_summary(self, start: str, end: str) -> dict:
        realized = dividends = nhi = 0.0
        rows = []
        for sec in self.list_securities(include_archived=True):
            st = self.replay(sec["id"], end)
            for r in st["realized"]:
                if start <= r["date"] <= end:
                    realized += r["gain"]
                    rows.append({**r, "name": sec["name"], "code": sec["code"]})
            for d in st["dividends"]:
                if start <= d["date"] <= end:
                    dividends += d["amount"]
                    nhi += d["nhi"]
        return {"realized": money_round(realized), "dividends": money_round(dividends),
                "nhi": money_round(nhi), "realized_rows": rows}

    @staticmethod
    def suggest_nhi(amount: float) -> float:
        return money_round(amount * NHI_RATE) if amount >= NHI_THRESHOLD else 0.0

    @staticmethod
    def suggest_fees(kind: str, shares: float, price: float, code: str = "") -> tuple[float, float]:
        """台股預設費用：手續費 0.1425%（最低 20 元）；賣出證交稅股票 0.3%、ETF（代號 00 開頭）0.1%。"""
        return trade_costs({"tax_rate": default_tax_rate(code)}, kind, shares, price)

    def fees_for(self, sid: int, kind: str, shares: float, price: float) -> tuple[float, float]:
        return trade_costs(self.get_security(sid), kind, shares, price)

    def last_price(self, sid: int) -> float:
        row = self.db._q1("SELECT price FROM sec_events WHERE security_id = ? AND kind = 'price'"
                          " ORDER BY date DESC, id DESC LIMIT 1", (sid,))
        return row["price"] if row else 0.0

    def last_cash_account(self, sid: int) -> int | None:
        row = self.db._q1("SELECT cash_account_id FROM sec_events WHERE security_id = ? AND"
                          " cash_account_id IS NOT NULL ORDER BY date DESC, id DESC LIMIT 1", (sid,))
        return row["cash_account_id"] if row else None
