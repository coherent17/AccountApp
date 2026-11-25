// 投資管理：持股明細、交易紀錄、已實現損益、報酬分析。
import { useEffect, useState } from "preact/hooks";
import { META, api, changed, css, html, money, num, pct, toast, useLoad, ymd } from "../lib/core.js";
import { Kpi, PALETTE, chartBase, useChart } from "../lib/charts.js";
import { Btn, Card, DataTable, DateInput, Icon, MenuButton, PageHead, PeriodPicker, Select, Tabs, TypeBadge, ask, errorBox, info,
         openMenu, usePeriod, Skeleton, Tip } from "../lib/ui.js";
import { openPrices, openSecurity, openSecurityList, openTrade } from "../dialogs/invest.js";
import { openVoucher } from "../dialogs/txn.js";

const sgn = (v) => (v >= 0 ? "c-income" : "c-expense");
const pctS = (v) => (v == null ? "—" : (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%");
const KIND_CLS = { buy: "b-expense", sell: "b-income", cash_div: "b-gold", stock_div: "b-adjust", jbuy: "b-expense",
                   jsell: "b-income", jdiv: "b-gold", price: "b-transfer" };

// 其他頁面（全域搜尋）可以帶著標的切換到交易紀錄
let pending = null;
export function showSecurity(go, sid) { pending = sid; go("investments"); }

export function Investments({ go }) {
  const [tab, setTab] = useState(pending ? "events" : "hold");
  const [asOf, setAsOf] = useState(null);
  const [evSec, setEvSec] = useState(pending);
  pending = null;
  const [d] = useLoad(() => api("invest_page", asOf), [asOf]);
  if (!d) return html`<${Skeleton} />`;

  async function trade(kind, sid) {
    if (!d.securities.some((s) => !s.archived)) {
      if (!d.has_invest_account) return info("請先到「帳戶管理」新增一個投資帳戶（類別選「短期投資」或「長期投資」，期初餘額 0），再回來新增投資標的。");
      if (!(await openSecurity())) return;
    }
    openTrade(kind, sid);
  }
  const showEvents = (sid) => { setEvSec(sid); setTab("events"); };

  return html`<div class="page-fill">
    <${PageHead} icon="chart" color="var(--adjust)" title="投資管理" help="investments" sub="投資明細帳：持股、平均成本、已實現與未實現損益、股利">
      <${Btn} kind="expense" icon="plus" big onClick=${() => trade("buy")}>買進</${Btn}>
      <${Btn} kind="income" icon="minus" big onClick=${() => trade("sell")}>賣出</${Btn}>
      <${MenuButton} label="股利" icon="gift" kind="adjust" items=${[
        { label: "現金股利", icon: "dollar", run: () => trade("cash_div") },
        { label: "股票股利（配股）", icon: "gift", run: () => trade("stock_div") }]} />
      <${Btn} kind="primary" icon="refresh" big onClick=${() => (d.holdings.length ? openPrices() : info("目前沒有持股。"))}>市價評價</${Btn}>
      <${Btn} icon="edit" big onClick=${openSecurityList} title="新增投資標的，或修改標的的類型、費率與稅率">標的設定</${Btn}>
    </${PageHead}>
    <div class="grid kpis5">
      <${Kpi} title="投資帳面價值" icon="pie" color=${css("--primary")} value=${d.market_value} />
      <${Kpi} title="投資成本" icon="layers" color=${css("--text-2")} value=${d.cost} delay=${40} />
      <${Kpi} title="未實現損益" icon="trend_up" color=${d.unrealized >= 0 ? css("--income") : css("--expense")} value=${d.unrealized} delay=${80}
        sub=${d.cost ? `報酬率 ${pctS(d.unrealized / d.cost)}` : ""} />
      <${Kpi} title="今年已實現損益" icon="coins" color=${d.realized_year >= 0 ? css("--income") : css("--expense")} value=${d.realized_year} delay=${120} />
      <${Kpi} title="今年股利收入" icon="gift" color=${css("--gold")} value=${d.dividends_year} delay=${160}
        sub=${d.nhi_year ? `已扣補充保費 ${money(d.nhi_year)}` : ""} />
    </div>
    <${Tabs} value=${tab} onChange=${setTab} tabs=${[["hold", "持股明細", "pie"], ["events", "交易紀錄", "list"], ["realized", "已實現損益", "coins"], ["perf", "報酬分析", "trend_up"]]} />
    ${tab === "hold" && html`<${Holdings} d=${d} asOf=${asOf} setAsOf=${setAsOf} trade=${trade} showEvents=${showEvents} />`}
    ${tab === "events" && html`<${Events} d=${d} sid=${evSec} setSid=${setEvSec} />`}
    ${tab === "realized" && html`<${Realized} d=${d} />`}
    ${tab === "perf" && html`<${Performance} showEvents=${showEvents} />`}
  </div>`;
}

function Holdings({ d, asOf, setAsOf, trade, showEvents }) {
  const [sel, setSel] = useState(new Set());
  const pal = PALETTE();
  const data = [...d.holdings].filter((h) => h.base_value > 0).sort((a, b) => b.base_value - a.base_value);
  const total = data.reduce((s, h) => s + h.base_value, 0) || 1;
  const donut = useChart(() => ({
    ...chartBase(), tooltip: { ...chartBase().tooltip, trigger: "item", valueFormatter: (v) => money(v) },
    series: [{ type: "pie", radius: ["58%", "86%"], padAngle: 2, itemStyle: { borderRadius: 5 }, label: { show: false },
               data: data.map((h, i) => ({ name: h.name, value: h.base_value, itemStyle: { color: pal[i % pal.length] } })) }],
  }), [d]);
  const menu = (e, h) => openMenu(e, [
    { label: "買進", icon: "plus", run: () => trade("buy", h.id) }, { label: "賣出", icon: "minus", run: () => trade("sell", h.id) },
    { label: "現金股利", icon: "dollar", run: () => trade("cash_div", h.id) }, { label: "股票股利（配股）", icon: "gift", run: () => trade("stock_div", h.id) },
    "-", { label: "查看交易紀錄", icon: "list", run: () => showEvents(h.id) }, { label: "編輯標的", icon: "edit", run: () => openSecurity(h.id) }]);
  const cols = [
    { key: "code", title: "代號", align: "c", render: (h) => html`<b>${h.code}</b>`, sort: (h) => h.code },
    { key: "name", title: "名稱", render: (h) => html`<b>${h.name}</b>`, sort: (h) => h.name, nowrap: true },
    { key: "shares", title: "持股", align: "r", render: (h) => html`<span class="num">${num(h.shares, null, false, 0)}</span>`, sort: (h) => h.shares },
    { key: "avg", title: "平均成本", align: "r", render: (h) => html`<span class="num">${num(h.avg_cost, null, false, 2)}</span>` },
    { key: "price", title: "最近評價市價", align: "r", nowrap: true,
      render: (h) => (h.price ? html`<span class="num">${num(h.price, null, false, 2)}</span><span class="muted small">　${ymd(h.price_date)}</span>` : html`<span class="muted">尚未評價</span>`) },
    { key: "cost", title: "成本", align: "r", render: (h) => html`<span class="num">${num(h.cost, h.currency)}</span>`, sort: (h) => h.cost },
    { key: "mv", title: "帳面價值", align: "r", render: (h) => html`<b class="num">${num(h.market_value, h.currency)}</b>`, sort: (h) => h.market_value },
    { key: "unr", title: "未實現損益", align: "r", render: (h) => html`<span class=${"num " + sgn(h.unrealized)}>${num(h.unrealized, h.currency, true)}</span>`, sort: (h) => h.unrealized },
    { key: "ret", title: "報酬率", align: "r", render: (h) => html`<b class=${"num " + sgn(h.return_pct || 0)}>${pctS(h.return_pct)}</b>`, sort: (h) => h.return_pct || 0 },
  ];
  return html`<div class="row wrap hold-bar"><span class="lbl">持股截至</span><${DateInput} value=${d.as_of} onChange=${setAsOf} />
      <${Btn} kind="link" onClick=${() => setAsOf(null)} disabled=${!asOf}>最新</${Btn}>
      ${data.length > 0 && html`<div class="hold-mix" title="持股比重（依帳面價值）"><span class="lbl">持股比重</span>
        <div class="segbar">${data.map((h, i) => html`<i style=${`flex:${h.base_value};background:${pal[i % pal.length]}`} title=${`${h.name}　${pct(h.base_value / total, 0)}`}></i>`)}</div>
        <div class="mix-legend">${data.slice(0, 4).map((h, i) => html`<span><i style=${`background:${pal[i % pal.length]}`}></i>${h.name} ${pct(h.base_value / total, 0)}</span>`)}</div></div>`}</div>
    <div class="card table-card"><${DataTable} columns=${cols} rows=${d.holdings} selected=${sel} onSelect=${setSel} onActivate=${(h) => showEvents(h.id)}
        onMenu=${menu} defaultSort=${["code", false]} empty="目前沒有持股。按「買進」登錄第一筆投資。" /></div>
    <div class="hold tall-only">
      ${data.length > 0 && html`<${Card} title="持股比重" icon="pie" extra=${html`<span class="muted small">依帳面價值</span>`}>
        <div class="alloc row-chart"><div class="chart small" ref=${donut}></div>
        <div class="legend">${data.map((h, i) => html`<div><i style=${`background:${pal[i % pal.length]}`}></i>${h.name}<span class="num">${pct(h.base_value / total, 0)}</span></div>`)}</div></div>
      </${Card}>`}
    </div>
    <${Tip}>帳面價值＝成本＋已認列的評價。評價以預估淨售價計算（市價×股數，扣除預估賣出手續費與證交稅），成本已含買進手續費，因此未實現損益已包含買賣的手續費與稅。按兩下可查看該標的的交易紀錄，按右鍵可買賣或登錄股利。</${Tip}>`;
}

function Events({ d, sid, setSid }) {
  const per = usePeriod("全部", d.range);
  const [range] = per;
  const [sel, setSel] = useState(new Set());
  const [rows] = useLoad(() => api("invest_events", sid, range[0], range[1]), [sid, range[0], range[1]]);
  const cur = rows && rows.find((r) => sel.has(r.id ?? "j" + r.txn_id));
  async function del(r = cur) {
    if (!r) return info("請先點選一筆交易。");
    if (r.txn_id) return info(`這筆交易來自複式分錄 ${r.cash.replace("分錄 ", "")}，請按兩下開啟該傳票後「作廢」，持股與評價會自動重算。`);
    if (!(await ask(`確定要刪除「${ymd(r.date)} ${r.name} ${r.kind_label}」嗎？\n系統會自動重算之後的成本與分錄。`, { yes: "刪除", danger: true }))) return;
    try { await api("event_delete", r.id); changed(); toast("已刪除並重新計算（Ctrl+Z 可復原）"); } catch (e) { errorBox(e.message); }
  }
  const cols = [
    { key: "date", title: "日期", render: (r) => html`<span class="num">${ymd(r.date)}</span>`, nowrap: true },
    { key: "sec", title: "標的", render: (r) => `${r.code} ${r.name}`.trim(), nowrap: true },
    { key: "kind", title: "類別", align: "c", render: (r) => html`<span class=${"type " + (KIND_CLS[r.kind] || "b-transfer")}>${r.kind_label}</span>` },
    { key: "shares", title: "股數", align: "r", render: (r) => (r.shares ? html`<span class="num">${num(r.shares, null, false, 0)}</span>` : "") },
    { key: "price", title: "價格", align: "r", render: (r) => (r.price ? html`<span class="num">${num(r.price, null, false, 3)}</span>` : "") },
    { key: "fee", title: "手續費／稅", align: "r", render: (r) => (r.fee ? html`<span class="num">${num(r.fee)}</span>` : "") },
    { key: "amount", title: "股利", align: "r", render: (r) => (r.amount ? html`<span class="num">${num(r.amount)}</span>` : "") },
    { key: "nhi", title: "補充保費", align: "r", render: (r) => (r.nhi ? html`<span class="num">${num(r.nhi)}</span>` : "") },
    { key: "cash", title: "交割帳戶", render: (r) => r.cash, nowrap: true },
    { key: "note", title: "備註", elide: true, cls: () => "grow evnote", render: (r) => r.note },
  ].filter((c) => !["shares", "fee", "amount", "nhi"].includes(c.key) || (rows || []).some((r) => r[c.key]));   // 這段期間都是空白的欄位不顯示，其他欄位才放得下
  return html`<div class="card filters"><div class="frow">
      <span class="lbl">標的</span><${Select} value=${sid} onChange=${setSid} options=${[[null, "全部標的"], ...d.securities.map((s) => [s.id, s.label])]} />
      <${PeriodPicker} state=${per} />
      <div class="grow"></div><${Btn} kind="danger" icon="trash" onClick=${() => del()} title="刪除選取的投資交易">刪除</${Btn}></div></div>
    <div class="card table-card"><${DataTable} columns=${cols} rows=${rows || []} rowKey=${(r) => r.id ?? "j" + r.txn_id}
      selected=${sel} onSelect=${setSel} onActivate=${(r) => r.txn_id && openVoucher(r.txn_id)} onDelete=${() => del()}
      onMenu=${(e, r) => openMenu(e, [r.txn_id ? { label: "開啟分錄傳票", icon: "book", run: () => openVoucher(r.txn_id) } : null,
                                        { label: "刪除這筆交易", icon: "trash", danger: true, run: () => del(r) }])}
      empty=${rows ? "這個期間沒有投資交易" : "讀取中…"} /></div>
    <${Tip}>在這裡輸入的買賣、股利與市價評價會自動產生會計分錄（收支明細中類型顯示為「投資」）。「買進／賣出／股利（分錄）」是在複式分錄中連結標的的交易，按兩下可開啟該傳票。賣出不迴轉未實現評價損益，所售股份的評價會在下次市價評價時一併調整。輸入錯誤時請刪除該筆交易（分錄請作廢該傳票），系統會自動重算之後的成本與分錄。</${Tip}>`;
}

function Realized({ d }) {
  const per = usePeriod("今年", d.range);
  const [range] = per;
  const [r] = useLoad(() => api("invest_realized", range[0], range[1]), [range[0], range[1]]);
  const cols = [
    { key: "date", title: "賣出日期", render: (x) => html`<span class="num">${ymd(x.date)}</span>`, sort: (x) => x.date },
    { key: "sec", title: "標的", render: (x) => `${x.code} ${x.name}`.trim(), cls: () => "grow" },
    { key: "shares", title: "股數", align: "r", render: (x) => html`<span class="num">${num(x.shares || 0, null, false, 0)}</span>` },
    { key: "proceeds", title: "實收金額", align: "r", render: (x) => html`<span class="num">${num(x.proceeds)}</span>` },
    { key: "cost", title: "出售成本", align: "r", render: (x) => html`<span class="num">${num(x.cost)}</span>` },
    { key: "gain", title: "已實現損益", align: "r", render: (x) => html`<b class=${"num " + sgn(x.gain)}>${num(x.gain, null, true)}</b>`, sort: (x) => x.gain },
  ];
  return html`<div class="card filters"><div class="frow"><${PeriodPicker} state=${per} label="賣出期間" /></div>
      ${r && html`<div class="sumline"><span>已實現損益合計 <span class=${"num " + sgn(r.realized)}>${money(r.realized, META.base, true)}</span></span>
        <span>股利 <span class="num c-gold">${money(r.dividends)}</span></span>${r.nhi > 0 && html`<span class="muted">（已扣補充保費 ${money(r.nhi)}）</span>`}</div>`}</div>
    <div class="card table-card"><${DataTable} columns=${cols} rows=${r ? r.rows : []} rowKey=${(x) => x.date + x.code + x.shares + x.gain}
      empty=${r ? "這個期間沒有賣出" : "讀取中…"} defaultSort=${["date", true]} /></div>`;
}

function Performance({ showEvents }) {
  const [asOf, setAsOf] = useState(null);
  const [p] = useLoad(() => api("invest_performance", asOf), [asOf]);
  if (!p) return html`<${Skeleton} kind="block" />`;
  const t = p.total;
  const xirr = (r) => (r.xirr != null ? pctS(r.xirr) : r.years > 0 && r.years < 1 ? "未滿一年" : "—");
  const m = (k) => (r) => html`<span class=${"num " + (["realized", "unrealized", "gain"].includes(k) ? sgn(r[k]) : k === "dividends" ? "c-gold" : "")}>${num(r[k])}</span>`;
  const rows = p.rows.length ? [...p.rows, { id: null, code: "", name: "投資組合合計", _total: true, ...t }] : [];
  const cols = [
    { key: "code", title: "代號", align: "c", render: (r) => html`<b>${r.code}</b>` },
    { key: "name", title: "名稱", render: (r) => html`<b>${r.name}</b>${r.shares <= 1e-9 && !r._total ? html`<span class="muted small">（已賣出）</span>` : ""}`, nowrap: true },
    { key: "invested", title: "投入金額", align: "r", render: m("invested") },
    { key: "value", title: "帳面價值", align: "r", render: m("value") },
    { key: "realized", title: "已實現損益", align: "r", render: m("realized") },
    { key: "dividends", title: "股利", align: "r", render: m("dividends") },
    { key: "unrealized", title: "未實現損益", align: "r", render: m("unrealized") },
    { key: "gain", title: "總損益", align: "r", render: (r) => html`<b class=${"num " + sgn(r.gain)}>${num(r.gain, null, true)}</b>` },
    { key: "tr", title: "總報酬率", align: "r", render: (r) => html`<span class=${"num " + sgn(r.total_return || 0)}>${pctS(r.total_return)}</span>` },
    { key: "xirr", title: "年化報酬率", align: "r", render: (r) => html`<span class=${"num " + (r.xirr == null ? "muted" : sgn(r.xirr))}>${xirr(r)}</span>` },
  ];
  const held = t.years < 1 ? `${Math.floor(t.years * 12)} 個月` : `${t.years.toFixed(1)} 年`;
  return html`<div class="card filters"><div class="frow"><span class="lbl">計算至</span><${DateInput} value=${p.as_of} onChange=${setAsOf} />
      <${Btn} kind="link" onClick=${() => setAsOf(null)}>今天</${Btn}></div>
      ${p.rows.length > 0 && html`<div class="sumline"><span>自 ${ymd(t.first_date)} 開始投資：投入 <span class="num">${money(t.invested)}</span></span>
        <span>總損益 <span class=${"num " + sgn(t.gain)}>${money(t.gain, META.base, true)}</span></span>
        <span>總報酬率 <span class=${"num " + sgn(t.total_return || 0)}>${pctS(t.total_return)}</span></span>
        <span>${t.xirr != null ? html`年化報酬率（XIRR）<span class=${"num " + sgn(t.xirr)}>${pctS(t.xirr)}</span>` : html`<span class="muted">持有 ${held}，未滿一年不計算年化報酬率</span>`}</span></div>`}</div>
    <div class="card table-card"><${DataTable} columns=${cols} rows=${rows} rowKey=${(r) => r.id ?? "total"} rowCls=${(r) => (r._total ? "total" : "")}
      onActivate=${(r) => r.id && showEvents(r.id)} empty="尚無投資交易。" /></div>
    <${Tip}>總損益＝已實現損益＋股利（扣除補充保費）＋未實現損益；總報酬率＝總損益 ÷ 投入金額（買進成本含手續費）。年化報酬率以 XIRR（內部報酬率）計算，考慮每筆買進、賣出與股利的日期，相當於「這筆錢每年平均賺幾 %」，可以和定存利率比較；持有未滿一年不換算年化。按兩下可查看該標的的交易紀錄。</${Tip}>`;
}
