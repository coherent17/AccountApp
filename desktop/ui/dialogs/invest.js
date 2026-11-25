// 投資管理的視窗：標的、標的類型、標的設定、買進／賣出／股利、市價評價、更新匯率。
import { useEffect, useState } from "preact/hooks";
import { META, api, changed, cur, html, isoToday, money, num, toast, ymd } from "../lib/core.js";
import { AmountInput, Btn, DataTable, DateInput, Dialog, Field, Icon, Select, TextInput, errorBox, info, openModal } from "../lib/ui.js";

const pct = (v, d = 4) => +(v * 100).toFixed(d);

// ------------------------------------------------------------------ 標的
export async function openSecurity(sid = null, accountId = null) {
  let form;
  try { form = await api("security_form", sid, accountId); } catch (e) { return errorBox(e.message); }
  return openModal((close) => html`<${SecurityDialog} form=${form} close=${close} />`);
}

function SecurityDialog({ form: f0, close }) {
  const [form, setForm] = useState(f0);
  const s = form.security;
  const [account, setAccount] = useState(form.account_id || (form.accounts.find((a) => a.invest) || form.accounts[0] || {}).id);
  const [code, setCode] = useState(s ? s.code : "");
  const [name, setName] = useState(s ? s.name : "");
  const [note, setNote] = useState(s ? s.note : "");
  const [type, setType] = useState(s ? s.type_name : "ETF");
  const [fee, setFee] = useState(s ? pct(s.fee_rate) : pct(form.defaults.fee_rate));
  const [feeMin, setFeeMin] = useState(s ? s.fee_min : form.defaults.fee_min);
  const [tax, setTax] = useState(s ? pct(s.tax_rate, 3) : 0.1);
  const [msg, setMsg] = useState("");
  const types = form.types;
  const pick = (t) => { setType(t); const x = types.find((y) => y.name === t); if (x) { setFee(pct(x.fee_rate)); setFeeMin(x.fee_min); setTax(pct(x.tax_rate, 3)); } };
  useEffect(() => { if (!s) pick(types.some((t) => t.name === "ETF") ? "ETF" : types[0]?.name || ""); }, []);
  // 手動改費率、與類型不同時改為「自訂」
  useEffect(() => {
    const t = types.find((y) => y.name === type);
    if (t && (Math.abs(fee - pct(t.fee_rate)) > 1e-7 || feeMin !== t.fee_min || Math.abs(tax - pct(t.tax_rate, 3)) > 1e-7)) setType("");
  }, [fee, feeMin, tax]);
  async function typed(c) {
    setCode(c);
    if (!s && (type === "股票" || type === "ETF")) {
      const t = await api("default_tax", c);
      const want = Math.abs(t - form.defaults.etf_tax) < 1e-9 ? "ETF" : "股票";
      if (want !== type && types.some((x) => x.name === want)) pick(want);
    }
  }
  async function manage() {
    const r = await openTypes(types);
    if (!r) return;
    const f = await api("security_form", s ? s.id : null, account);
    setForm({ ...form, types: f.types });
  }
  async function save() {
    setMsg("");
    try {
      const r = await api("security_save", { account_id: account, code, name, note, type_name: type,
        fee_rate: (fee || 0) / 100, fee_min: feeMin || 0, tax_rate: (tax || 0) / 100 }, s ? s.id : null);
      changed(); toast(`已儲存投資標的：${r.name}`); close(r.id);
    } catch (e) { setMsg(e.message); }
  }
  return html`<${Dialog} title=${s ? "編輯投資標的" : "新增投資標的"} icon="chart" width="42rem" guard=${[code, name, note, type, fee, feeMin, tax]} onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <${Field} label="投資帳戶"><${Select} value=${account} onChange=${setAccount} disabled=${!!s || !!form.account_id}
        options=${form.accounts.map((a) => [a.id, a.label])} /></${Field}>
      <${Field} label="代號"><${TextInput} value=${code} onInput=${typed} placeholder="例如 0050、2330（基金可留空）" autofocus /></${Field}>
      <${Field} label="名稱"><${TextInput} value=${name} onInput=${setName} placeholder="例如 元大台灣50" /></${Field}>
      <${Field} label="備註"><${TextInput} value=${note} onInput=${setNote} /></${Field}>
      <${Field} label="類型"><div class="row"><${Select} value=${type} onChange=${pick} style="flex:1"
          options=${[...types.map((t) => [t.name, `${t.name}（手續費 ${+(t.fee_rate * 100).toFixed(4)}%、證交稅 ${+(t.tax_rate * 100).toFixed(3)}%）`]), ["", "自訂（只用於這個標的）"]]} />
        <${Btn} onClick=${manage}>管理類型…</${Btn}></div></${Field}>
      <${Field} label="手續費率"><div class="row narrow"><${AmountInput} value=${fee} onChange=${setFee} decimals=${4} trim suffix="%" /></div></${Field}>
      <${Field} label="最低手續費"><div class="row narrow"><${AmountInput} value=${feeMin} onChange=${setFeeMin} decimals=${0} suffix="元" /></div></${Field}>
      <${Field} label="證交稅率"><div class="row narrow"><${AmountInput} value=${tax} onChange=${setTax} decimals=${3} trim suffix="%" /></div></${Field}>
      <div class="hint">手續費一般為 0.1425%，有折扣時請輸入折扣後的費率（例如 6 折為 0.0855%）。手續費與證交稅依券商慣例無條件捨去至元。<br />
        投資科目請先在「帳戶管理」建立（類別選「短期投資」、「長期投資」、「股票」、「基金」或「債券」，期初餘額填 0）。</div>
      ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
    </form>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 標的類型
function openTypes(types) {
  return openModal((close) => html`<${TypesDialog} types=${types} close=${close} />`);
}
function TypesDialog({ types, close }) {
  const [rows, setRows] = useState(types.map((t) => ({ name: t.name, old: t.name, fee: pct(t.fee_rate), min: t.fee_min, tax: pct(t.tax_rate, 3) })));
  const [msg, setMsg] = useState("");
  const set = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  async function save() {
    try {
      const problems = await api("security_types_save", rows.map((r) => ({ name: r.name, old: r.old || "",
        fee_rate: +((r.fee || 0) / 100).toFixed(6), fee_min: r.min || 0, tax_rate: +((r.tax || 0) / 100).toFixed(6) })));
      changed(); toast("已儲存標的類型");
      if (problems.length) await info("類型已儲存，但下列標的無法變更費率：\n" + problems.join("\n"));
      close(true);
    } catch (e) { setMsg(e.message); }
  }
  return html`<${Dialog} title="管理標的類型" icon="list" width="52rem" guard=${rows} onClose=${() => close()}
      footer=${html`<${Btn} icon="plus" onClick=${() => setRows([...rows, { name: "", old: "", fee: 0.1425, min: 20, tax: 0.3 }])}>新增類型</${Btn}>
        <div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <table class="list edit"><thead><tr><th>類型名稱</th><th class="r">手續費率</th><th class="r">最低手續費</th><th class="r">證交稅率</th><th></th></tr></thead>
      <tbody>${rows.map((r, i) => html`<tr>
        <td><${TextInput} value=${r.name} onInput=${(v) => set(i, "name", v)} placeholder="例如 股票（6 折）" /></td>
        <td style="width:9rem"><${AmountInput} value=${r.fee} onChange=${(v) => set(i, "fee", v)} decimals=${4} trim suffix="%" /></td>
        <td style="width:8rem"><${AmountInput} value=${r.min} onChange=${(v) => set(i, "min", v)} decimals=${0} suffix="元" /></td>
        <td style="width:8rem"><${AmountInput} value=${r.tax} onChange=${(v) => set(i, "tax", v)} decimals=${3} trim suffix="%" /></td>
        <td><button class="iconbtn" title="刪除這個類型" onClick=${() => setRows(rows.filter((_, j) => j !== i))}><${Icon} name="trash" /></button></td></tr>`)}</tbody></table>
    <p class="hint">修改類型的費率後，屬於該類型的標的會一併改用新費率，市價評價分錄也會依新費率重算（已結帳期間有評價的標的不會變更）。刪除類型時，原屬該類型的標的保留目前費率，改為「自訂」。</p>
    ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 標的設定（清單）
export const openSecurityList = () => openModal((close) => html`<${SecurityListDialog} close=${close} />`);
function SecurityListDialog({ close }) {
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState(new Set());
  const load = () => api("invest_page", null).then((d) => setRows(d.securities));
  useEffect(() => { load(); }, []);
  const cur = rows && rows.find((r) => sel.has(r.id));
  const edit = async (r) => { if (await openSecurity(r.id)) load(); };
  async function archive() {
    try { await api("security_archive", cur.id, !cur.archived); changed(); load(); } catch (e) { errorBox(e.message); }
  }
  async function types() { const f = await api("security_form", null, null); if (await openTypes(f.types)) load(); }
  return html`<${Dialog} title="標的設定" icon="edit" width="66rem" cls="listdlg" onClose=${() => close()}
      footer=${html`<${Btn} icon="plus" onClick=${async () => { if (await openSecurity()) load(); }}>新增標的</${Btn}>
        <${Btn} icon="edit" disabled=${!cur} onClick=${() => edit(cur)}>編輯</${Btn}>
        <${Btn} icon="list" onClick=${types}>管理類型</${Btn}>
        <${Btn} icon="archive" disabled=${!cur} onClick=${archive} title="封存後不再出現在選單中（資料保留）；已無持股的標的才可封存">${cur && cur.archived ? "取消封存" : "封存"}</${Btn}>
        <div class="grow"></div><${Btn} kind="primary" onClick=${() => close()}>關閉</${Btn}>`}>
    ${rows && html`<${DataTable} rows=${rows} selected=${sel} onSelect=${setSel} onActivate=${edit} maxHeight="55vh"
      columns=${[{ key: "code", title: "代號", align: "c", render: (r) => html`<b>${r.code}</b>` },
                 { key: "name", title: "名稱", render: (r) => html`<b>${r.name}</b>${!!r.archived && html`<span class="muted">（已封存）</span>`}`, nowrap: true },
                 { key: "acc", title: "投資科目", render: (r) => r.account_name, nowrap: true },
                 { key: "type", title: "類型", render: (r) => r.type_name || "自訂" },
                 { key: "fee", title: "手續費率", align: "r", render: (r) => `${+(r.fee_rate * 100).toFixed(4)}%` },
                 { key: "min", title: "最低手續費", align: "r", render: (r) => `${num(r.fee_min, null, false, 0)} 元` },
                 { key: "tax", title: "證交稅率", align: "r", render: (r) => `${+(r.tax_rate * 100).toFixed(3)}%` },
                 { key: "note", title: "備註", elide: true, render: (r) => r.note }]} />`}
    <p class="hint">按兩下或點選後按「編輯」，可修改代號、名稱、類型、手續費率、最低手續費與證交稅率。費率改變時，該標的的市價評價分錄會依新費率重新計算。</p>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 買進、賣出、股利
const KIND = { buy: ["買進", "var(--expense)", "plus"], sell: ["賣出", "var(--income)", "minus"],
               cash_div: ["現金股利", "var(--gold)", "gift"], stock_div: ["股票股利（配股）", "var(--adjust)", "gift"] };
const HINTS = {
  buy: "手續費依標的費率自動帶入（可修改）。成本＝成交金額＋手續費。",
  sell: "手續費與證交稅依標的費率自動帶入（可修改）。已實現損益＝淨價款－平均成本。",
  cash_div: "單筆股利達 2 萬元時，自動帶入 2.11% 二代健保補充保費，可修改。",
  stock_div: "股票股利（配股）只增加股數，總成本不變，平均成本自動下降。",
};

export async function openTrade(kind, sid = null) {
  return openModal((close) => html`<${TradeDialog} kind=${kind} sid0=${sid} close=${close} />`);
}
function TradeDialog({ kind, sid0, close }) {
  const [date, setDate] = useState(isoToday());
  const [sid, setSid] = useState(sid0);
  const [f, setF] = useState(null);
  const [shares, setShares] = useState(null);
  const [price, setPrice] = useState(null);
  const [fee, setFee] = useState(null);
  const [tax, setTax] = useState(null);
  const [feeTouched, setFeeTouched] = useState(false);
  const [amount, setAmount] = useState(null);
  const [nhi, setNhi] = useState(null);
  const [nhiTouched, setNhiTouched] = useState(false);
  const [cash, setCash] = useState(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => {
    api("trade_form", sid, date).then((x) => {
      setF(x);
      if (x.security && x.security !== sid) setSid(x.security);
      if (x.cash) setCash((c) => (x.cash.some((a) => a.id === c) ? c : (x.cash.find((a) => a.id === x.last_cash) || x.cash[0] || {}).id ?? null));
      if ((kind === "buy" || kind === "sell") && price == null && x.state && x.state.price) setPrice(x.state.price);
    });
  }, [sid, date]);
  useEffect(() => {
    if ((kind === "buy" || kind === "sell") && !feeTouched && sid) {
      api("trade_fees", sid, kind, shares || 0, price || 0).then(([a, b]) => { setFee(a || null); setTax(b || null); });
    }
  }, [sid, shares, price, feeTouched]);
  useEffect(() => { if (kind === "cash_div" && !nhiTouched) api("suggest_nhi", amount || 0).then((v) => setNhi(v || null)); }, [amount]);
  if (!f) return null;
  const c = f.currency || META.base;
  const st = f.state || { shares: 0, avg_cost: 0, price: 0 };
  const [label, color, icon] = KIND[kind];
  let calc = null;
  const q = shares || 0, p = price || 0;
  if (kind === "buy") calc = html`應付金額 <b class="num">${money(q * p + (fee || 0), c)}</b>（成本，含手續費）`;
  else if (kind === "sell") {
    const proceeds = q * p - (fee || 0) - (tax || 0), cost = st.avg_cost * q, g = proceeds - cost;
    calc = html`實收金額 <b class="num">${money(proceeds, c)}</b>　｜　出售成本 <b class="num">${money(cost, c)}</b>　｜　預估已實現損益
      <b class=${"num " + (g >= 0 ? "c-income" : "c-expense")}>${money(g, c, true)}</b>`;
  } else if (kind === "cash_div") calc = html`實際入帳 <b class="num">${money((amount || 0) - (nhi || 0), c)}</b>`;
  else calc = html`配股後持股 <b class="num">${num(st.shares + q, null, false, 0)}</b>`;
  async function newSec() { const id = await openSecurity(); if (id) setSid(id); }
  async function save() {
    setMsg("");
    if (!sid) return setMsg("請先新增投資標的");
    try {
      const l = await api("trade_save", sid, kind, { date, shares, price, fee, tax, amount, nhi, cash: kind === "stock_div" ? null : cash, note });
      changed(); toast(`已登錄${l}，分錄已自動產生（Ctrl+Z 可復原）`); close(true);
    } catch (e) { setMsg(e.message); }
  }
  return html`<${Dialog} title=${label} icon=${icon} accent=${color} width="42rem" guard=${[shares, amount, note]} onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <${Field} label="投資標的" hint=${sid ? `目前持股 ${num(st.shares, null, false, 0)}　平均成本 ${num(st.avg_cost, null, false, 2)}　最近評價市價 ${num(st.price, null, false, 2)}` : "請先新增投資標的"}>
        <div class="row"><${Select} value=${sid} onChange=${setSid} style="flex:1" options=${f.securities.map((s) => [s.id, `${s.label}（${s.account_name}）`])} />
          <${Btn} kind="link" icon="plus" onClick=${newSec}>新增標的</${Btn}></div></${Field}>
      <${Field} label="日期"><${DateInput} value=${date} onChange=${setDate} /></${Field}>
      ${(kind === "buy" || kind === "sell") && html`
        <${Field} label="股數（單位）"><${AmountInput} value=${shares} onChange=${setShares} decimals=${4} trim autofocus /></${Field}>
        <${Field} label="成交價"><${AmountInput} value=${price} onChange=${setPrice} decimals=${4} trim suffix=${cur(c).name} /></${Field}>
        <${Field} label="手續費"><${AmountInput} value=${fee} onChange=${(v) => { setFee(v); setFeeTouched(true); }} code=${c} /></${Field}>
        ${kind === "sell" && html`<${Field} label="證券交易稅"><${AmountInput} value=${tax} onChange=${(v) => { setTax(v); setFeeTouched(true); }} code=${c} /></${Field}>`}`}
      ${kind === "stock_div" && html`<${Field} label="配發股數"><${AmountInput} value=${shares} onChange=${setShares} decimals=${4} trim autofocus /></${Field}>`}
      ${kind === "cash_div" && html`
        <${Field} label="股利總額"><${AmountInput} value=${amount} onChange=${setAmount} code=${c} autofocus /></${Field}>
        <${Field} label="健保補充保費"><${AmountInput} value=${nhi} onChange=${(v) => { setNhi(v); setNhiTouched(true); }} code=${c} /></${Field}>`}
      ${kind !== "stock_div" && html`<${Field} label="交割帳戶" hint="扣款或入帳的銀行帳戶">
        <${Select} value=${cash} onChange=${setCash} options=${(f.cash || []).map((a) => [a.id, a.name])} /></${Field}>`}
      <${Field} label="備註"><${TextInput} value=${note} onInput=${setNote} /></${Field}>
      <div class="calcbar" style=${`border-color:${color}`}>${calc}</div>
      <div class="hint">${HINTS[kind]}</div>
      ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
    </form>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 市價評價
export const openPrices = () => openModal((close) => html`<${PriceDialog} close=${close} />`);
function PriceDialog({ close }) {
  const [date, setDate] = useState(isoToday());
  const [rows, setRows] = useState(null);
  const [vals, setVals] = useState({});
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("price_form", date).then(setRows); }, [date]);
  async function fetch() {
    setBusy(true); setMsg(null);
    try {
      const r = await api("fetch_prices");
      const next = { ...vals };
      let n = 0;
      for (const h of rows) { const p = r.prices[h.code.trim()]; if (p && !h.sold) { next[h.id] = p; n++; } }
      setVals(next);
      setMsg({ text: `已填入 ${n} 檔收盤價（來源：${r.source}），請確認後按「產生評價分錄」。` });
    } catch (e) { setMsg({ bad: true, text: e.message }); } finally { setBusy(false); }
  }
  // 從 Excel 複製「代號、價格」貼上：先看對應結果，確認後才填入
  async function pastePrices(text = "") {
    const got = await openModal((cl) => html`<${PastePrices} text0=${text} date=${date} close=${cl} />`);
    if (!got) return;
    const next = { ...vals };
    for (const m of got) next[m.id] = m.price;
    setVals(next);
    setMsg({ text: `已填入 ${got.length} 檔市價，請確認後按「產生評價分錄」。` });
  }
  const onPaste = (e) => { const t = e.clipboardData?.getData("text") || ""; if (/[\t\n]/.test(t.trim())) { e.preventDefault(); pastePrices(t); } };
  async function save() {
    setMsg(null);
    try {
      const n = await api("price_save", date, rows.filter((h) => !h.sold).map((h) => [h.id, vals[h.id] || 0]));
      changed(); toast(`已產生 ${n} 檔評價分錄（Ctrl+Z 可復原）`); close(true);
    } catch (e) { setMsg({ bad: true, text: e.message }); }
  }
  return html`<${Dialog} title="市價評價" icon="refresh" width="56rem" cls="listdlg" guard=${vals} onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>產生評價分錄</${Btn}>`}>
    <div class="row wrap" style="margin-bottom:.8rem"><span class="lbl">評價日期</span><${DateInput} value=${date} onChange=${setDate} />
      <div class="grow"></div><${Btn} icon="clip" onClick=${() => pastePrices()} title="從 Excel 複製代號與價格兩欄，一次貼上">貼上價格…</${Btn}>${META.online && html`<${Btn} icon="download" disabled=${busy} onClick=${fetch}>${busy ? "下載中…" : "從網路取得收盤價"}</${Btn}>`}</div>
    ${rows && (rows.length === 0 ? html`<div class="note">這個日期沒有持股。</div>` : html`<div class="tablewrap" onPaste=${onPaste}><table class="list edit ptable sticky">
      <thead><tr><th>代號</th><th>名稱</th><th class="r">持股</th><th class="r">最近評價市價</th><th class="r" style="width:13rem">評價市價</th></tr></thead>
      <tbody>${rows.map((h) => html`<tr><td><b>${h.code}</b></td><td>${h.name}</td><td class="r num">${num(h.shares, null, false, 0)}</td>
        <td class="r num muted">${h.price ? num(h.price, null, false, 2) : h.sold ? "已全數賣出" : "尚未評價"}</td>
        <td>${h.sold ? html`<span class="muted small">剩餘帳面價值 ${num(h.market_value, null, false, 0)} 將歸零</span>`
          : html`<${AmountInput} value=${vals[h.id] ?? null} onChange=${(v) => setVals({ ...vals, [h.id]: v })} decimals=${4} trim placeholder="輸入市價" />`}</td></tr>`)}</tbody></table></div>`)}
    <p class="hint">選擇評價日期並輸入市價（留空表示這檔不評價）。按「產生評價分錄」後才會把帳面價值調整為預估淨售價（市價×股數，扣除預估賣出手續費與證交稅），差額記為「未實現評價損益」；同一天再次評價會取代先前的市價。買進、賣出不會自動評價；已全數賣出的標的，剩餘評價會自動歸零。輸入錯誤時，可到「交易紀錄」刪除該筆市價評價。</p>
    ${msg && html`<div class=${"msg " + (msg.bad ? "bad" : "ok")}><${Icon} name=${msg.bad ? "alert" : "check"} />${msg.text}</div>`}
  </${Dialog}>`;
}

function PastePrices({ text0, date, close }) {
  const [text, setText] = useState(text0);
  const [r, setR] = useState(null);
  useEffect(() => {
    if (!text.trim()) return setR(null);
    const t = setTimeout(() => api("price_paste", text, date).then(setR).catch((e) => errorBox(e.message)), 200);
    return () => clearTimeout(t);
  }, [text]);
  const list = (title, items, cls) => items.length > 0 && html`<div class=${"pp-note " + cls}><b>${title}（${items.length}）</b>${items.slice(0, 8).map((x) => html`<span>${x}</span>`)}${items.length > 8 ? "…" : ""}</div>`;
  return html`<${Dialog} title="貼上價格" icon="clip" width="56rem" onClose=${() => close(null)}
      footer=${html`<span class="hint">只會填入市價欄，還要再按「產生評價分錄」才會入帳。</span><div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}>
        <${Btn} kind="primary" icon="check" disabled=${!r || !r.matches.length} onClick=${() => close(r.matches)}>填入${r ? ` ${r.matches.length} 檔` : ""}</${Btn}>`}>
    <div class="pp-grid"><div><p class="muted" style="margin-top:0">在 Excel 選取「代號」與「價格」兩欄，按 Ctrl+C 複製，再到下面按 Ctrl+V 貼上。</p>
      <textarea class="fb-text" rows="9" value=${text} onInput=${(e) => setText(e.target.value)} placeholder=${"0050\t109.5\n2330\t1045"} autofocus></textarea></div>
      <div class="pp-res">${!r ? html`<div class="empty-mini">貼上後，這裡會顯示對應到的持股。</div>` : html`
        ${r.matches.length > 0 && html`<table class="list compact"><thead><tr><th>標的</th><th class="r">上次</th><th class="r">市價</th></tr></thead>
          <tbody>${r.matches.map((m) => html`<tr class=${m.jump ? "jump" : ""}><td>${m.code} ${m.name}${m.jump ? html` <span class="type b-adjust">差很多，請確認</span>` : ""}</td>
            <td class="r num muted">${m.old ? num(m.old, null, false, 2) : "—"}</td><td class="r num"><b>${num(m.price, null, false, 2)}</b></td></tr>`)}</tbody></table>`}
        ${list("看不懂的列", r.problems, "bad")}${list("不是您的持股", r.unknown, "")}${list("沒有貼到價格的持股", r.missing, "")}`}</div></div>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 匯率
export const openRates = () => openModal((close) => html`<${RateDialog} close=${close} />`);
function RateDialog({ close }) {
  const [rows, setRows] = useState(null);
  const [vals, setVals] = useState({});
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("rate_form").then((r) => { setRows(r); setVals(Object.fromEntries(r.map((x) => [x.code, x.rate]))); }); }, []);
  async function fetch() {
    setBusy(true);
    try {
      const r = await api("fetch_rates", META.base);
      const next = { ...vals }; let n = 0;
      for (const x of rows) if (r.rates[x.code]) { next[x.code] = r.rates[x.code]; n++; }
      setVals(next); setMsg({ text: `已填入 ${n} 種匯率（來源：${r.source}），請確認後按「儲存」。` });
    } catch (e) { setMsg({ bad: true, text: e.message }); } finally { setBusy(false); }
  }
  async function save() {
    try { await api("rate_save", vals); changed(); toast("匯率已更新"); close(true); } catch (e) { setMsg({ bad: true, text: e.message }); }
  }
  return html`<${Dialog} title="更新匯率" icon="refresh" width="40rem" guard=${vals} onClose=${() => close()}
      footer=${html`${META.online && rows && rows.length > 0 && html`<${Btn} icon="download" disabled=${busy} onClick=${fetch}>${busy ? "下載中…" : "從網路取得參考匯率"}</${Btn}>`}
        <div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" disabled=${!rows || !rows.length} onClick=${save}>儲存</${Btn}>`}>
    ${rows && (rows.length === 0 ? html`<div class="note">目前沒有外幣帳戶。</div>` : html`<div class="form">${rows.map((x) => html`
      <${Field} label=${`1 ${x.name}（${x.code}）＝`} hint=${"使用的帳戶：" + x.accounts.join("、")}>
        <${AmountInput} value=${vals[x.code]} onChange=${(v) => setVals({ ...vals, [x.code]: v })} decimals=${4} trim suffix=${cur(META.base).name} /></${Field}>`)}</div>`)}
    <p class="hint">可參考銀行牌告的「即期」買賣中價。匯率變動造成的價值差異會列入「兌換損益」。</p>
    ${msg && html`<div class=${"msg " + (msg.bad ? "bad" : "ok")}><${Icon} name=${msg.bad ? "alert" : "check"} />${msg.text}</div>`}
  </${Dialog}>`;
}
