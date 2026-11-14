"""投資明細帳：證券持股、平均成本、已實現／未實現損益與股利。

會計處理（帳上投資科目以市價表示）：
* 買進：借 投資帳戶（成本＝股數×價格＋手續費）／貸 交割帳戶；不產生評價分錄。
* 賣出：借 交割帳戶（淨價款）、貸 投資帳戶（平均成本）、差額記「處分投資損益」；
        同時迴轉所售股份已認列之「未實現評價損益」，剩餘持股不重新評價。
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
    分錄賣出：迴轉所售股份之未實現評價損益，並將貸記金額與平均成本之差額調整為處分投資損益。
系統分錄由系統自動產生（source = 'inv:<證券 id>'），交易變更時自該日起重新產生。
"""

from __future__ import annotations

import datetime as _dt
import math

from .database import Database, fmt_shares, money_round, voucher_no

KIND_LABELS = {"buy": "買進", "sell": "賣出", "cash_div": "現金股利", "stock_div": "股票股利",
               "price": "市價評價", "jbuy": "買進（分錄）", "jsell": "賣出（分錄）"}
NHI_RATE = 0.0211       # 二代健保補充保費費率
NHI_THRESHOLD = 20000   # 單筆股利達此金額才扣繳
FEE_RATE = 0.001425     # 台股手續費率（未打折）
FEE_MIN = 20.0          # 最低手續費
STOCK_TAX = 0.003       # 股票證交稅
ETF_TAX = 0.001         # ETF 證交稅


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
                     tax_rate: float | None = None) -> int:
        if not name.strip():
            raise ValueError("請輸入標的名稱")
        acc = self.db.get_account(account_id)
        if not acc or acc["kind"] != "asset":
            raise ValueError("請選擇投資帳戶（資產）")
        rates = self._check_rates(FEE_RATE if fee_rate is None else fee_rate,
                                  FEE_MIN if fee_min is None else fee_min,
                                  default_tax_rate(code) if tax_rate is None else tax_rate)
        cur = self.db.conn.execute(
            "INSERT INTO securities(account_id, code, name, note, fee_rate, fee_min, tax_rate)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", (account_id, code.strip(), name.strip(), note.strip(), *rates))
        self.db.conn.commit()
        return cur.lastrowid

    @staticmethod
    def _check_rates(fee_rate: float, fee_min: float, tax_rate: float) -> tuple[float, float, float]:
        if not (0 <= fee_rate < 0.05 and 0 <= fee_min < 10000 and 0 <= tax_rate < 0.05):
            raise ValueError("手續費率與證交稅率請輸入合理的百分比（例如 0.1425%、0.3%）")
        return float(fee_rate), float(fee_min), float(tax_rate)

    def update_security(self, sid: int, code: str, name: str, note: str = "",
                        fee_rate: float | None = None, fee_min: float | None = None,
                        tax_rate: float | None = None) -> None:
        sec = self.get_security(sid)
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
                             " tax_rate = ? WHERE id = ?",
                             (code.strip(), name.strip(), note.strip(), *rates, sid))
        if first:
            self.rebuild(sid, first)
        self.db.conn.commit()

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
        """複式分錄中連結投資標的之買進／賣出（作廢的分錄不計入）。"""
        sql = ("SELECT t.id AS txn_id, t.date, t.note, t.created_at, l.security_id, s.code,"
               " s.name AS sec_name, s.account_id, SUM(l.orig) AS orig, MAX(l.price) AS unit_price,"
               " SUM(CASE WHEN l.debit > 0 THEN l.shares ELSE -l.shares END) AS net_shares,"
               " (SELECT COALESCE(SUM(x.credit - x.debit), 0) FROM txn_lines x"
               "   WHERE x.txn_id = t.id AND x.special = 'realized') AS booked_gain"
               " FROM txn_lines l JOIN transactions t ON t.id = l.txn_id"
               " JOIN securities s ON s.id = l.security_id"
               " WHERE t.void = 0 AND t.type = 'journal' AND l.security_id IS NOT NULL")
        params: list = []
        if sid:
            sql += " AND l.security_id = ?"
            params.append(sid)
        if start:
            sql += " AND t.date >= ?"
            params.append(start)
        if end:
            sql += " AND t.date <= ?"
            params.append(end)
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
                diff = money_round(value - shares * unit) if buy else money_round(shares * unit - value)
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
                 "realized": [], "dividends": [], "vouchers": []}
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
                note = f"買進 {sec['name']} {e['shares']:,.0f} 股 @ {e['price']:,.2f}"
            elif k == "sell":
                if e["shares"] > state["shares"] + 1e-9:
                    raise ValueError(f"{e['date'].replace('-', '/')} 賣出 {e['shares']:,.0f} 股，"
                                     f"超過當時持股 {state['shares']:,.0f} 股")
                ratio = e["shares"] / state["shares"]
                cost_out = state["cost"] * ratio
                adj_out = state["val_adj"] * ratio
                proceeds = e["shares"] * e["price"] - e["fee"] - e["tax"]
                gain = proceeds - cost_out
                lines += [{"account": e["cash_account_id"], "amt": proceeds},
                          {"account": inv, "amt": -cost_out},
                          {"special": "realized", "gain": gain}]
                if abs(adj_out) >= 0.005:
                    lines += [{"account": inv, "amt": -adj_out}, {"special": "adjust", "gain": -adj_out}]
                state["shares"] -= e["shares"]
                state["cost"] -= cost_out
                state["val_adj"] -= adj_out
                if state["shares"] < 1e-9:
                    state["shares"] = state["cost"] = state["val_adj"] = 0.0
                state["realized"].append({"date": e["date"], "gain": gain, "event": e["id"],
                                          "cost": cost_out, "proceeds": proceeds})
                note = f"賣出 {sec['name']} {e['shares']:,.0f} 股 @ {e['price']:,.2f}"
            elif k == "jbuy":
                # 分錄已由使用者借記投資科目、貸記付款科目，這裡只累計成本與股數
                state["shares"] += e["shares"]
                state["cost"] += e["value"]
            elif k == "jsell":
                if e["shares"] > state["shares"] + 1e-9:
                    raise ValueError(f"{e['date'].replace('-', '/')} 分錄賣出 {fmt_shares(e['shares'])} 股，"
                                     f"超過當時持股 {fmt_shares(state['shares'])} 股")
                ratio = e["shares"] / state["shares"]
                cost_out = state["cost"] * ratio
                adj_out = state["val_adj"] * ratio
                # 使用者已貸記投資科目 value；差額依平均成本調整為處分損益
                diff = e["value"] - cost_out
                if abs(adj_out) >= 0.005:
                    lines += [{"account": inv, "amt": -adj_out}, {"special": "adjust", "gain": -adj_out}]
                if abs(diff) >= 0.005:
                    lines += [{"account": inv, "amt": diff}, {"special": "realized", "gain": diff}]
                gain = e["booked_gain"] / (sec["rate"] or 1) + diff
                state["shares"] -= e["shares"]
                state["cost"] -= cost_out
                state["val_adj"] -= adj_out
                if state["shares"] < 1e-9:
                    state["shares"] = state["cost"] = state["val_adj"] = 0.0
                state["realized"].append({"date": e["date"], "gain": gain, "event": None,
                                          "txn_id": e["txn_id"], "cost": cost_out,
                                          "proceeds": cost_out + gain})
                note = (f"{sec['name']} 分錄賣出：迴轉未實現評價損益，並依平均成本"
                        f"調整處分投資損益（{voucher_no(e['txn_id'])}）")
            elif k == "cash_div":
                net = e["amount"] - e["nhi"]
                lines += [{"account": e["cash_account_id"], "amt": net},
                          {"category": ("income", "股利"), "credit": e["amount"]}]
                if e["nhi"]:
                    lines.append({"category": ("expense", "健保補充保費"), "debit": e["nhi"]})
                state["dividends"].append({"date": e["date"], "amount": e["amount"], "nhi": e["nhi"]})
                note = f"{sec['name']} 現金股利"
            elif k == "stock_div":
                state["shares"] += e["shares"]
            elif k == "price":
                state["price"], state["price_date"] = e["price"], e["date"]
                note = f"{sec['name']} 股價更新 @ {e['price']:,.2f}"
                # 評價至預估淨售價：市價×股數－預估賣出手續費－預估證交稅
                fee, tax = trade_costs(sec, "sell", state["shares"], state["price"])
                target = state["shares"] * state["price"] - fee - tax - state["cost"] if state["shares"] else 0.0
                delta = target - state["val_adj"]
                if abs(delta) >= 0.005:
                    lines += [{"account": inv, "amt": delta}, {"special": "adjust", "gain": delta}]
                    state["val_adj"] = target
            if state["shares"] < 1e-9:
                state["price"], state["price_date"] = 0.0, ""
            if lines:
                state["vouchers"].append({"event": e["id"], "date": e["date"], "note": note,
                                          "lines": lines})
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
            out.append({"account_id": aid, "orig": round(orig, 4),
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
        """刪除該標的自 from_date 起的系統分錄，依交易重新產生。"""
        sec = self.get_security(sid)
        src = f"inv:{sid}"
        db = self.db
        old = db._q("SELECT id FROM transactions WHERE source = ? AND date >= ?", (src, from_date))
        for r in old:
            db.conn.execute("DELETE FROM txn_lines WHERE txn_id = ?", (r["id"],))
            db.conn.execute("DELETE FROM recon_items WHERE txn_id = ?", (r["id"],))
            db.conn.execute("DELETE FROM transactions WHERE id = ?", (r["id"],))
        state = self.replay(sid)
        n = 0
        for v in state["vouchers"]:
            if v["date"] < from_date:
                continue
            lines = self._lines_to_journal(sec, v["lines"])
            if len([x for x in lines if x.get("debit") or x.get("credit")]) < 2:
                continue
            db.add_journal(v["date"], v["note"], lines, source=src, log="")
            n += 1
        db._log("投資分錄產生", None, f"{sec['name']}：自 {from_date.replace('-', '/')} 起重新產生 {n} 張傳票")
        db.conn.commit()

    def holdings(self, as_of: str | None = None, include_zero: bool = False) -> list[dict]:
        out = []
        for sec in self.list_securities(include_archived=True):
            st = self.replay(sec["id"], as_of)
            if st["shares"] <= 1e-9 and not include_zero:
                continue
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

    def last_cash_account(self, sid: int) -> int | None:
        row = self.db._q1("SELECT cash_account_id FROM sec_events WHERE security_id = ? AND"
                          " cash_account_id IS NOT NULL ORDER BY date DESC, id DESC LIMIT 1", (sid,))
        return row["cash_account_id"] if row else None
