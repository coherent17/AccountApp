"""資料健康檢查：一次確認帳本完整、帳務平衡、備份正常，並列出需要留意的事。

只讀取帳務資料（另外記下最近一次檢查的時間 health_last）。每一項回傳 {key, title, status, detail, action}；status 為 ok／warn／info／bad：
bad 是帳務或檔案有問題（應立即處理），warn 是建議處理，info 只是提醒。
"""

from __future__ import annotations

import datetime as _dt
import os

from .database import Database, money_round


def _item(key: str, title: str, status: str, detail: str, action: str = "") -> dict:
    return {"key": key, "title": title, "status": status, "detail": detail, "action": action}


def run(db: Database, folder: str, today: _dt.date | None = None) -> dict:
    from . import backup
    from .investments import Investments

    today = today or _dt.date.today()
    t = today.isoformat()
    out: list[dict] = []
    lo, hi = db.date_range()
    hi = max(hi, t) if hi else t

    # 1. 帳本檔案
    res = db.conn.execute("PRAGMA integrity_check").fetchone()[0]
    out.append(_item("file", "帳本檔案完整", "ok" if res == "ok" else "bad",
                     "資料庫檔案檢查正常" if res == "ok" else f"檔案檢查發現問題：{res}；請從「自動備份」還原最近的備份",
                     "" if res == "ok" else "restore"))

    # 2. 試算表平衡（期初、本期、期末三組借貸都要相等）
    if lo:
        rows = db.trial_balance(lo, hi)
        diffs = [abs(sum(r[a] for r in rows) - sum(r[b] for r in rows))
                 for a, b in (("open_debit", "open_credit"), ("period_debit", "period_credit"), ("debit", "credit"))]
        ok = max(diffs) < 0.05
        total = money_round(sum(r["debit"] for r in rows))
        out.append(_item("trial", "試算表借貸平衡", "ok" if ok else "bad",
                         f"借方合計＝貸方合計＝{total:,.0f}" if ok else f"借貸差額 {max(diffs):,.2f}，請聯絡協助檢查"))
        entries = db.journal(lo, hi)
        bad = [e["voucher"] for e in entries
               if abs(sum(ln["debit"] for ln in e["lines"]) - sum(ln["credit"] for ln in e["lines"])) >= 0.05]
        out.append(_item("vouchers", "每張傳票借貸相等", "ok" if not bad else "bad",
                         f"共檢查 {len(entries):,} 張傳票" if not bad else "借貸不相等：" + "、".join(bad[:8])))
    else:
        out.append(_item("trial", "試算表借貸平衡", "ok", "帳本還沒有任何紀錄"))

    # 3. 投資科目餘額＝持股帳面價值
    inv = Investments(db)
    hold = inv.holdings(include_zero=True)
    accs = {s["account_id"] for s in inv.list_securities(include_archived=True)}
    wrong = []
    for a in db.account_summaries(include_archived=True):
        if a["id"] in accs:
            book = sum(h["market_value"] for h in hold if h["account_id"] == a["id"])
            if abs(book - a["balance"]) >= 0.5:
                wrong.append(a["name"])
    if accs:
        out.append(_item("invest", "投資科目＝持股帳面價值", "ok" if not wrong else "bad",
                         "每個投資科目的餘額都等於持股的成本加評價" if not wrong else "不一致：" + "、".join(wrong)))

    # 4. 備份
    auto_dir = os.path.join(folder, "自動備份")
    files = sorted(f for f in os.listdir(auto_dir) if f.endswith(".db")) if os.path.isdir(auto_dir) else []
    latest = max((os.path.getmtime(os.path.join(auto_dir, f)) for f in files), default=None)
    if latest is None:
        out.append(_item("backup", "自動備份", "warn", "還沒有自動備份；每天第一次開啟程式時會自動備份"))
    else:
        days = (today - _dt.date.fromtimestamp(latest)).days
        out.append(_item("backup", "自動備份", "ok" if days <= 7 else "warn",
                         f"共 {len(files)} 份，最近一份是{'今天' if days == 0 else f' {days} 天前'}"))
    bk = backup.status(db)
    if not bk.get("dir"):
        out.append(_item("backup2", "第二份備份（隨身碟／OneDrive）", "info",
                         "尚未設定；建議在「設定 → 資料管理與備份」指定隨身碟或 OneDrive，電腦故障時也不怕", "backup"))
    else:
        out.append(_item("backup2", "第二份備份（隨身碟／OneDrive）", "warn" if bk.get("remind") else "ok",
                         (f"上次成功是 {bk['days']} 天前" if bk.get("days") is not None else "還沒有成功備份過")
                         if bk.get("remind") else "最近一週內已完成", "backup" if bk.get("remind") else ""))

    # 5. 定期交易
    due = db.due_recurring(t)
    out.append(_item("recurring", "定期交易都已入帳", "ok" if not due else "warn",
                     "沒有待入帳的定期交易" if not due else f"有 {len(due)} 筆已到期尚未入帳：" +
                     "、".join(dict.fromkeys(r["name"] for r, _ in due)), "" if not due else "due"))

    # 6. 對帳：曾經對過帳的帳戶，超過 60 天還沒核銷的紀錄
    stuck = []
    for a in db.list_accounts():
        recs = db.list_reconciliations(a["id"])
        if not recs:
            continue
        cutoff = (_dt.date.fromisoformat(recs[0]["statement_date"]) - _dt.timedelta(days=60)).isoformat()
        n = sum(1 for c in db.recon_candidates(a["id"], recs[0]["statement_date"]) if c["date"] < cutoff)
        if n:
            stuck.append(f"{a['name']} {n} 筆")
    out.append(_item("recon", "沒有長期未核銷的紀錄", "ok" if not stuck else "warn",
                     "已對帳的帳戶都沒有超過 60 天未核銷的紀錄" if not stuck else
                     "超過 60 天仍未核銷（可能漏記或金額不符）：" + "、".join(stuck), "" if not stuck else "recon"))

    # 7. 投資評價
    live = [h for h in hold if h["shares"] > 1e-9]
    if live:
        old = [h["name"] for h in live if not h["price_date"] or
               (today - _dt.date.fromisoformat(h["price_date"])).days > 45]
        out.append(_item("valuation", "持股市價評價", "ok" if not old else "info",
                         "每一檔持股在 45 天內都評價過" if not old else "超過 45 天沒有評價：" + "、".join(old[:6]),
                         "" if not old else "prices"))

    # 8. 附件
    missing = db._q1("SELECT COUNT(*) AS n FROM attachments")["n"]
    lost = [r for r in db._q("SELECT path FROM attachments") if not os.path.exists(r["path"])] if missing else []
    if missing:
        out.append(_item("attach", "憑證附件", "ok" if not lost else "warn",
                         f"{missing} 個附件檔案都在" if not lost else f"有 {len(lost)} 個附件找不到檔案（可能被移動或刪除）"))

    # 9. 年度結帳
    last_year = today.year - 1
    if today.month >= 3 and lo and lo <= f"{last_year}-12-31" and (db.closed_until or "") < f"{last_year}-12-31":
        out.append(_item("close", f"{last_year} 年度結帳", "info", f"{last_year} 年的帳還沒有結帳；確認無誤後可到「財務報表」做年度結帳",
                         "yearclose"))

    bad = sum(1 for i in out if i["status"] == "bad")
    warn = sum(1 for i in out if i["status"] == "warn")
    summary = ("帳務正常" if not bad and not warn else
               f"有 {bad} 項問題需要立即處理" if bad else f"帳務正常，有 {warn} 項建議處理")
    result = {"checks": out, "bad": bad, "warn": warn, "ok": not bad, "summary": summary,
              "at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    db.set_json("health_last", {"at": result["at"], "bad": bad, "warn": warn})
    return result
