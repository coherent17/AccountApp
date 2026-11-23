"""複式分錄的常用範本。

範本存在 journal_templates 設定（JSON）：[[名稱, [[借貸, 科目, 行備註, 金額], ...]], ...]；
科目為 "account:5"、"category:12"、"special:equity"（自訂範本），或內建範本的 "asset:銀行存款"、
"category:expense:餐飲" 之類的描述，套用時依類別或名稱找到實際科目。
"""

from __future__ import annotations

import json

from .database import INVESTMENT_CATEGORIES

TEMPLATES = [
    ("（選擇常用範本）", []),
    ("房貸繳款（本金＋利息）", [("debit", "liability:房屋貸款", "本金"),
                            ("debit", "category:expense:房貸利息", "利息"),
                            ("credit", "asset:銀行存款", "")]),
    ("年繳保費（保單價值＋保險費）", [("debit", "asset:保險", "保單價值增加"),
                                ("debit", "category:expense:保險費", "危險保費"),
                                ("credit", "asset:銀行存款", "")]),
    ("退休金入帳（扣除健保費等）", [("debit", "asset:銀行存款", "實際入帳"),
                               ("debit", "category:expense:保險費", "代扣健保費"),
                               ("credit", "category:income:退休金", "應領金額")]),
    ("定存到期（本金＋利息）", [("debit", "asset:銀行存款", ""),
                            ("credit", "asset:定期存款", "本金"),
                            ("credit", "category:income:利息", "利息")]),
    ("一筆付款分攤多個費用", [("debit", "category:expense:餐飲", ""),
                          ("debit", "category:expense:日常用品", ""),
                          ("credit", "asset:現金", "")]),
    ("買進股票（借 短期投資／貸 銀行存款）", [("debit", "asset:短期投資", ""),
                                      ("credit", "asset:銀行存款", "")]),
    ("賣出股票（借 銀行存款／貸 短期投資）", [("debit", "asset:銀行存款", "實收價款"),
                                      ("credit", "asset:短期投資", "")]),
    ("淨值調整（補登漏記資產）", [("debit", "asset:", ""), ("credit", "special:equity", "")]),
]


def load_templates(db) -> list[tuple]:
    """常用分錄範本：[(名稱, [(借貸, 科目, 行備註, 金額), ...])]，未自訂時使用內建範本。"""
    try:
        saved = json.loads(db.get_setting("journal_templates") or "null")
    except ValueError:
        saved = None
    rows = saved if isinstance(saved, list) else TEMPLATES[1:]
    return [(name, [(*ln, None)[:4] for ln in lines]) for name, lines in rows]


def save_templates(db, templates: list[tuple]) -> None:
    db.set_setting("journal_templates", json.dumps(templates, ensure_ascii=False))


def resolve_template_key(db, chart_by_key: dict, spec: str):
    """範本科目轉為會計科目：自訂範本存科目 id，內建範本依類別或名稱尋找。"""
    if spec in chart_by_key:
        return chart_by_key[spec]["key"]
    kind, _, rest = spec.partition(":")
    if kind == "special":
        return ("special", rest)
    if kind == "category":
        k, _, name = rest.partition(":")
        c = db.find_category(k, name)
        return ("category", c["id"]) if c else None
    accs = db.list_accounts()
    for a in accs:
        if a["kind"] == kind and (not rest or a["category"] == rest):
            return ("account", a["id"])
    if rest in INVESTMENT_CATEGORIES:
        for a in accs:
            if a["kind"] == "asset" and a["category"] in INVESTMENT_CATEGORIES:
                return ("account", a["id"])
    return None
