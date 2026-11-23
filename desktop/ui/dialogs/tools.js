// 月結小幫手、到期提醒中心、資料健康檢查、月報。帳務判斷都在 Python（core/monthclose、reminders、health）。
import { useEffect, useState } from "preact/hooks";
import { api, changed, html, isoToday, money, toast, ymd } from "../lib/core.js";
import { AmountInput, Btn, DateInput, Dialog, Field, Icon, Segmented, Select, TextInput, ask, errorBox, openModal } from "../lib/ui.js";
import { openDue, openReconcile } from "./more.js";
import { openPrices } from "./invest.js";
import { openPreview } from "./print.js";

const KIND_ICON = { insurance: "heart", card: "card", tax: "dollar", dividend: "coins", other: "bell",
                    maturity: "bank", recurring: "restore" };
const KIND_COLOR = { insurance: "var(--expense)", card: "var(--transfer)", tax: "var(--gold)", dividend: "var(--income)",
                     other: "var(--primary)", maturity: "var(--adjust)", recurring: "var(--primary)" };
const WEEK = "日一二三四五六";
const ymLabel = (ym) => `${+ym.slice(0, 4)} 年 ${+ym.slice(5)} 月`;

/** 時間軸上的一件事：左邊日期方塊，右邊名稱與說明。 */
export function EventRow({ e, onEdit }) {
  const d = new Date(e.date + "T00:00:00");
  return html`<div class=${"evt" + (e.urgent ? " urgent" : "")} style=${`--c:${KIND_COLOR[e.kind] || "var(--primary)"}`}>
    <div class="evt-date"><small>${d.getMonth() + 1} 月</small><b>${d.getDate()}</b><small>週${WEEK[d.getDay()]}</small></div>
    <span class="evt-ic"><${Icon} name=${KIND_ICON[e.kind] || "bell"} /></span>
    <div class="evt-txt"><b>${e.title}</b><small>${e.sub}${e.interest ? `　預估利息 ${money(e.interest, e.currency)}` : ""}</small></div>
    ${e.amount ? html`<span class="evt-amt num">${money(e.amount, e.currency)}</span>` : null}
    <span class="evt-when">${e.when}</span>
    ${onEdit && e.source === "custom" ? html`<button class="evt-edit" title="修改這個提醒" onClick=${() => onEdit(e.id)}><${Icon} name="edit" /></button>` : null}
  </div>`;
}

// ------------------------------------------------------------------ 到期提醒中心
export const openReminders = () => openModal((close) => html`<${ReminderCenter} close=${close} />`);
function ReminderCenter({ close }) {
  const [d, setD] = useState(null);
  const load = () => api("reminders_upcoming", 90).then(setD).catch((e) => errorBox(e.message));
  useEffect(() => { load(); }, []);
  async function edit(id) {
    const item = id ? d.custom.find((c) => c.id === id) : null;
    if (await openModal((c) => html`<${ReminderEdit} item=${item} kinds=${d.kinds} freqs=${d.freqs} close=${c} />`)) { changed(); load(); }
  }
  const groups = [];
  for (const e of d ? d.events : []) {
    const k = e.date.slice(0, 7);
    if (!groups.length || groups[groups.length - 1][0] !== k) groups.push([k, []]);
    groups[groups.length - 1][1].push(e);
  }
  const freqName = (f) => (d.freqs.find((x) => x[0] === f) || [, ""])[1];
  return html`<${Dialog} title="到期提醒中心" icon="calendar" width="58rem" cls="listdlg" onClose=${() => close()}
      footer=${html`<span class="hint">定存到期、定期交易與 5 月報稅會自動列出；保費、信用卡繳款等可以自己新增。</span><div class="grow"></div>
        <${Btn} onClick=${() => close()}>關閉</${Btn}><${Btn} kind="primary" icon="plus" onClick=${() => edit(null)}>新增提醒</${Btn}>`}>
    ${!d ? html`<div class="muted">讀取中…</div>` : html`<div class="tablewrap remind-scroll">
      ${groups.length === 0 && html`<div class="empty">接下來 90 天沒有排定的事。</div>`}
      ${groups.map(([k, evs]) => html`<div class="evt-month">${ymLabel(k)}</div>${evs.map((e) => html`<${EventRow} e=${e} onEdit=${edit} />`)}`)}
      ${d.custom.length > 0 && html`<div class="evt-month">我設定的提醒（${d.custom.length}）</div>
        ${d.custom.map((c) => html`<div class="mine" onClick=${() => edit(c.id)}>
          <span class="evt-ic" style=${`--c:${KIND_COLOR[c.kind]}`}><${Icon} name=${KIND_ICON[c.kind]} /></span>
          <b>${c.title}</b><span class="muted">${freqName(c.freq)}・${c.freq === "monthly" ? `每月 ${+c.date.slice(8)} 日` : c.freq === "yearly" ? `每年 ${+c.date.slice(5, 7)}/${+c.date.slice(8)}` : ymd(c.date)}
          ${c.amount ? `・${money(c.amount)}` : ""}・提前 ${c.lead} 天提醒</span><div class="grow"></div><${Icon} name="edit" /></div>`)}`}
    </div>`}
  </${Dialog}>`;
}

function ReminderEdit({ item, kinds, freqs, close }) {
  const [title, setTitle] = useState(item ? item.title : "");
  const [kind, setKind] = useState(item ? item.kind : "insurance");
  const [freq, setFreq] = useState(item ? item.freq : "yearly");
  const [date, setDate] = useState(item ? item.date : isoToday());
  const [amount, setAmount] = useState(item ? item.amount : null);
  const [lead, setLead] = useState(item ? item.lead : 7);
  const [note, setNote] = useState(item ? item.note : "");
  const [msg, setMsg] = useState("");
  async function save() {
    try { await api("reminder_save", { id: item && item.id, title, kind, freq, date, amount, lead, note }); toast(`已儲存提醒：${title}`); close(true); }
    catch (e) { setMsg(e.message); }
  }
  async function del() {
    if (!(await ask(`刪除提醒「${item.title}」？`, { yes: "刪除", danger: true }))) return;
    await api("reminder_delete", item.id); toast("已刪除提醒"); close(true);
  }
  const placeholder = { insurance: "例如：國泰人壽保費", card: "例如：國泰信用卡繳款", tax: "例如：房屋稅、地價稅", dividend: "例如：0056 除息", other: "例如：健康檢查" }[kind];
  return html`<${Dialog} title=${item ? "修改提醒" : "新增提醒"} icon="bell" width="40rem" onClose=${() => close()}
      footer=${html`${item && html`<${Btn} kind="danger" icon="trash" onClick=${del}>刪除</${Btn}>`}<div class="grow"></div>
        <${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <${Field} label="種類"><${Segmented} value=${kind} onChange=${(k) => { setKind(k); if (!item) setFreq({ card: "monthly", other: "once" }[k] || "yearly"); }} options=${kinds.map(([k, n]) => [k, n, KIND_ICON[k]])} /></${Field}>
      <${Field} label="名稱"><${TextInput} value=${title} onInput=${setTitle} placeholder=${placeholder} autofocus /></${Field}>
      <${Field} label="重複"><${Segmented} value=${freq} onChange=${setFreq} options=${freqs} /></${Field}>
      <${Field} label=${freq === "once" ? "日期" : "第一次的日期"} hint=${freq === "monthly" ? "之後每月同一天（小月為月底）" : freq === "yearly" ? "之後每年同一天" : ""}>
        <${DateInput} value=${date} onChange=${setDate} /></${Field}>
      <${Field} label="金額"><${AmountInput} value=${amount} onChange=${setAmount} placeholder="可留空" /></${Field}>
      <${Field} label="提前提醒"><${Select} value=${lead} onChange=${setLead}
          options=${[[0, "當天"], [3, "3 天前"], [7, "7 天前"], [14, "14 天前"], [30, "30 天前"]]} /></${Field}>
      <${Field} label="說明"><${TextInput} value=${note} onInput=${setNote} placeholder="例如：從郵局活儲自動扣款（可留空）" /></${Field}>
      ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
      <button type="submit" hidden></button>
    </form>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 資料健康檢查
const STATUS = { ok: ["check", "正常"], info: ["info", "提醒"], warn: ["alert", "建議處理"], bad: ["alert", "需要處理"] };

/** 執行健康檢查並顯示結果。完成檢查後傳回 true。 */
export const openHealth = () => openModal((close) => html`<${Health} close=${close} />`);
function Health({ close }) {
  const [r, setR] = useState(null);
  const run = () => { setR(null); api("health_run").then((x) => setTimeout(() => setR(x), 450)).catch((e) => errorBox(e.message)); };
  useEffect(run, []);
  async function act(a) {
    if (a === "due") await openDue();
    else if (a === "recon") await openReconcile();
    else if (a === "prices") await openPrices();
    else { close(true); window.__go(a === "yearclose" ? "reports" : "settings"); return; }
    changed(); run();
  }
  const tone = !r ? "run" : r.bad ? "bad" : r.warn ? "warn" : "ok";
  const label = { backup: "設定備份", backup2: "設定備份", due: "確認入帳", recon: "去對帳", prices: "市價評價", yearclose: "到財務報表", restore: "還原備份" };
  return html`<${Dialog} title="資料健康檢查" icon="heart" width="50rem" cls="listdlg" onClose=${() => close(!!r)}
      footer=${html`<div class="grow"></div><${Btn} icon="refresh" onClick=${run} disabled=${!r}>重新檢查</${Btn}>
        <${Btn} icon="print" onClick=${async () => openPreview(await api("health_html"), "帳務健康檢查報告")} disabled=${!r}>列印報告</${Btn}>
        <${Btn} kind="primary" onClick=${() => close(!!r)}>完成</${Btn}>`}>
    <div class=${"verdict " + tone}>
      <span class="v-ic">${r ? html`<${Icon} name=${r.bad || r.warn ? "alert" : "check"} size="2rem" />` : html`<i class="spin"></i>`}</span>
      <div><b>${r ? r.summary : "正在檢查帳本…"}</b>
        <small>${r ? `檢查時間 ${r.at.replace(/-/g, "/")}・共 ${r.checks.length} 項` : "確認檔案完整、借貸平衡、備份正常"}</small></div>
    </div>
    <div class="tablewrap hc-list">${r && r.checks.map((c, i) => html`<div class=${"hc " + c.status} style=${`animation-delay:${i * 60}ms`}>
      <span class="hc-ic"><${Icon} name=${STATUS[c.status][0]} /></span>
      <div class="hc-txt"><b>${c.title}</b><small>${c.detail}</small></div>
      <span class="hc-tag">${STATUS[c.status][1]}</span>
      ${c.action && label[c.action] ? html`<${Btn} kind="ghost" onClick=${() => act(c.action === "backup2" ? "backup" : c.action)}>${label[c.action]}</${Btn}>` : null}
    </div>`)}</div>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 月報
export async function previewMonthly(ym) {
  try { await openPreview(await api("monthly_html", ym), `${ymLabel(ym)} 月報`); return true; } catch (e) { errorBox(e.message); return false; }
}
export async function openMonthly() {
  let st;
  try { st = await api("month_close"); } catch (e) { return errorBox(e.message); }
  return openModal((close) => html`<${MonthlyPick} months=${st.months} ym0=${st.ym} close=${close} />`);
}
function MonthlyPick({ months, ym0, close }) {
  const [ym, setYm] = useState(ym0);
  return html`<${Dialog} title="月報" icon="print" width="30rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}>
        <${Btn} kind="primary" icon="eye" onClick=${() => { close(); previewMonthly(ym); }}>預覽月報</${Btn}>`}>
    <p class="muted" style="margin-top:0">一頁看完一個月：收支、分類與預算、較大的支出、淨資產與投資，以及接下來的提醒。</p>
    <${Field} label="月份"><${Select} value=${ym} onChange=${setYm} options=${months.map((m) => [m, ymLabel(m)])} /></${Field}>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 月結小幫手
export const openMonthClose = (ym = null) => openModal((close) => html`<${MonthClose} ym0=${ym} close=${close} />`);
function MonthClose({ ym0, close }) {
  const [ym, setYm] = useState(ym0);
  const [s, setS] = useState(null);
  const [done, setDone] = useState(false);
  const load = (m = ym) => api("month_close", m).then((x) => { setS(x); if (!m) setYm(x.ym); }).catch((e) => errorBox(e.message));
  useEffect(() => { load(ym); }, [ym]);
  if (!s) return html`<${Dialog} title="月結小幫手" icon="calendar" width="50rem" onClose=${() => close()}><div class="muted">讀取中…</div></${Dialog}>`;
  const mark = async (key, on = true) => { await api("month_close_check", s.ym, key, on); load(s.ym); };
  const after = async (p) => { await p; changed(); load(s.ym); };
  async function finish() {
    const left = s.steps.filter((x) => !x.ok).map((x) => x.title);
    if (left.length && !(await ask(`還有 ${left.length} 個步驟沒有完成：\n${left.join("\n")}\n\n仍要完成 ${s.label}的月結嗎？`, { yes: "仍要完成" }))) return;
    await api("month_close_finish", s.ym); changed(); setDone(true);
  }
  const actions = {
    recurring: (st) => !st.ok && html`<${Btn} kind="primary" onClick=${() => after(openDue())}>確認入帳</${Btn}>`,
    reconcile: (st) => html`<div class="mc-accts">${(st.accounts || []).map((a) => html`<button class=${"pillbtn" + (a.ok ? " on" : "")}
        title=${a.last ? `上次對帳單日期 ${ymd(a.last)}` : "還沒有對過帳"} onClick=${() => after(openReconcile(a.id))}>
        ${a.ok ? "✓ " : ""}${a.name}</button>`)}</div>`,
    valuation: (st) => !st.ok && html`<${Btn} onClick=${() => after(openPrices())}>市價評價</${Btn}>`,
    budget: (st) => html`${(st.budgets || []).length > 0 && html`<div class="mc-budget">${st.budgets.map((b) => {
        const k = b.used / b.budget;
        return html`<div class=${k > 1 ? "over" : ""}><span>${b.name}</span><i><b style=${`width:${Math.min(100, k * 100)}%`}></b></i>
          <span class="num">${Math.round(k * 100)}%</span></div>`; })}</div>`}`,
    health: () => html`<${Btn} onClick=${async () => { if (await openHealth()) mark("health"); }}>開始檢查</${Btn}>`,
    report: () => html`<${Btn} icon="print" onClick=${async () => { if (await previewMonthly(s.ym)) mark("report"); }}>預覽月報</${Btn}>`,
  };
  const pctDone = Math.round((s.done / s.total) * 100);
  if (done) {
    return html`<${Dialog} title="月結小幫手" icon="calendar" width="50rem" onClose=${() => close(true)}
        footer=${html`<${Btn} icon="print" onClick=${() => previewMonthly(s.ym)}>預覽月報</${Btn}><div class="grow"></div>
          <${Btn} kind="primary" onClick=${() => close(true)}>完成</${Btn}>`}>
      <div class="mc-done"><div class="ok"><${Icon} name="check" size="2.6rem" /></div>
        <h2>${s.label}的帳已經收好了！</h2><p class="muted">辛苦了。下個月初會再提醒您，一樣一步一步完成。</p></div>
    </${Dialog}>`;
  }
  return html`<${Dialog} title="月結小幫手" icon="calendar" width="54rem" cls="listdlg" onClose=${() => close()}
      footer=${html`<${Btn} onClick=${() => close()}>稍後再說</${Btn}><div class="grow"></div>
        <${Btn} kind="primary" icon="check" onClick=${finish}>完成 ${s.label}月結</${Btn}>`}>
    <div class="mc-head">
      <div class="mc-ring" style=${`--p:${pctDone}`}><b>${s.done}<small>/${s.total}</small></b></div>
      <div class="grow"><h2>${s.label}的月結</h2>
        <p class="muted">${s.finished ? `已於 ${s.finished.replace(/-/g, "/")} 完成。` : "一步一步把上個月的帳收好；能自動確認的步驟會自己打勾。"}</p></div>
      <${Select} value=${s.ym} onChange=${setYm} options=${s.months.map((m) => [m, ymLabel(m)])} />
    </div>
    <div class="tablewrap mc-steps">${s.steps.map((st, i) => html`<div class=${"mstep" + (st.ok ? " ok" : "")}>
      <span class="mnum">${st.ok ? html`<${Icon} name="check" />` : i + 1}</span>
      <div class="mtxt"><b>${st.title}${st.auto ? html`<span class="auto">自動確認</span>` : null}</b>
        <small>${st.key !== "budget" && st.manual ? "已完成" : st.detail}</small>
        ${actions[st.key](st)}</div>
      ${!st.auto && html`<button class="link mtoggle" onClick=${() => mark(st.key, !st.manual)}>${st.manual ? "取消完成" : st.key === "budget" ? "已檢視" : "標記完成"}</button>`}
    </div>`)}</div>
  </${Dialog}>`;
}
