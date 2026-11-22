"""數字、金額與日期的顯示格式（不需要 Qt；v2 介面、列印與 v3 介面共用）。"""

from __future__ import annotations

import datetime as dt

from .database import CURRENCIES, ZERO_DECIMAL_CURRENCIES

FONT_FAMILY = "Microsoft JhengHei UI"


def currency_symbol(code: str) -> str:
    return CURRENCIES.get(code, (code, code + " "))[1]


def currency_name(code: str) -> str:
    return CURRENCIES.get(code, (code, code))[0]


def decimals_for(code: str) -> int:
    return 0 if code in ZERO_DECIMAL_CURRENCIES else 2


def fmt_num(value: float, code: str = "TWD", signed: bool = False) -> str:
    d = decimals_for(code)
    v = round(value or 0.0, d) + 0.0
    text = f"{abs(v):,.{d}f}"
    if v < 0:
        return "-" + text
    if signed and v > 0:
        return "+" + text
    return text


def fmt_money(value: float, code: str = "TWD", signed: bool = False) -> str:
    v = round(value or 0.0, decimals_for(code)) + 0.0
    sym = currency_symbol(code)
    sign = "-" if v < 0 else ("+" if signed and v > 0 else "")
    return f"{sign}{sym}{fmt_num(abs(v), code)}"


WEEKDAYS = "一二三四五六日"


def fmt_date(iso: str) -> str:
    return iso.replace("-", "/") if iso else ""


def fmt_date_long(d: dt.date) -> str:
    return f"{d.year}年{d.month}月{d.day}日（民國{d.year - 1911}年）星期{WEEKDAYS[d.weekday()]}"


def fmt_month(ym: str) -> str:
    y, m = ym.split("-")
    return f"{y}年{int(m)}月"


def fmt_month_short(ym: str) -> str:
    y, m = ym.split("-")
    return f"{int(m)}"
