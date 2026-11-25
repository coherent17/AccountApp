// 會計科目：新增／修改科目、會計科目表、年度結帳。
import { useEffect, useState } from "preact/hooks";
import { META, api, changed, cur, html, money, num, toast, ymd } from "../lib/core.js";
import { AmountInput, Btn, Check, DataTable, DateInput, Dialog, Field, Icon, Segmented, Select, TextInput, errorBox, info,
         openModal } from "../lib/ui.js";
import { openAccount } from "./account.js";

const NATURES = [["asset", "資產", "bank"], ["liability", "負債", "card"], ["income", "收入", "plus"], ["expense", "費用", "minus"]];
const INVEST_HINT = "投資科目（短期投資、長期投資等）可在複式分錄中連結投資標的與股數，評價請到「投資管理 → 市價評價」選日期並輸入市價，差額列「未實現評價損益」。";

/** 新增會計科目（資產、負債、收入、費用），或修改收入／費用科目。傳回 {key, code, name}。 */
export async function openSubject(nature = null, cid = null) {
  let f;
  try { f = await api("subject_form", cid); } catch (e) { return errorBox(e.message); }
  return openModal((close) => html`<${SubjectDialog} f=${f} nature0=${nature} close=${close} />`);
}
function SubjectDialog({ f, nature0, close }) {
  const c = f.category;
  const [n, setN] = useState(c ? c.kind : nature0 || "asset");
  const [name, setName] = useState(c ? c.name : "");
  const [code, setCode] = useState(c ? c.code : "");
  const [auto, setAuto] = useState("");
  const [hint, setHint] = useState("");
  const acc = n === "asset" || n === "liability";
  const cats = n === "asset" ? f.asset_categories : f.liability_categories;
  const [category, setCategory] = useState(f.asset_categories[0]);
  const [currency, setCurrency] = useState(f.base);
  const [opening, setOpening] = useState(null);
  const [openDate, setOpenDate] = useState(f.default_opening);
  const [budget, setBudget] = useState(c ? c.budget || null : null);
  const [tax, setTax] = useState(c ? c.tax_tag : "");
  const [msg, setMsg] = useState("");
  useEffect(() => { if (acc && !cats.includes(category)) setCategory(cats[0]); }, [n]);
  useEffect(() => {
    if (c) return;
    api("subject_code", n, acc ? category : "").then((h) => {
      if (!code.trim() || code.trim() === auto) setCode(h.suggest);
      setAuto(h.suggest);
      setHint(`建議 ${h.suggest}（${h.prefix} ${h.group}）`);
    });
  }, [n, category]);
  async function save() {
    setMsg("");
    try {
      const r = await api("subject_save", { nature: n, name, code, category, currency, opening, opening_date: openDate, budget, tax_tag: tax }, c ? c.id : null);
      changed(); toast(`已${c ? "更新" : "新增"}會計科目：${r.code} ${r.name}`); close(r);
    } catch (e) { setMsg(e.message); }
  }
  const explain = acc ? (n === "asset" && f.invest_categories.includes(category) ? INVEST_HINT : "資產、負債科目會出現在「帳戶管理」與資產負債表；流動或非流動依科目類別自動判斷。")
    : "收入、費用科目會出現在收支損益表，記帳時可直接選用。";
  return html`<${Dialog} title=${c ? "修改會計科目" : "新增會計科目"} icon="list" width="42rem" guard=${[n, name, code, category, currency, opening, budget, tax]} onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <${Field} label="科目性質">${c ? html`<b>${NATURES.find((x) => x[0] === n)[1]}</b>` : html`<${Segmented} value=${n} onChange=${setN} options=${NATURES} />`}</${Field}>
      <${Field} label="科目代號" hint=${c ? "" : hint}><div class="row narrow"><${TextInput} value=${code} onInput=${(v) => setCode(v.replace(/\D/g, "").slice(0, 6))} placeholder="3～6 位數字" /></div></${Field}>
      <${Field} label="科目名稱"><${TextInput} value=${name} onInput=${setName} placeholder="例如：短期投資、應收帳款、顧問收入" autofocus /></${Field}>
      ${acc && !c && html`
        <${Field} label="科目類別"><${TextInput} value=${category} onInput=${setCategory} suggestions=${cats} />
          <div class="row wrap">${cats.map((x) => html`<button type="button" class=${"pillbtn" + (x === category ? " on" : "")} onClick=${() => setCategory(x)}>${x}</button>`)}</div></${Field}>
        <${Field} label="幣別"><${Select} value=${currency} onChange=${setCurrency} options=${f.currencies} /></${Field}>
        <${Field} label=${n === "asset" ? "期初餘額" : "期初欠款"}><${AmountInput} value=${opening} onChange=${setOpening} code=${currency} suffix=${cur(currency).name} /></${Field}>
        <${Field} label="期初日期"><${DateInput} value=${openDate} onChange=${setOpenDate} /></${Field}>`}
      ${n === "expense" && html`<${Field} label="每月預算"><${AmountInput} value=${budget} onChange=${setBudget} placeholder="不設定" /></${Field}>`}
      ${!acc && html`<${Field} label="稅務歸類"><${Select} value=${tax || ""} onChange=${setTax} options=${f.tax_tags[n]} /></${Field}>`}
      <div class="hint">${explain}</div>
      ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
    </form>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 會計科目表
export const openChart = () => openModal((close) => html`<${ChartDialog} close=${close} />`);
function ChartDialog({ close }) {
  const [arch, setArch] = useState(false);
  const [rows, setRows] = useState(null);
  const [sel, setSel] = useState(new Set());
  const load = () => api("chart", arch).then(setRows);
  useEffect(() => { load(); }, [arch]);
  const keyOf = (r) => (r.key ? r.key.join(":") : "h" + r.code + r.name);
  const cur_ = rows && rows.find((r) => sel.has(keyOf(r)));
  async function edit(r = cur_) {
    if (!r || !r.key) return r ? null : info("請先點選一個會計科目。");
    if (r.key[0] === "special") return info("這是系統科目，由程式自動使用（例如評價損益、兌換損益），不需要也不能修改。");
    const ok = r.key[0] === "account" ? await openAccount(r.key[1]) : await openSubject(null, r.key[1]);
    if (ok) load();
  }
  async function archive() {
    const r = cur_;
    if (!r || !r.key || r.key[0] === "special") return info("請先點選一個可封存的科目（系統科目不可封存）。");
    try {
      if (r.key[0] === "account") {
        if (!r.archived && Math.abs(r.amount || 0) >= 0.005) return info("此科目仍有餘額，請先將餘額轉出再封存。");
        await api("account_archive", r.key[1], !r.archived);
      } else await api("category_update", r.key[1], { archived: !r.archived });
      changed(); load();
    } catch (e) { errorBox(e.message); }
  }
  const cols = [
    { key: "code", title: "科目代號", align: "c", render: (r) => html`<span class=${"num " + (r.style === "section" ? "c-primary b" : "muted")}>${r.code}</span>` },
    { key: "name", title: "會計科目", cls: () => "grow", render: (r) => html`<span class=${"lvl" + r.level}>${r.name}${r.archived ? html`<span class="muted">（已封存）</span>` : ""}</span>` },
    { key: "label", title: "科目類別", render: (r) => html`<span class="muted">${r.label || ""}</span>`, nowrap: true },
    { key: "amount", title: `餘額／本年累計（${META.base}）`, align: "r", render: (r) => (r.amount == null ? "" : html`<span class="num">${num(r.amount)}</span>`) },
  ];
  return html`<${Dialog} title="會計科目表" icon="list" width="66rem" help="chart" cls="listdlg" onClose=${() => close()}
      footer=${html`<${Btn} kind="primary" icon="plus" onClick=${async () => { if (await openSubject()) load(); }}>新增會計科目</${Btn}>
        <${Btn} icon="edit" onClick=${() => edit()}>修改</${Btn}><${Btn} icon="archive" onClick=${archive}>封存／取消封存</${Btn}>
        <div class="grow"></div><${Btn} onClick=${() => close()}>關閉</${Btn}>`}>
    <div class="row wrap" style="margin-bottom:.6rem"><span class="hint grow">資產 1、負債 2、權益 3、收入 4、費用 5、業外損益 7。按兩下科目可修改；新增的科目可立即用於記帳與複式分錄。</span>
      <${Check} checked=${arch} onChange=${setArch}>顯示已封存／隱藏的科目</${Check}></div>
    ${rows && html`<${DataTable} columns=${cols} rows=${rows} rowKey=${keyOf} selected=${sel} onSelect=${setSel} onActivate=${(r) => r.key && edit(r)}
      rowCls=${(r) => (r.style === "section" ? "chart-section" : r.style === "subtotal" ? "chart-sub" : "")} maxHeight="62vh" />`}
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 年度結帳
export async function openYearClose(year) {
  let p;
  try { p = await api("year_close_preview", year); } catch (e) { return errorBox(e.message); }
  return openModal((close) => html`<${YearCloseDialog} p=${p} close=${close} />`);
}
function YearCloseDialog({ p, close }) {
  const [msg, setMsg] = useState("");
  const blocked = p.blocked || !!p.done;
  async function go() {
    try { const n = await api("year_close", p.year); changed(); toast(`${p.year} 年度結帳完成` + (n ? `，已產生 ${n} 張結帳分錄` : "")); close(true); }
    catch (e) { setMsg(e.message); }
  }
  return html`<${Dialog} title=${`${p.year} 年度結帳`} icon="lock" width="52rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>${blocked ? "關閉" : "取消"}</${Btn}>
        ${!blocked && html`<${Btn} kind="primary" icon="lock" onClick=${go}>確認 ${p.year} 年度結帳</${Btn}>`}`}>
    <p class="hint">年度結帳會把 ${p.year} 年的收入、費用與業外損益結轉到「本期損益（累積淨值）」，並將 ${p.year}/12/31（含）以前的帳務鎖定。結帳分錄記錄於日記簿；報表本來就以期初淨值承接前期損益，所以結帳不會改變任何報表金額。</p>
    <div class="section-title sm">結帳前檢查</div>
    ${p.checks.map((c) => html`<div class=${"check-line " + (c.ok ? "c-income" : "c-adjust")}><${Icon} name=${c.ok ? "check" : "alert"} />${c.text}</div>`)}
    <div class="two-col">
      <div><div class="section-title sm">權益變動</div>
        <table class="list compact"><tbody>${p.equity.map((x) => html`<tr><td>${x.name}</td><td class="r num">${money(x.value)}</td></tr>`)}
          <tr class="total"><td>期末淨值</td><td class="r num">${money(p.closing)}</td></tr></tbody></table></div>
      <div><div class="section-title sm">結帳分錄（預覽）</div>
        <table class="list compact"><thead><tr><th>代號</th><th>會計科目</th><th class="r">借方</th><th class="r">貸方</th></tr></thead>
          <tbody>${p.lines.length ? p.lines.map((l) => html`<tr><td class="muted num">${l.code}</td><td>${l.name}</td><td class="r num">${l.debit ? num(l.debit) : ""}</td><td class="r num">${l.credit ? num(l.credit) : ""}</td></tr>`)
            : html`<tr><td colspan="4" class="muted">本年度沒有損益</td></tr>`}</tbody></table></div>
    </div>
    ${p.done && html`<div class="msg ok"><${Icon} name="check" />${p.year} 年度已完成結帳（${p.done}）。如需更正，請先解除結帳。</div>`}
    ${p.blocked && !p.done && html`<div class="msg bad"><${Icon} name="alert" />試算表不平衡，請先檢查帳務。</div>`}
    ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
  </${Dialog}>`;
}
