// 財務報表：資產負債表、收支損益表、現金流量表、月度收支、分類與預算、標籤／專案、日記帳、分類帳、試算表、報稅彙總。
import { useEffect, useMemo, useState } from "preact/hooks";
import { META, api, changed, css, html, money, num, pct, toast, useLoad, ymd } from "../lib/core.js";
import { PALETTE, axis, chartBase, useChart, valueAxis } from "../lib/charts.js";
import { Btn, Card, DataTable, Dialog, Field, Icon, PageHead, PeriodPicker, Segmented, Select, Tabs, TextInput, ask, errorBox,
         openModal, usePeriod } from "../lib/ui.js";
import { openVoucher } from "../dialogs/txn.js";
import { openAnnual, openPrint } from "../dialogs/print.js";
import { openExport } from "../dialogs/data.js";
import { showTransactions } from "./transactions.js";

const TABS = [["bs", "資產負債表", "scale"], ["is", "收支損益表", "trend_up"], ["cf", "現金流量表", "transfer"],
              ["monthly", "月度收支", "chart"], ["cats", "分類與預算", "pie"], ["tags", "標籤／專案", "tag"],
              ["journal", "日記帳", "book"], ["ledger", "分類帳", "list"], ["tb", "試算表", "layers"], ["tax", "報稅彙總", "dollar"]];
const sgn = (v) => (v >= 0 ? "c-income" : "c-expense");
const pctOrBlank = (v) => (v == null ? "" : pct(v));

export function Reports({ go }) {
  const pending = window.__pendingReport || {};
  window.__pendingReport = null;
  const [tab, setTab] = useState(pending.tab || "bs");
  const [meta] = useLoad(() => api("reports_meta"));
  const per = usePeriod("今年", meta ? meta.range : null);
  const [range] = per;
  if (!meta) return html`<div class="boot">讀取中…</div>`;
  const [start, end] = range;
  const P = { bs: BalanceSheet, is: IncomeStatement, cf: CashFlow, monthly: Monthly, cats: Categories, tags: Tags,
              journal: Journal, ledger: Ledger, tb: TrialBalance, tax: Tax }[tab];
  return html`<div class="page-fill">
    <${PageHead} title="財務報表" sub="資產負債表、收支損益表、分類帳與試算表">
      <${Btn} kind="income" icon="download" big onClick=${() => openExport(start, end)}>匯出 Excel 報表</${Btn}>
      <${Btn} icon="print" big onClick=${() => openPrint(start, end)}>列印／PDF</${Btn}>
      <${Btn} kind="primary" icon="book" big onClick=${() => openAnnual(meta.years)} title="一鍵產生整年度的完整報告（封面、四大報表、比率、投資績效…）">年度財務報告</${Btn}>
    </${PageHead}>
    <div class="card filters"><div class="frow"><${PeriodPicker} state=${per} label="報表期間" /><div class="grow"></div>
      ${meta.closed_until && html`<span class="muted"><${Icon} name="lock" cls="mini" /> 已結帳至 ${ymd(meta.closed_until)}</span>`}</div></div>
    <${Tabs} value=${tab} onChange=${setTab} tabs=${TABS} />
    <${P} start=${start} end=${end} meta=${meta} go=${go} pending=${pending} key=${tab} />
  </div>`;
}

// ------------------------------------------------------------------ 報表（樹狀）表格
function Statement({ heads, rows, cls = "" }) {
  return html`<div class="card table-card"><div class="tablewrap"><table class=${"list stmt sticky " + cls}>
    <thead><tr>${heads.map((h, i) => html`<th class=${i ? "r" : ""}>${h}</th>`)}</tr></thead>
    <tbody>${rows.map((r) => (r.style === "blank" ? html`<tr class="blank"><td colspan=${heads.length}></td></tr>`
      : html`<tr class=${"s-" + (r.style || "row") + " l" + (r.level ?? 1)} title=${r.help || ""}>
          ${r.cells.map((c, i) => (i === 0 ? html`<td class="name" colspan=${r.span || 1}>${c}</td>`
            : html`<td class=${"r num " + (r.cls ? r.cls[i] || "" : "")}>${c}</td>`))}</tr>`))}</tbody>
  </table></div></div>`;
}

function CompareBar({ title, value, onChange, modes }) {
  return html`<div class="row wrap"><span class="muted grow">${title}</span><span class="lbl">比較</span>
    <${Select} value=${value} onChange=${onChange} options=${modes} title="與上一期比較：資產負債表比較本期期初，收支損益表比較長度相同的前一期（例如本月比上月、今年比去年）。與去年同期比較：日期往前推一年。" /></div>`;
}

function BalanceSheet({ start, end, meta }) {
  const [mode, setMode] = useState(meta.compare_bs);
  const [d] = useLoad(() => api("report_bs", start, end, mode), [start, end, mode]);
  const change = (m) => { setMode(m); api("set_setting", "report_compare_bs", m); };
  if (!d) return html`<div class="muted">計算中…</div>`;
  const cmp = !!d.cdate;
  const heads = ["會計科目", ...(d.has_orig ? ["原幣金額"] : []), `金額（${META.base}）`, "占總資產", ...(cmp ? [ymd(d.cdate), "增減金額", "增減 %"] : [])];
  const n = heads.length;
  const rows = [];
  for (const r of d.rows) {
    if (r.style === "blank") { rows.push({ style: "blank" }); continue; }
    if (r.cur == null) { rows.push({ style: r.style, level: r.level, cells: [r.name], span: n }); continue; }
    const g = r.good == null ? "" : r.good ? "c-income" : "c-expense";
    const cells = [r.name, ...(d.has_orig ? [r.orig != null ? money(r.orig, r.currency) : ""] : []), num(r.cur), pctOrBlank(r.share),
                   ...(cmp ? [num(r.prev), r.change ? num(r.change, null, true) : "", r.change_pct == null ? "" : pct(r.change_pct)] : [])];
    const cls = cells.map((_, i) => (i >= n - 2 && cmp ? g : r.net && i === (d.has_orig ? 2 : 1) ? "c-primary" : ""));
    rows.push({ style: r.style, level: r.level, cells, cls });
  }
  rows.push({ style: "blank" }, { style: "section", level: 0, cells: ["財務比率分析"], span: n });
  for (const x of d.ratios) {
    rows.push({ level: 1, help: x.help, cells: [x.name, ...(d.has_orig ? [""] : []), x.cur, "", ...(cmp ? [x.prev, x.change, ""] : [])] });
  }
  rows.push({ style: "blank" }, { style: "section", level: 0, cells: [`權益變動（${ymd(start)}～${ymd(end)}）`], span: n });
  for (const x of d.equity) rows.push({ level: 1, cells: [x.name, ...(d.has_orig ? [""] : []), num(x.value), "", ...(cmp ? ["", "", ""] : [])] });
  rows.push({ style: "total", level: 0, cells: ["期末淨值", ...(d.has_orig ? [""] : []), num(d.equity_closing), "", ...(cmp ? ["", "", ""] : [])],
              cls: [, ...(d.has_orig ? [""] : []), "c-primary"] });
  if (d.closed_years.length) rows.push({ level: 1, cells: [`已辦理年度結帳：${d.closed_years.join("、")} 年（本期損益已結轉累積淨值）`], span: n });
  return html`<${CompareBar} title=${`基準日：${ymd(end)}（報表期間的最後一天）` + (cmp ? `　｜　比較日：${ymd(d.cdate)}` : "")}
      value=${mode} onChange=${change} modes=${meta.compare_modes} />
    <${Statement} heads=${heads} rows=${rows} />`;
}

function IncomeStatement({ start, end, meta }) {
  const [mode, setMode] = useState(meta.compare_is);
  const [d] = useLoad(() => api("report_is", start, end, mode), [start, end, mode]);
  const change = (m) => { setMode(m); api("set_setting", "report_compare_is", m); };
  if (!d) return html`<div class="muted">計算中…</div>`;
  const cmp = !!d.crange;
  const heads = ["會計科目", "筆數", `本期金額（${META.base}）`, "占收入比", ...(cmp ? [`${ymd(d.crange[0])}～${ymd(d.crange[1])}`, "增減金額", "增減 %"] : [])];
  const rows = d.rows.map((r) => {
    if (r.style === "section") return { style: "section", level: 0, cells: [r.name], span: heads.length };
    const g = r.good == null ? "" : r.good ? "c-income" : "c-expense";
    const tone = r.style === "subtotal" ? (r.kind === "income" ? "c-income" : "c-expense") : r.style === "grand" ? (r.cur >= 0 ? "c-primary" : "c-expense") : "";
    return { style: r.style, level: r.level,
             cells: [r.code ? html`<span class="muted num code">${r.code}</span>${r.name}` : r.name, r.count, num(r.cur), pctOrBlank(r.share),
                     ...(cmp ? [num(r.prev), r.change ? num(r.change, null, true) : "", r.change_pct == null ? (r.change ? "—" : "") : pct(r.change_pct)] : [])],
             cls: ["", "muted", tone, "", "", g, g] };
  });
  return html`<${CompareBar} title=${`期間：${ymd(start)}～${ymd(end)}` + (cmp ? `　｜　比較：${ymd(d.crange[0])}～${ymd(d.crange[1])}` : "")}
      value=${mode} onChange=${change} modes=${meta.compare_modes} />
    <${Statement} heads=${heads} rows=${rows} />`;
}

function CashFlow({ start, end }) {
  const [cf] = useLoad(() => api("report_cf", start, end), [start, end]);
  if (!cf) return html`<div class="muted">計算中…</div>`;
  const rows = [{ style: "total", level: 0, cells: ["期初現金及約當現金", num(cf.opening)] }];
  for (const [title, key, tk] of [["一、生活（營業）活動之現金流量", "operating", "op_total"], ["二、投資活動之現金流量", "investing", "inv_total"],
                                    ["三、籌資活動之現金流量", "financing", "fin_total"], ["四、其他", "other", "other_total"]]) {
    if (key === "other" && !cf.other.length) continue;
    rows.push({ style: "section", level: 0, cells: [title], span: 2 });
    for (const r of cf[key]) rows.push({ level: 2, cells: [r.name, num(r.amount)], cls: ["", r.amount > 0 ? "c-income" : "c-expense"] });
    if (!cf[key].length) rows.push({ level: 2, cells: ["（本期無）", ""] });
    rows.push({ style: "subtotal", level: 1, cells: ["淨現金流入（流出）", num(cf[tk])] });
  }
  rows.push({ style: "total", level: 0, cells: ["本期現金及約當現金淨增減", num(cf.net, null, true)], cls: ["", sgn(cf.net)] });
  rows.push({ style: "grand", level: 0, cells: ["期末現金及約當現金", num(cf.closing)], cls: ["", "c-primary"] });
  const ok = Math.abs(cf.check) < 0.05;
  rows.push({ level: 1, cells: ["勾稽：期初 ＋ 淨增減 ＝ 期末", ok ? "✓ 相符" : `差額 ${num(cf.check)}`], cls: ["", ok ? "c-income" : "c-expense"] });
  return html`<${Statement} heads=${["項目", `金額（${META.base}）`]} rows=${rows} cls="narrow" />
    <div class="hint">現金及約當現金包含：現金、銀行存款、定期存款、外幣存款。生活（營業）活動為日常收支與信用卡；投資活動為股票、基金、保單等買賣；籌資活動為貸款借還。</div>`;
}

function Monthly({ start, end }) {
  const [d] = useLoad(() => api("report_monthly", start, end), [start, end]);
  const months = d ? d.months : [];
  const many = new Set(months.map((m) => m.ym.slice(0, 4))).size > 1;
  const labels = months.map((m) => (many ? m.ym.slice(2, 4) + "/" + m.ym.slice(5) : +m.ym.slice(5) + "月"));
  const ref = useChart(() => ({
    ...chartBase(), legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: css("--text-2") } },
    grid: { left: 8, right: 12, top: 34, bottom: 4, containLabel: true }, xAxis: axis(labels), yAxis: valueAxis(),
    series: [{ name: "收入", type: "bar", data: months.map((m) => m.income), barMaxWidth: 18, itemStyle: { color: css("--income"), borderRadius: [5, 5, 0, 0] } },
             { name: "支出", type: "bar", data: months.map((m) => m.expense), barMaxWidth: 18, itemStyle: { color: css("--expense"), borderRadius: [5, 5, 0, 0] } },
             { name: "結餘", type: "line", data: months.map((m) => m.income - m.expense), smooth: 0.3, symbolSize: 6, lineStyle: { color: css("--primary"), width: 2.5 }, itemStyle: { color: css("--primary") } }],
  }), [d]);
  if (!d) return html`<div class="muted">計算中…</div>`;
  const ti = months.reduce((s, m) => s + m.income, 0), te = months.reduce((s, m) => s + m.expense, 0), n = Math.max(1, months.length);
  const rows = [...months.map((m) => ({ ...m, label: `${m.ym.slice(0, 4)}年${+m.ym.slice(5)}月` })),
                { ym: "sum", label: "合計", income: ti, expense: te, _total: true }, { ym: "avg", label: "月平均", income: ti / n, expense: te / n, _total: true }];
  const cols = [
    { key: "m", title: "月份", render: (r) => html`<b>${r.label}</b>`, nowrap: true },
    { key: "i", title: "收入", align: "r", render: (r) => html`<span class="num c-income">${num(r.income)}</span>` },
    { key: "e", title: "支出", align: "r", render: (r) => html`<span class="num c-expense">${num(r.expense)}</span>` },
    { key: "n", title: "結餘", align: "r", render: (r) => html`<b class=${"num " + (r.income < r.expense ? "c-expense" : "")}>${num(r.income - r.expense)}</b>` },
    { key: "s", title: "儲蓄率", align: "r", render: (r) => html`<span class="num">${r.income ? pct((r.income - r.expense) / r.income) : "—"}</span>` },
  ];
  return html`<div class="split">
    <div class="card table-card"><${DataTable} columns=${cols} rows=${rows} rowKey=${(r) => r.ym} rowCls=${(r) => (r._total ? "total" : "")} /></div>
    <${Card} title="每月收支" icon="chart"><div class="chart tall" ref=${ref}></div></${Card}></div>`;
}

function Categories({ start, end, go }) {
  const [kind, setKind] = useState("expense");
  const [rows] = useLoad(() => api("report_categories", start, end, kind), [start, end, kind]);
  const pal = PALETTE();
  const top = (rows || []).slice(0, 8);
  const rest = (rows || []).slice(8).reduce((s, r) => s + r.total, 0);
  const items = [...top.map((r) => [r.name, r.total]), ...(rest ? [["其他", rest]] : [])];
  const ref = useChart(() => ({
    ...chartBase(), tooltip: { ...chartBase().tooltip, trigger: "item", valueFormatter: (v) => money(v) },
    series: [{ type: "pie", radius: ["55%", "85%"], padAngle: 2, itemStyle: { borderRadius: 5 }, label: { show: false },
               data: items.map(([n, v], i) => ({ name: n, value: v, itemStyle: { color: pal[i % pal.length] } })) }],
  }), [rows]);
  const cols = [
    { key: "name", title: "分類", render: (r) => html`<b>${r.name}</b>`, sort: (r) => r.name, cls: () => "grow" },
    { key: "count", title: "筆數", align: "r", render: (r) => r.count, sort: (r) => r.count },
    { key: "total", title: "金額", align: "r", render: (r) => html`<span class="num">${num(r.total)}</span>`, sort: (r) => r.total },
    { key: "share", title: "占比", align: "r", render: (r) => html`<span class="num">${pct(r.share)}</span>`, sort: (r) => r.share },
    ...(kind === "expense" ? [
      { key: "budget", title: "期間預算", align: "r", render: (r) => (r.budget ? html`<span class="num">${num(r.budget)}</span>` : "—"), sort: (r) => r.budget },
      { key: "rate", title: "執行率", align: "r", render: (r) => (r.budget ? html`<span class=${"num " + (r.total > r.budget ? "c-expense" : "")}>${pct(r.total / r.budget)}</span>` : "—") },
      { key: "diff", title: "預算差異", align: "r", render: (r) => (r.budget ? html`<span class=${"num " + (r.total > r.budget ? "c-expense" : "c-income")}>${num(r.budget - r.total)}</span>` : "—") }] : []),
  ];
  return html`<div class="row"><${Segmented} value=${kind} onChange=${setKind} options=${[["expense", "支出分類", "minus"], ["income", "收入分類", "plus"]]} />
      <span class="hint">按兩下分類可查看這段期間的明細。期間預算＝每月預算 × 期間月數。</span></div>
    <div class="split">
      <div class="card table-card"><${DataTable} columns=${cols} rows=${rows || []} defaultSort=${["total", true]}
        onActivate=${(r) => showTransactions(go, { category: r.id, period: "自訂期間", start, end })} empty="這個期間沒有紀錄" /></div>
      <${Card} title="分類占比" icon="pie"><div class="chart tall" ref=${ref}></div>
        <div class="legend">${items.map(([n, v], i) => html`<div><i style=${`background:${pal[i % pal.length]}`}></i>${n}<span class="num">${money(v)}</span></div>`)}</div></${Card}></div>`;
}

function Tags({ start, end, go }) {
  const [rows] = useLoad(() => api("report_tags", start, end), [start, end]);
  const [sel, setSel] = useState(new Set());
  const cur = rows && (rows.find((r) => sel.has(r.name)) || rows[0]);
  const [detail] = useLoad(() => (cur ? api("report_tag_detail", cur.name, start, end) : []), [cur && cur.name, start, end]);
  const pal = PALETTE();
  const exp = (detail || []).filter((x) => x.kind === "expense").slice(0, 8);
  const ref = useChart(() => ({
    ...chartBase(), tooltip: { ...chartBase().tooltip, trigger: "item", valueFormatter: (v) => money(v) },
    series: [{ type: "pie", radius: ["55%", "85%"], padAngle: 2, itemStyle: { borderRadius: 5 }, label: { show: false },
               data: exp.map((x, i) => ({ name: x.name, value: x.total, itemStyle: { color: pal[i % pal.length] } })) }],
  }), [detail]);
  const open = (r) => showTransactions(go, { tag: r.name, period: "自訂期間", start, end });
  async function rename() {
    const nw = await openModal((close) => html`<${RenameDlg} old=${cur.name} close=${close} />`);
    if (!nw || nw === cur.name) return;
    try { const n = await api("tag_rename", cur.name, nw); changed(); toast(`已將 ${n} 筆紀錄的標籤改為「${nw}」`); } catch (e) { errorBox(e.message); }
  }
  async function del() {
    if (!(await ask(`要從所有紀錄移除標籤「${cur.name}」嗎？\n紀錄本身與金額都不會變動（可按 Ctrl+Z 復原）。`, { yes: "移除標籤", danger: true }))) return;
    const n = await api("tag_delete", cur.name); changed(); toast(`已從 ${n} 筆紀錄移除標籤「${cur.name}」`);
  }
  if (!rows) return html`<div class="muted">計算中…</div>`;
  const hasIncome = rows.some((r) => r.income);
  const cols = [
    { key: "name", title: "標籤／專案", render: (r) => html`<span class="tag big">#${r.name}</span>`, sort: (r) => r.name, cls: () => "grow" },
    { key: "count", title: "筆數", align: "r", render: (r) => r.count, sort: (r) => r.count },
    ...(hasIncome ? [{ key: "income", title: "收入", align: "r", render: (r) => (r.income ? html`<span class="num c-income">${num(r.income)}</span>` : "—"), sort: (r) => r.income }] : []),
    { key: "expense", title: "支出", align: "r", render: (r) => (r.expense ? html`<span class="num c-expense">${num(r.expense)}</span>` : "—"), sort: (r) => r.expense },
    { key: "net", title: "淨額", align: "r", render: (r) => html`<b class=${"num " + sgn(r.net)}>${num(r.net, null, true)}</b>`, sort: (r) => r.net },
  ];
  return html`<div class="hint">標籤把跨分類的紀錄歸在一起，例如一趟旅行、房屋修繕。記帳時在「標籤」欄輸入，或在收支明細選取多筆後按右鍵「加上標籤」。金額與收支損益表同一來源。</div>
    ${rows.length === 0 ? html`<div class="card empty"><${Icon} name="tag" size="2.2rem" /><div>這個期間沒有加上標籤的紀錄</div></div>` : html`<div class="split">
      <div class="col"><div class="card table-card"><${DataTable} columns=${cols} rows=${rows} rowKey=${(r) => r.name} selected=${new Set([cur.name])}
          onSelect=${setSel} onActivate=${open} defaultSort=${["expense", true]} /></div>
        <div class="row"><${Btn} kind="primary" icon="list" onClick=${() => open(cur)}>查看明細</${Btn}><${Btn} icon="edit" onClick=${rename}>重新命名…</${Btn}>
          <${Btn} kind="danger" icon="trash" onClick=${del}>移除標籤…</${Btn}></div></div>
      <${Card} title=${`「${cur.name}」${ymd(cur.first)} ～ ${ymd(cur.last)}`} icon="tag">
        <table class="list compact"><tbody>${(detail || []).map((x) => html`<tr><td><span class="muted num code">${x.code}</span>${x.name}</td><td class="r">${x.count}</td>
          <td class=${"r num " + (x.kind === "income" ? "c-income" : "c-expense")}>${num(x.total)}</td></tr>`)}</tbody></table>
        ${exp.length > 0 && html`<div class="chart small" ref=${ref}></div>`}</${Card}></div>`}`;
}
function RenameDlg({ old, close }) {
  const [v, setV] = useState(old);
  return html`<${Dialog} title="重新命名標籤" icon="tag" width="30rem" onClose=${() => close(null)}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}><${Btn} kind="primary" onClick=${() => close(v.trim())}>改名</${Btn}>`}>
    <p>「${old}」改名為（與已有標籤同名時會合併）：</p>
    <form onSubmit=${(e) => { e.preventDefault(); close(v.trim()); }}><${TextInput} value=${v} onInput=${setV} autofocus /></form></${Dialog}>`;
}

function Journal({ start, end }) {
  const [kw, setKw] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const t = setTimeout(() => setQ(kw), 250); return () => clearTimeout(t); }, [kw]);
  const [entries] = useLoad(() => api("report_journal", start, end, q), [start, end, q]);
  const rows = useMemo(() => {
    const out = [];
    (entries || []).forEach((e, n) => e.lines.forEach((ln, i) => out.push({ key: e.id + "-" + i, id: e.id, first: i === 0, odd: n % 2, date: e.date, voucher: e.voucher, summary: e.summary, ...ln })));
    return out;
  }, [entries]);
  const d = rows.reduce((s, r) => s + r.debit, 0), c = rows.reduce((s, r) => s + r.credit, 0), ok = Math.abs(d - c) < 1;
  const cols = [
    { key: "date", title: "日期", render: (r) => (r.first ? html`<span class="num">${ymd(r.date)}</span>` : ""), nowrap: true },
    { key: "v", title: "傳票號碼", align: "c", render: (r) => (r.first ? html`<span class="muted num">${r.voucher}</span>` : "") },
    { key: "s", title: "摘要", elide: true, render: (r) => (r.first ? r.summary : "") },
    { key: "code", title: "科目代號", align: "c", render: (r) => html`<span class="muted num">${r.code}</span>` },
    { key: "name", title: "會計科目", render: (r) => html`<span class=${r.credit && !r.debit ? "indent" : ""}>${r.name}</span>`, nowrap: true },
    { key: "dr", title: "借方金額", align: "r", render: (r) => (r.debit ? html`<span class="num c-income">${num(r.debit)}</span>` : "") },
    { key: "cr", title: "貸方金額", align: "r", render: (r) => (r.credit ? html`<span class="num c-expense">${num(r.credit)}</span>` : "") },
  ];
  return html`<div class="row wrap"><${TextInput} icon="search" value=${kw} onInput=${setKw} placeholder="搜尋摘要或會計科目…" />
      <div class="grow"></div>${entries && html`<b class=${ok ? "c-income" : "c-expense"}>傳票 ${entries.length} 張　｜　借方合計 ${money(d)}　｜　貸方合計 ${money(c)}　${ok ? "✓ 借貸平衡" : `✗ 差額 ${money(d - c)}`}</b>`}</div>
    <div class="card table-card"><${DataTable} columns=${cols} rows=${rows} rowKey=${(r) => r.key} rowCls=${(r) => (r.odd ? "band" : "") + (r.first ? " first" : "")}
      onActivate=${(r) => openVoucher(r.id)} empty=${entries ? "這個期間沒有傳票" : "讀取中…"} /></div>
    <div class="hint">依日期列出每張傳票的借貸分錄（以本位幣表示，貸方科目內縮）。按兩下可開啟傳票；系統自動產生的投資分錄也會列在這裡。</div>`;
}

function Ledger({ start, end, meta, pending }) {
  const [aid, setAid] = useState(pending.account || (meta.accounts[0] && meta.accounts[0].id));
  const [lg] = useLoad(() => (aid ? api("report_ledger", aid, start, end) : null), [aid, start, end]);
  const c = lg ? lg.currency : META.base;
  const rows = lg ? [{ key: "o", date: start, voucher: "", summary: "期初餘額（上期結轉）", counter: "", debit: 0, credit: 0, balance: lg.opening, _total: true },
                     ...lg.rows.map((r, i) => ({ ...r, key: i })),
                     { key: "t", date: end, voucher: "", summary: "本期合計", counter: "", debit: lg.debit_total, credit: lg.credit_total, balance: lg.closing, _total: true }] : [];
  const cols = [
    { key: "date", title: "日期", render: (r) => html`<span class="num">${ymd(r.date)}</span>`, nowrap: true },
    { key: "v", title: "傳票號碼", align: "c", render: (r) => html`<span class="muted num">${r.voucher}</span>` },
    { key: "s", title: "摘要", elide: true, cls: () => "grow", render: (r) => r.summary },
    { key: "c", title: "對方科目", elide: true, render: (r) => r.counter },
    { key: "dr", title: "借方", align: "r", render: (r) => (r.debit ? html`<span class="num c-income">${num(r.debit, c)}</span>` : "") },
    { key: "cr", title: "貸方", align: "r", render: (r) => (r.credit ? html`<span class="num c-expense">${num(r.credit, c)}</span>` : "") },
    { key: "b", title: "餘額", align: "r", render: (r) => html`<b class="num">${num(r.balance, c)}</b>` },
  ];
  return html`<div class="row wrap"><span class="lbl">帳戶（科目）</span><${Select} value=${aid} onChange=${setAid} options=${meta.accounts.map((a) => [a.id, a.label])} />
      <div class="grow"></div>${lg && html`<b>期初 ${money(lg.opening, c)}　→　期末 ${money(lg.closing, c)}（${lg.side}餘）</b>`}</div>
    <div class="card table-card"><${DataTable} columns=${cols} rows=${rows} rowKey=${(r) => r.key} rowCls=${(r) => (r._total ? "total" : "")}
      onActivate=${(r) => r.id && openVoucher(r.id)} /></div>
    <div class="hint">借方：資產增加／負債減少；貸方：資產減少／負債增加。資產帳戶餘額在借方，負債帳戶餘額在貸方。按兩下可開啟傳票。</div>`;
}

function TrialBalance({ start, end }) {
  const [rows] = useLoad(() => api("report_tb", start, end), [start, end]);
  if (!rows) return html`<div class="muted">計算中…</div>`;
  const K = ["open_debit", "open_credit", "period_debit", "period_credit", "debit", "credit"];
  const tot = Object.fromEntries(K.map((k) => [k, rows.reduce((s, r) => s + r[k], 0)]));
  const ok = [["open_debit", "open_credit"], ["period_debit", "period_credit"], ["debit", "credit"]].every(([a, b]) => Math.abs(tot[a] - tot[b]) < 1);
  const all = [...rows, { code: "", name: "合計", group: "", _total: true, ...tot }];
  const amt = (k, t) => ({ key: k, title: t, align: "r", render: (r) => (r[k] ? html`<span class=${"num" + (k === "debit" || k === "credit" ? " b" : "")}>${num(r[k])}</span>` : "") });
  const cols = [{ key: "code", title: "代號", align: "c", render: (r) => html`<span class="muted num">${r.code}</span>` },
                { key: "name", title: "會計科目", render: (r) => html`<b>${r.name}</b>`, nowrap: true, cls: () => "grow" },
                { key: "g", title: "類別", align: "c", render: (r) => html`<span class="muted">${r.group}</span>` },
                amt("open_debit", "期初借方"), amt("open_credit", "期初貸方"), amt("period_debit", "本期借方"), amt("period_credit", "本期貸方"),
                amt("debit", "期末借方"), amt("credit", "期末貸方")];
  return html`<div class="card table-card"><${DataTable} columns=${cols} rows=${all} rowKey=${(r) => r.code + r.name} rowCls=${(r) => (r._total ? "total" : "")} /></div>
    <b class=${ok ? "c-income" : "c-expense"}>期末借方 ${money(tot.debit)}　｜　期末貸方 ${money(tot.credit)}　｜　${ok ? "✓ 期初、本期、期末皆借貸平衡" : `✗ 不平衡，期末差額 ${money(tot.debit - tot.credit)}`}</b>
    <div class="hint">六欄式試算表：期初餘額＋本期借貸發生額＝期末餘額。損益科目只有本期發生額；期初淨值 = 期初前一日淨資產 + 期間內新開帳戶之期初金額。三組借貸合計都相等即表示帳務平衡。</div>`;
}

function Tax({ end, meta }) {
  const [year, setYear] = useState(meta.years.includes(+end.slice(0, 4)) ? +end.slice(0, 4) : meta.years[0]);
  const [ts] = useLoad(() => api("report_tax", year), [year]);
  const rows = [];
  if (ts) {
    rows.push({ style: "section", level: 0, cells: [`${year} 年度所得（民國 ${year - 1911} 年）`], span: 2 });
    for (const [items, empty, title] of [[ts.incomes, "（無已歸類的所得）"], [ts.deductions, "（無已歸類的扣除項目）", "可列舉扣除與相關支出"]]) {
      if (title) rows.push({ style: "section", level: 0, cells: [title], span: 2 });
      for (const it of items) {
        rows.push({ style: "subtotal", level: 1, cells: [it.label, num(it.amount)] });
        rows.push({ level: 2, cells: ["來源：" + it.categories.join("、")], span: 2 });
        if (it.note) rows.push({ level: 2, cells: [html`<span class="muted">說明：${it.note}</span>`], span: 2 });
      }
      if (!items.length) rows.push({ level: 1, cells: [empty, ""] });
    }
    rows.push({ style: "section", level: 0, cells: ["證券交易"], span: 2 });
    rows.push({ level: 1, cells: ["處分投資損益（參考）", num(ts.realized)] });
    rows.push({ level: 2, cells: [html`<span class="muted">說明：${ts.realized_note}</span>`], span: 2 });
  }
  return html`<div class="row"><span class="lbl">所得年度</span><${Select} value=${year} onChange=${setYear} options=${meta.years.map((y) => [y, `${y} 年（民國 ${y - 1911} 年）`])} /></div>
    ${ts ? html`<${Statement} heads=${["項目", `金額（${META.base}）`]} rows=${rows} cls="narrow wrap" />` : html`<div class="muted">計算中…</div>`}
    <div class="hint">依「設定 → 收支分類」中的「稅務歸類」彙總，方便每年五月申報綜合所得稅時參考。稅法規定時有修訂，實際申報請以財政部最新規定與國稅局資料為準。</div>`;
}
