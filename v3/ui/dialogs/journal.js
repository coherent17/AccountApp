// 複式分錄（傳票）：多行借貸、借貸平衡才能儲存；投資科目可連結標的與股數，外幣科目輸入原幣金額與匯率；常用範本。
import { useEffect, useMemo, useState } from "preact/hooks";
import { META, api, changed, cur, html, isoToday, money, num, toast } from "../lib/core.js";
import { flashRow } from "../lib/ui.js";
import { AmountInput, Btn, Combo, DateInput, Dialog, Field, Icon, Select, TagInput, TextInput, ask, errorBox, openModal } from "../lib/ui.js";
import { openAudit, askVoidReason } from "./txn.js";
import { printVoucher } from "./print.js";
import { openSubject } from "./chart.js";
import { openSecurity } from "./invest.js";

let rid = 0;
const blank = (p = {}) => ({ id: ++rid, key: "", debit: null, credit: null, memo: "", security_id: null, shares: null, price: null,
                             orig: null, rate: null, auto: null, want: null, ...p });

/** 開啟複式分錄。opts：tid（開啟／編輯）、prefill（[{key, debit, credit, memo, ...}]）、date、note、tags。 */
export async function openJournal(opts = {}) {
  let f;
  try { f = await api("journal_form", opts.tid || null); } catch (e) { return errorBox(e.message); }
  return openModal((close) => html`<${JournalDialog} f0=${f} opts=${opts} close=${close} />`);
}

function JournalDialog({ f0, opts, close }) {
  const [f, setF] = useState(f0);
  const t = f.txn;
  const ro = !!(t && t.readonly);
  const chart = useMemo(() => Object.fromEntries(f.chart.map((c) => [c.key, c])), [f]);
  const [date, setDate] = useState(t ? t.date : opts.date || isoToday());
  const [note, setNote] = useState(t ? t.note : opts.note || "");
  const [tags, setTags] = useState(t ? t.tags : opts.tags || []);
  const init = (t ? t.lines : opts.prefill || []).map((l) => {
    const c = chart[l.key];
    const fx = c && c.currency && c.currency !== f.base && !c.investment;
    const base = (l.debit || 0) || (l.credit || 0);
    return blank({ ...l, orig: fx && l.orig ? Math.abs(l.orig) : null, rate: fx ? (l.orig && base ? +(base / Math.abs(l.orig)).toFixed(6) : c.rate) : null });
  });
  while (init.length < 3) init.push(blank());
  const [rows, setRows] = useState(init);
  const [sel, setSel] = useState(null);
  const [info, setInfo] = useState([]);
  const [msg, setMsg] = useState(ro ? t.readonly : "");
  const [busy, setBusy] = useState(false);

  const upd = (id, patch) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const kindOf = (r) => {
    const c = chart[r.key];
    if (!c) return {};
    const div = c.kind === "income";
    const invest = c.key.startsWith("account:") && c.investment;
    const fx = c.key.startsWith("account:") && c.currency && c.currency !== f.base && !c.investment;
    return { c, div, invest, fx, sec: invest || div };
  };
  const secOptions = (r) => {
    const k = kindOf(r);
    if (!k.sec) return [];
    const aid = k.invest ? +r.key.split(":")[1] : null;
    return [{ value: null, label: "（不連結標的）" },
            ...f.securities.filter((s) => (k.div || s.account_id === aid) && (!s.archived || s.id === r.security_id)).map((s) => ({ value: s.id, label: s.label })),
            ...(k.invest ? [{ value: "new", label: "＋ 新增投資標的…" }] : [])];
  };

  // 科目改變：外幣科目帶入匯率；非投資科目清除標的
  function setKey(r, key) {
    const c = chart[key];
    const fx = c && key.startsWith("account:") && c.currency && c.currency !== f.base && !c.investment;
    const keepSec = c && ((key.startsWith("account:") && c.investment) || c.kind === "income");
    upd(r.id, { key, rate: fx ? r.rate || c.rate : null, orig: fx ? r.orig : null,
                ...(keepSec ? {} : { security_id: null, shares: null, price: null }) });
  }
  async function setSec(r, v) {
    if (v === "new") {
      const id = await openSecurity(null, +r.key.split(":")[1]);
      if (!id) return;
      const f2 = await api("journal_form", t ? t.id : null);
      setF({ ...f, securities: f2.securities });
      upd(r.id, { security_id: id });
      return;
    }
    upd(r.id, v == null ? { security_id: null, shares: null, price: null } : { security_id: v });
  }

  // 股數、單價：空白（或先前自動帶入）的金額依標的費率自動計算（買進＝成本含手續費；賣出＝實收；股利＝股數×每股股利）
  async function autoAmount(r) {
    const k = kindOf(r);
    const q = r.shares || 0, p = r.price || 0;
    if (!r.security_id || q <= 0 || p <= 0) return;
    if (k.div) {
      if (!r.debit && (r.auto === "credit" || !r.credit)) upd(r.id, { credit: Math.round(q * p * 100) / 100, auto: "credit" });
      return;
    }
    if (!k.invest || k.c.currency !== f.base) return;
    const empty = !r.debit && !r.credit;
    let side;
    if (r.auto === "credit" || (empty && r.want === "credit")) side = "credit";
    else if (r.auto === "debit" || empty) side = "debit";
    else return;
    const [fee, tax] = await api("trade_fees", r.security_id, side === "debit" ? "buy" : "sell", q, p);
    const v = Math.round((side === "debit" ? q * p + fee : q * p - fee - tax) * 100) / 100;
    upd(r.id, { [side]: v, auto: side });
  }
  function fxAmount(r) {
    const q = r.orig || 0, rate = r.rate || 0;
    if (q <= 0 || rate <= 0) return;
    const side = r.credit && !r.debit ? "credit" : "debit";
    upd(r.id, { [side]: Math.round(q * rate * 100) / 100, auto: side });
  }

  // 投資連結說明：目前持股、平均成本與本行手續費
  const linkSig = rows.map((r) => [r.key, r.security_id, r.shares, r.price, !!r.credit].join("|")).join(";");
  useEffect(() => {
    let alive = true;
    (async () => {
      const parts = [];
      for (const r of rows) {
        if (!r.security_id || r.security_id === "new") continue;
        const s = await api("sec_info", r.security_id);
        parts.push(s.shares ? `${s.label}：目前持股 ${num(s.shares, null, false, 0)} 股，平均成本 ${num(s.avg_cost, null, false, 2)}，帳面成本 ${money(s.cost, s.currency)}`
          : `${s.label}：目前無持股`);
        const q = r.shares || 0, p = r.price || 0;
        if (q > 0 && p > 0 && kindOf(r).div) parts.push(`本行股利 ${num(q, null, false, 0)} 股 × 每股 ${p} ＝ ${money(q * p, s.currency)}`);
        else if (q > 0 && p > 0) {
          const sell = !!r.credit;
          const [fee, tax] = await api("trade_fees", r.security_id, sell ? "sell" : "buy", q, p);
          parts.push(`本行 ${num(q, null, false, 0)} 股 × ${p} ＝ ${money(q * p, s.currency)}，手續費 ${num(fee, null, false, 0)}${sell ? `、證交稅 ${num(tax, null, false, 0)}` : ""}`);
        }
      }
      if (alive) setInfo([...new Set(parts)]);
    })();
    return () => { alive = false; };
  }, [linkSig]);

  const d = rows.reduce((s, r) => s + (r.debit || 0), 0), c = rows.reduce((s, r) => s + (r.credit || 0), 0);
  const diff = Math.round((d - c) * 100) / 100;
  const ok = Math.abs(diff) < 0.005 && d > 0;

  function autoBalance() {
    if (Math.abs(diff) < 0.005) return;
    const rs = [...rows];
    let i = rs.length - 1;
    while (i >= 0 && (rs[i].debit || rs[i].credit)) i--;
    if (i < 0) { rs.push(blank()); i = rs.length - 1; }
    rs[i] = { ...rs[i], [diff > 0 ? "credit" : "debit"]: Math.abs(diff) };
    setRows(rs);
  }
  function applyTemplate(name) {
    const tp = f.templates.find((x) => x.name === name);
    if (!tp) return;
    setRows(tp.lines.map((l) => blank({ key: l.key, debit: l.side === "debit" ? l.amount : null, credit: l.side === "credit" ? l.amount : null,
                                         memo: l.memo, want: l.side, rate: chart[l.key] && chart[l.key].currency !== f.base && !chart[l.key].investment ? chart[l.key].rate : null })));
    if (!note) setNote(name.split("（")[0]);
  }
  async function saveTemplate() {
    const lines = rows.filter((r) => r.key).map((r) => [r.credit && !r.debit ? "credit" : "debit", r.key, r.memo || "", (r.debit || r.credit) || null]);
    if (lines.length < 2) return setMsg("請先選擇至少兩行會計科目，再存成範本");
    const name = await openModal((cl) => html`<${NameDlg} init=${note} close=${cl} />`);
    if (!name) return;
    try { await api("template_add", name, lines); const f2 = await api("journal_form", t ? t.id : null); setF({ ...f, templates: f2.templates }); toast(`已存成範本「${name}」`); }
    catch (e) { errorBox(e.message); }
  }
  async function manage() {
    await openModal((cl) => html`<${TemplatesDlg} close=${cl} />`);
    const f2 = await api("journal_form", t ? t.id : null);
    setF({ ...f, templates: f2.templates });
  }
  async function newSubject() {
    const r = await openSubject();
    if (!r) return;
    const f2 = await api("journal_form", t ? t.id : null);
    setF({ ...f, chart: f2.chart });
    const key = r.key.join(":");
    const empty = rows.find((x) => !x.key);
    if (empty) upd(empty.id, { key }); else setRows([...rows, blank({ key })]);
  }

  async function save(confirmed = false) {
    setMsg(""); setBusy(true);
    try {
      const lines = rows.map((r) => ({ key: r.key, debit: r.debit, credit: r.credit, memo: r.memo, orig: kindOf(r).fx ? r.orig : null,
                                       security_id: typeof r.security_id === "number" ? r.security_id : null, shares: r.shares, price: r.price }));
      const res = await api("journal_save", { date, note, tags, lines }, t ? t.id : null, confirmed);
      if (res.need_confirm) {
        setBusy(false);
        if (await ask(`「${res.need_confirm.join("、")}」已有投資標的，但這張分錄沒有選擇標的與股數，金額將不會計入持股與成本。\n\n確定要這樣儲存嗎？`, { yes: "仍要儲存", no: "回去選擇標的" })) save(true);
        return;
      }
      flashRow(res.id); changed(); toast(`分錄 ${res.voucher} 已儲存，借貸平衡 ✓（Ctrl+Z 可復原）`); close(true);
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  }
  async function voidIt() {
    const reason = await askVoidReason(1);
    if (reason == null) return;
    try { await api("txn_void", [t.id], reason); changed(); toast("傳票已作廢（Ctrl+Z 可復原）"); close(true); } catch (e) { setMsg(e.message); }
  }
  async function delSystem() {
    const what = await api("voucher_event_text", t.id);
    if (!(await ask(`刪除 ${t.voucher} 會一併刪除產生它的投資管理交易${what}，系統會重算之後的成本與分錄。確定要刪除嗎？`, { yes: "刪除", danger: true }))) return;
    try { await api("inv_delete_vouchers", [t.id]); changed(); toast(`已刪除 ${t.voucher}`); close(true); } catch (e) { setMsg(e.message); }
  }

  const subjOptions = useMemo(() => f.chart.map((x) => ({ value: x.key, label: `${x.code}　${x.name}（${x.group}）` })), [f]);
  const title = t ? `分錄傳票　${t.voucher}` : "複式分錄（傳票）";
  const footer = html`
    ${t && !ro && html`<${Btn} kind="danger" icon="trash" onClick=${voidIt}>作廢這張傳票</${Btn}>`}
    ${t && t.system && !t.void && html`<${Btn} kind="danger" icon="trash" onClick=${delSystem} title="一併刪除產生這張傳票的投資管理交易">刪除這張傳票</${Btn}>`}
    ${t && html`<${Btn} kind="link" icon="print" onClick=${() => printVoucher(t.id)}>列印傳票</${Btn}><${Btn} kind="link" onClick=${() => openAudit(t.id)}>修改紀錄</${Btn}>`}
    <div class="grow"></div>
    <${Btn} onClick=${() => close()}>${ro ? "關閉" : "取消"}</${Btn}>
    ${!ro && html`<${Btn} kind="primary" icon="check" disabled=${busy} onClick=${() => save(false)}>儲存</${Btn}>`}`;

  return html`<${Dialog} title=${title} icon="book" width="90rem" onClose=${() => close()} footer=${footer} cls="journal">
    <div class="jtop">
      <${Field} label="日期"><${DateInput} value=${date} onChange=${ro ? () => {} : setDate} /></${Field}>
      ${!ro && html`<${Field} label="範本"><div class="row"><${Select} value=${""} onChange=${applyTemplate} style="flex:1"
          options=${[["", "（選擇常用範本）"], ...f.templates.map((x) => [x.name, x.name])]} />
        <${Btn} onClick=${saveTemplate} title="把目前的科目與金額存成常用範本">存成範本</${Btn}><${Btn} onClick=${manage}>管理範本</${Btn}></div></${Field}>`}
      <${Field} label="摘要" cls="wide"><${TextInput} value=${note} onInput=${ro ? () => {} : setNote} suggestions=${ro ? null : f.notes} placeholder="摘要，例如：房貸繳款 10 月" /></${Field}>
      ${!(t && t.source) && html`<${Field} label="標籤" cls="wide"><${TagInput} value=${tags} onChange=${ro ? () => {} : setTags} suggestions=${f.tags} /></${Field}>`}
    </div>
    ${msg && html`<div class=${"note " + (ro ? "warn" : "bad")}><${Icon} name=${ro ? "lock" : "alert"} />${msg}</div>`}
    <div class="jtable-wrap"><table class="list jtable">
      <colgroup><col style="width:2.4rem" /><col /><col style="width:9rem" /><col style="width:9rem" /><col style="width:23rem" /><col style="width:9.5rem" /></colgroup>
      <thead><tr><th></th><th>會計科目</th><th class="r">借方金額</th><th class="r">貸方金額</th>
        <th>投資標的／股數／單價（外幣：原幣／匯率）</th><th>行備註</th></tr></thead>
      <tbody>${rows.map((r, i) => {
        const k = kindOf(r);
        return html`<tr key=${r.id} class=${sel === r.id ? "sel" : ""} onMouseDown=${() => setSel(r.id)}>
          <td class="muted c">${i + 1}</td>
          <td><${Combo} value=${r.key} onChange=${(v) => setKey(r, v)} options=${subjOptions} disabled=${ro} /></td>
          <td><${AmountInput} value=${r.debit} onChange=${(v) => upd(r.id, { debit: v, auto: null })} placeholder=${r.want === "debit" ? "請輸入" : ""} /></td>
          <td><${AmountInput} value=${r.credit} onChange=${(v) => upd(r.id, { credit: v, auto: null })} placeholder=${r.want === "credit" ? "請輸入" : ""} /></td>
          <td>${k.fx ? html`<div class="row nowrap"><span class="cur">${k.c.currency}</span>
                <${AmountInput} value=${r.orig} onChange=${(v) => { const n = { ...r, orig: v }; upd(r.id, { orig: v }); fxAmount(n); }} code=${k.c.currency} placeholder="原幣金額" />
                <div style="width:7rem"><${AmountInput} value=${r.rate} onChange=${(v) => { const n = { ...r, rate: v }; upd(r.id, { rate: v }); fxAmount(n); }} decimals=${6} placeholder="匯率" /></div></div>`
            : k.sec ? html`<div class="row nowrap"><div style="flex:1;min-width:0"><${Select} value=${r.security_id} onChange=${(v) => setSec(r, v)} options=${secOptions(r)} disabled=${ro} /></div>
                <div style="width:5.5rem"><${AmountInput} value=${r.shares} decimals=${4} placeholder="股數" onChange=${(v) => { const n = { ...r, shares: v }; upd(r.id, { shares: v }); autoAmount(n); }} /></div>
                <div style="width:6rem"><${AmountInput} value=${r.price} decimals=${3} placeholder=${k.div ? "每股股利" : "單價"} onChange=${(v) => { const n = { ...r, price: v }; upd(r.id, { price: v }); autoAmount(n); }} /></div></div>`
            : html`<span class="muted">—</span>`}</td>
          <td><${TextInput} value=${r.memo} onInput=${(v) => upd(r.id, { memo: v })} /></td></tr>`;
      })}</tbody></table>${ro && html`<div class="ro-cover"></div>`}</div>
    <div class="row wrap jtools">
      ${!ro && html`<${Btn} icon="plus" onClick=${() => setRows([...rows, blank()])}>新增一行</${Btn}>
        <${Btn} icon="trash" onClick=${() => { const id = sel || rows[rows.length - 1].id; setRows(rows.length > 1 ? rows.filter((r) => r.id !== id) : rows); setSel(null); }}>刪除選取行</${Btn}>
        <${Btn} icon="refresh" onClick=${autoBalance} title="把借貸差額自動填入最後一行空白金額">自動平衡差額</${Btn}>
        <${Btn} kind="link" icon="plus" onClick=${newSubject}>新增會計科目</${Btn}>`}
      <div class="grow"></div>
      <b class=${ok ? "c-income" : "c-expense"}>借方合計 ${money(d)}　貸方合計 ${money(c)}　${ok ? "✓ 借貸平衡" : `差額 ${money(diff)}`}</b>
    </div>
    ${info.length > 0 && html`<div class="note adjust"><${Icon} name="chart" /><div>投資連結　${info.join("；")}。賣出時請貸記投資科目的出售成本，並自行列出處分投資損益（系統不另產生分錄）；股利科目連結標的後，會計入該標的的股利紀錄。</div></div>`}
    <p class="hint">借方：資產增加、費用發生、負債減少；貸方：資產減少、收入發生、負債增加。外幣科目請輸入原幣金額與匯率，借貸金額（${cur(META.base).name}）會自動換算。投資科目請選擇投資標的並填股數與成交單價，金額空白時會自動帶入含手續費的成本（賣出為扣除手續費與證交稅後的實收金額）；股利科目可選擇標的並填持有股數與每股股利；評價請到「投資管理 → 市價評價」。</p>
  </${Dialog}>`;
}

function NameDlg({ init, close }) {
  const [v, setV] = useState(init || "");
  return html`<${Dialog} title="存成範本" icon="save" width="30rem" onClose=${() => close(null)}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}><${Btn} kind="primary" disabled=${!v.trim()} onClick=${() => close(v.trim())}>儲存</${Btn}>`}>
    <p>範本名稱（金額會一起存起來，套用時可以修改）：</p>
    <form onSubmit=${(e) => { e.preventDefault(); v.trim() && close(v.trim()); }}><${TextInput} value=${v} onInput=${setV} autofocus /></form></${Dialog}>`;
}

function TemplatesDlg({ close }) {
  const [items, setItems] = useState(null);
  const [sel, setSel] = useState(0);
  const [msg, setMsg] = useState("");
  useEffect(() => { api("template_list").then(setItems); }, []);
  if (!items) return null;
  const move = (d) => { const j = sel + d; if (j < 0 || j >= items.length) return; const a = [...items]; [a[sel], a[j]] = [a[j], a[sel]]; setItems(a); setSel(j); };
  async function save() { try { await api("template_save_all", items); toast("已儲存範本"); close(true); } catch (e) { setMsg(e.message); } }
  return html`<${Dialog} title="管理分錄範本" icon="list" width="40rem" onClose=${() => close()}
      footer=${html`<${Btn} icon="up" onClick=${() => move(-1)}>上移</${Btn}><${Btn} icon="down" onClick=${() => move(1)}>下移</${Btn}>
        <${Btn} kind="danger" icon="trash" disabled=${!items.length} onClick=${() => { setItems(items.filter((_, i) => i !== sel)); setSel(0); }}>刪除</${Btn}>
        <div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" onClick=${save}>儲存</${Btn}>`}>
    <p class="hint">點選範本後可改名稱、調整順序或刪除。要修改範本內容，請在複式分錄套用後調整，再「存成範本」。</p>
    <div class="tlist">${items.map((it, i) => html`<div class=${"titem" + (i === sel ? " on" : "")} onMouseDown=${() => setSel(i)}>
      <span class="muted num">${i + 1}</span><${TextInput} value=${it.name} onInput=${(v) => setItems(items.map((x, j) => (j === i ? { ...x, name: v } : x)))} />
      <span class="muted small">${it.lines.length} 行</span></div>`)}</div>
    ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
  </${Dialog}>`;
}
