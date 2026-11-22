// 新增／編輯帳戶、更新餘額／市值。
import { useEffect, useState } from "preact/hooks";
import { META, api, changed, cur, html, isoToday, money, toast } from "../lib/core.js";
import { AmountInput, Btn, Check, DateInput, Dialog, Field, Icon, Segmented, Select, TextInput, errorBox, openModal } from "../lib/ui.js";

export async function openAccount(aid = null) {
  let form;
  try { form = await api("account_form", aid); } catch (e) { return errorBox(e.message); }
  return openModal((close) => html`<${AccountDialog} form=${form} close=${close} />`);
}

function AccountDialog({ form, close }) {
  const a = form.account;
  const [kind, setKind] = useState(a ? a.kind : "asset");
  const [name, setName] = useState(a ? a.name : "");
  const [category, setCategory] = useState(a ? a.category : form.asset_categories[0]);
  const [code, setCode] = useState(a ? a.code : "");
  const [auto, setAuto] = useState("");
  const [hint, setHint] = useState("");
  const [currency, setCurrency] = useState(a ? a.currency : form.base);
  const [rate, setRate] = useState(a ? a.rate : 1);
  const [opening, setOpening] = useState(a ? a.opening_balance : null);
  const [openDate, setOpenDate] = useState(a ? a.opening_date : form.default_opening);
  const [hasMat, setHasMat] = useState(!!(a && a.maturity_date));
  const [maturity, setMaturity] = useState(a && a.maturity_date ? a.maturity_date : isoToday(365));
  const [interest, setInterest] = useState(a ? a.interest_rate || null : null);
  const [note, setNote] = useState(a ? a.note : "");
  const [msg, setMsg] = useState("");
  const cats = kind === "asset" ? form.asset_categories : form.liability_categories;

  useEffect(() => { if (!cats.includes(category) && !a) setCategory(cats[0]); }, [kind]);
  useEffect(() => {
    api("account_code_hint", kind, category, a ? a.id : null).then((h) => {
      if (a) { setHint(`${h.prefix} 開頭為${h.group}`); return; }
      if (!code.trim() || code.trim() === auto) setCode(h.suggest);
      setAuto(h.suggest);
      setHint(`建議 ${h.suggest}（${h.group}）`);
    });
  }, [kind, category]);

  async function save() {
    setMsg("");
    try {
      const r = await api("account_save", { name, kind, category, code, currency, rate: currency === form.base ? 1 : rate,
        opening_balance: opening || 0, opening_date: openDate, note, maturity_date: hasMat ? maturity : "",
        interest_rate: interest || 0 }, a ? a.id : null);
      changed();
      toast(`已${a ? "更新" : "新增"}帳戶：${r.name}`);
      close(r.id);
    } catch (e) { setMsg(e.message); }
  }

  return html`<${Dialog} title=${a ? "編輯帳戶" : "新增帳戶"} icon="wallet" width="40rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}>
        <${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <${Field} label="帳戶名稱"><${TextInput} value=${name} onInput=${setName} placeholder="例如：郵局活儲、台銀定存、隨身現金" autofocus /></${Field}>
      <${Field} label="性質"><${Segmented} value=${kind} onChange=${setKind}
          options=${[["asset", "資產（存款、投資、現金…）", "bank"], ["liability", "負債（信用卡、貸款…）", "card"]]} /></${Field}>
      <${Field} label="類別"><${TextInput} value=${category} onInput=${setCategory} suggestions=${cats} />
        <div class="row wrap">${cats.map((c) => html`<button type="button" class=${"pillbtn" + (c === category ? " on" : "")} onClick=${() => setCategory(c)}>${c}</button>`)}</div></${Field}>
      <${Field} label="科目代號" hint=${hint}><${TextInput} value=${code} onInput=${(v) => setCode(v.replace(/\D/g, "").slice(0, 6))} placeholder="3～6 位數字" /></${Field}>
      <${Field} label="幣別"><${Select} value=${currency} onChange=${setCurrency} options=${form.currencies.map((c) => [c.code, `${c.name}（${c.code}）`])} /></${Field}>
      ${currency !== form.base && html`<${Field} label="匯率" hint=${`1 ${cur(currency).name} = ? ${cur(form.base).name}`}>
        <${AmountInput} value=${rate} onChange=${setRate} decimals=${4} /></${Field}>`}
      <${Field} label=${kind === "asset" ? "期初餘額" : "期初欠款"} hint="請填入此帳戶在「期初日期」當天的金額，之後的收支會自動累計。">
        <${AmountInput} value=${opening} onChange=${setOpening} code=${currency} suffix=${cur(currency).name} /></${Field}>
      <${Field} label="期初日期"><${DateInput} value=${openDate} onChange=${setOpenDate} /></${Field}>
      <${Field} label="到期"><div class="row wrap"><${Check} checked=${hasMat} onChange=${setHasMat}>設定到期日（定存、債券、保單、貸款）</${Check}>
        ${hasMat && html`<${DateInput} value=${maturity} onChange=${setMaturity} />`}</div></${Field}>
      <${Field} label="年利率"><div class="row"><div style="width:10rem"><${AmountInput} value=${interest} onChange=${setInterest} decimals=${3} placeholder="0" /></div><span>%</span></div></${Field}>
      <${Field} label="備註"><${TextInput} value=${note} onInput=${setNote} placeholder="可記錄帳號末四碼等（可留空）" /></${Field}>
      ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
      <button type="submit" hidden></button>
    </form>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 更新餘額／市值
export const openAdjust = (aid = null) => openModal((close) => html`<${AdjustDialog} aid=${aid} close=${close} />`);

function AdjustDialog({ aid, close }) {
  const [account, setAccount] = useState(aid);
  const [date, setDate] = useState(isoToday());
  const [info, setInfo] = useState(null);
  const [value, setValue] = useState(null);
  const [note, setNote] = useState("市值更新");
  const [msg, setMsg] = useState("");
  useEffect(() => { api("adjust_info", account, date).then((i) => { setInfo(i); if (!account) setAccount(i.account); }); }, [account, date]);
  if (!info) return null;
  const c = info.currency || META.base;
  const d = value == null ? null : value - info.current;
  const good = d == null ? true : info.kind === "asset" ? d >= 0 : d <= 0;
  async function save() {
    setMsg("");
    if (value == null) return setMsg("請輸入實際最新金額");
    try { const n = await api("adjust_save", account, date, value, note); changed(); toast(`已更新「${n}」金額（Ctrl+Z 可復原）`); close(true); }
    catch (e) { setMsg(e.message); }
  }
  return html`<${Dialog} title="更新餘額／市值" icon="refresh" accent="var(--adjust)" width="38rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <p class="hint">適用於市值會變動的資產（保單、外幣…），或帳戶實際餘額與帳本不符時。輸入「目前實際金額」，系統會自動記錄差額。股票、基金請到「投資管理」使用市價評價。</p>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <${Field} label="帳戶"><${Select} value=${account} onChange=${(v) => { setAccount(v); setValue(null); }}
        options=${info.accounts.map((x) => ({ value: x.id, label: x.name, group: x.kind === "asset" ? "資產" : "負債" }))} /></${Field}>
      <${Field} label="日期"><${DateInput} value=${date} onChange=${setDate} /></${Field}>
      <${Field} label="帳本目前金額"><b class="num big-num">${info.kind === "liability" ? "欠款 " : ""}${money(info.current, c)}</b></${Field}>
      ${info.invest && html`<div class="note warn"><${Icon} name="info" />此帳戶的持股由「投資管理」維護，請到投資管理使用「市價評價」。</div>`}
      <${Field} label="實際最新金額"><${AmountInput} value=${value} onChange=${setValue} code=${c} big autofocus suffix=${cur(c).name} /></${Field}>
      <${Field} label="差額"><b class=${"num big-num " + (good ? "c-income" : "c-expense")}>${d == null ? "—" : money(d, c, true)}</b></${Field}>
      <${Field} label="說明"><${TextInput} value=${note} onInput=${setNote} /></${Field}>
      ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
    </form>
  </${Dialog}>`;
}
