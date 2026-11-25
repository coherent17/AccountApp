// 月結小幫手、到期提醒中心、資料健康檢查、月報。帳務判斷都在 Python（core/monthclose、reminders、health）。
import { useEffect, useState } from "preact/hooks";
import { META, api, changed, css, html, isoToday, money, toast, ymd } from "../lib/core.js";
import { PALETTE, axis, chartBase, shortMoney, useChart, valueAxis } from "../lib/charts.js";
import { AmountInput, Btn, Check, DateInput, Dialog, Field, Icon, Segmented, Select, TextInput, ask, errorBox, openModal } from "../lib/ui.js";
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
    if (await openModal((c) => html`<${ReminderEdit} item=${item} kinds=${d.kinds} freqs=${d.freqs} accounts=${d.accounts} close=${c} />`)) { changed(); load(); }
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

function ReminderEdit({ item, kinds, freqs, accounts, close }) {
  const [title, setTitle] = useState(item ? item.title : "");
  const [kind, setKind] = useState(item ? item.kind : "insurance");
  const [freq, setFreq] = useState(item ? item.freq : "yearly");
  const [date, setDate] = useState(item ? item.date : isoToday());
  const [amount, setAmount] = useState(item ? item.amount : null);
  const [lead, setLead] = useState(item ? item.lead : 7);
  const [note, setNote] = useState(item ? item.note : "");
  const [account, setAccount] = useState(item ? item.account_id : null);
  const [msg, setMsg] = useState("");
  async function save() {
    try { await api("reminder_save", { id: item && item.id, title, kind, freq, date, amount, lead, note, account_id: account }); toast(`已儲存提醒：${title}`); close(true); }
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
      <${Field} label=${kind === "dividend" ? "入帳帳戶" : "付款帳戶"} hint="選了帳戶（並填金額），這筆會納入「現金流預測」；若已設成定期交易就不必再選，以免重複計算。">
        <${Select} value=${account} onChange=${setAccount} options=${[[null, "（不指定）"], ...accounts.map((a) => [a.id, a.name])]} /></${Field}>
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

// ------------------------------------------------------------------ 現金流預測
export const openForecast = () => openModal((close) => html`<${Forecast} close=${close} />`);
function Forecast({ close }) {
  const [months, setMonths] = useState(6);
  const [d, setD] = useState(null);
  const [low, setLow] = useState(null);
  const [only, setOnly] = useState(null);
  const load = () => api("cash_forecast", months).then((x) => { setD(x); setLow(x.low); }).catch((e) => errorBox(e.message));
  useEffect(() => { load(); }, [months]);
  const shown = d ? d.accounts.filter((a) => a.events > 0 || a.warn) : [];
  const lines = shown.filter((a) => a.kind === "asset" && (!only || a.id === only));
  const chart = useChart(() => {
    if (!d) return {};
    const pal = PALETTE();
    return { ...chartBase(),
      legend: { top: 0, type: "scroll", textStyle: { color: css("--text-2") } },
      grid: { left: 8, right: 16, top: 34, bottom: 4, containLabel: true },
      xAxis: { ...axis(d.weeks.map((w) => `${+w.slice(5, 7)}/${+w.slice(8)}`)), boundaryGap: false },
      yAxis: { ...valueAxis(), axisLabel: { formatter: shortMoney, color: css("--text-3") } },
      tooltip: { ...chartBase().tooltip, valueFormatter: (v) => money(v) },
      series: lines.map((a, i) => ({ name: a.name, type: "line", step: "end", data: a.series, symbol: "none",
        lineStyle: { width: 2.5, color: pal[i % pal.length] }, itemStyle: { color: pal[i % pal.length] },
        markLine: i === 0 ? { symbol: "none", silent: true, label: { position: "insideEndTop", formatter: `低水位 ${shortMoney(d.low)}`, color: css("--expense") },
          lineStyle: { color: css("--expense"), type: "dashed" }, data: [{ yAxis: d.low }] } : undefined })) };
  }, [d, only]);
  async function saveLow() {
    try { await api("set_forecast_low", low); toast("已更新低水位"); load(); changed(); } catch (e) { errorBox(e.message); }
  }
  const evs = d ? d.events.filter((e) => !only || e.account_id === only) : [];
  return html`<${Dialog} title="現金流預測" icon="trend_up" width="74rem" cls="listdlg forecast" onClose=${() => close()}
      footer=${html`<span class="hint">依定期交易與指定了帳戶的提醒推算；定存到期、臨時支出不會自動計入。</span><div class="grow"></div>
        <${Btn} icon="bell" onClick=${async () => { await openReminders(); load(); }}>管理提醒</${Btn}><${Btn} kind="primary" onClick=${() => close()}>關閉</${Btn}>`}>
    <div class="row wrap fc-bar">
      <${Segmented} value=${months} onChange=${setMonths} options=${[[3, "3 個月"], [6, "6 個月"], [12, "12 個月"]]} />
      <div class="grow"></div><span class="lbl">低水位</span>
      <div style="width:10rem"><${AmountInput} value=${low} onChange=${setLow} /></div>
      <${Btn} onClick=${saveLow} disabled=${!d || low === d.low}>儲存</${Btn}>
    </div>
    ${!d ? html`<div class="muted">計算中…</div>` : html`<div class=${"fc-top" + (lines.length ? "" : " solo")}>
      <div class="fc-cards">${shown.map((a) => html`<button class=${"fc-card" + (a.warn ? " warn" : "") + (only === a.id ? " on" : "")}
          onClick=${() => setOnly(only === a.id ? null : a.id)} title="按一下只看這個帳戶">
        <b>${a.name}</b>
        <span>目前 <i class="num">${money(a.start, a.currency)}</i></span>
        <span>${a.kind === "asset" ? "最低" : "最高欠款"} <i class=${"num" + (a.warn ? " c-expense" : "")}>${money(a.kind === "asset" ? a.min : Math.max(a.start, ...a.series), a.currency)}</i>
          ${a.kind === "asset" ? html`<small>（${ymd(a.min_date)}）</small>` : ""}</span>
        <span>${ymd(d.end)} <i class="num">${money(a.end, a.currency)}</i></span>
        ${a.warn && html`<em><${Icon} name="alert" />${a.negative ? "會變成負數" : "低於低水位"}${a.reason ? `（${a.reason}）` : ""}</em>`}
      </button>`)}
        ${!shown.length && html`<div class="empty-mini">接下來沒有預定的收支。設定「定期交易」或在提醒裡指定付款帳戶後，這裡就會推算餘額。</div>`}</div>
      ${lines.length > 0 && html`<div class="chart fc-chart" ref=${chart}></div>`}</div>
      <div class="tablewrap"><table class="list sticky"><thead><tr><th>日期</th><th>事項</th><th>帳戶</th><th class="r">金額</th><th class="r">之後餘額</th></tr></thead>
        <tbody>${evs.map((e) => html`<tr><td class="num">${ymd(e.date)}${e.overdue ? html` <span class="type b-adjust">已到期</span>` : ""}</td><td>${e.title}</td><td>${e.account}</td>
          <td class=${"r num " + (e.inflow ? "c-income" : "c-expense")}>${money(e.amount, e.currency, true)}</td>
          <td class=${"r num" + (shown.find((a) => a.id === e.account_id && a.kind === "asset" && e.balance < d.low) ? " c-expense b" : "")}>${money(e.balance, e.currency)}</td></tr>`)}
          ${d.maturities.map((m) => html`<tr class="muted"><td class="num">${ymd(m.date)}</td><td>${m.title}（續存或轉入由您決定，未計入）</td><td></td>
            <td class="r num">${money(m.amount, m.currency)}</td><td></td></tr>`)}</tbody></table></div>`}
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 意見回饋
// 可以累積好幾則（每則附上當時的畫面），最後產生一份 PDF：存在「意見回饋」資料夾並複製起來，在 LINE 按 Ctrl+V 貼上傳送。
// 不會自動上傳任何資料。
const FB_TAGS = ["看不清楚", "操作不順", "數字不對", "希望新增功能", "其他"];
let fbCount = 0;
const fbSubs = new Set();
const setFbCount = (n) => { fbCount = n; fbSubs.forEach((f) => f(n)); };
/** 側邊欄 ♡ 上的數字：還沒做成 PDF 的回饋則數。 */
export function useFeedbackCount() {
  const [n, setN] = useState(fbCount);
  useEffect(() => { fbSubs.add(setN); api("feedback_items").then((x) => setFbCount(x.length)).catch(() => {}); return () => fbSubs.delete(setN); }, []);
  return n;
}
export async function openFeedback() {
  const shot = await api("feedback_capture").catch(() => "");        // 先拍下目前的畫面（不含回饋視窗）
  const items = await api("feedback_items").catch(() => []);
  return openModal((close) => html`<${Feedback} shot=${shot} items0=${items} close=${close} />`);
}

// ---- 用畫布畫出 PDF 的每一頁（A4，150 dpi）
const PW = 1240, PH = 1754, PAD = 70, FONT = "'Microsoft JhengHei UI', 'Microsoft JhengHei', sans-serif";
function page() {
  const c = document.createElement("canvas"); c.width = PW; c.height = PH;
  const g = c.getContext("2d"); g.fillStyle = "#FFFFFF"; g.fillRect(0, 0, PW, PH); g.textBaseline = "top";
  return [c, g];
}
function wrap(g, text, width) {
  const out = [];
  for (const para of String(text).split("\n")) {
    let line = "";
    for (const ch of para) { if (g.measureText(line + ch).width > width && line) { out.push(line); line = ch; } else line += ch; }
    out.push(line);
  }
  return out;
}
function para(g, text, y, { size = 30, color = "#0F172A", bold = false, lh = 1.55, maxLines = 99, mono = false } = {}) {
  g.font = `${bold ? "bold " : ""}${size}px ${mono ? "Consolas, monospace" : FONT}`; g.fillStyle = color;
  const lines = wrap(g, text, PW - PAD * 2);
  lines.slice(0, maxLines).forEach((l, i) => g.fillText(l, PAD, y + i * size * lh));
  return y + Math.min(lines.length, maxLines) * size * lh;
}
function head(g, title, sub) {
  g.fillStyle = "#4F46E5"; g.fillRect(0, 0, 14, 190);
  let y = para(g, title, PAD, { size: 46, bold: true, lh: 1.3 });
  y = para(g, sub, y + 10, { size: 24, color: "#64748B" });
  g.fillStyle = "#E2E8F0"; g.fillRect(PAD, y + 20, PW - PAD * 2, 2);
  return y + 50;
}
const loadImg = (src) => new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = bad; i.src = src; });
const jpeg = (c) => c.toDataURL("image/jpeg", 0.88);
async function buildPages(items, diag) {
  const now = new Date().toLocaleString("zh-TW", { hour12: false });
  const pages = [];
  let [c, g] = page();                                              // 封面：摘要
  let y = head(g, "我的理財帳本　意見回饋", `${META.owner || ""}　${now}　版本 ${diag.version}　共 ${items.length} 則`);
  items.forEach((it, i) => {
    y = para(g, `${i + 1}.　${it.tag ? "【" + it.tag + "】" : ""}${it.page ? "（" + it.page + "）" : ""}`, y, { size: 30, bold: true, lh: 1.4 });
    y = para(g, it.note || "（沒有文字說明）", y + 4, { size: 28, color: "#334155", maxLines: 3 }) + 24;
  });
  para(g, "每一則的詳細說明與當時的畫面在後面幾頁；最後一頁是診斷資訊。", PH - PAD - 40, { size: 22, color: "#94A3B8" });
  pages.push(jpeg(c));
  for (const [i, it] of items.entries()) {                          // 每一則一頁：說明＋畫面
    [c, g] = page();
    y = head(g, `第 ${i + 1} 則${it.tag ? "　【" + it.tag + "】" : ""}`, `${it.at}　${it.page ? "畫面：" + it.page : ""}`);
    y = para(g, it.note || "（沒有文字說明）", y, { size: 32, maxLines: 14 }) + 30;
    if (it.shot) {
      const img = await loadImg(it.shot);
      const w = PW - PAD * 2, s = Math.min(w / img.width, (PH - PAD - y) / img.height);
      g.drawImage(img, PAD, y, img.width * s, img.height * s);
      g.strokeStyle = "#CBD5E1"; g.lineWidth = 2; g.strokeRect(PAD, y, img.width * s, img.height * s);
    }
    pages.push(jpeg(c));
  }
  [c, g] = page();                                                  // 最後一頁：診斷資訊
  y = head(g, "診斷資訊", "給協助修改程式的人看：版本、電腦環境、資料筆數與最近的錯誤紀錄（不含金額）");
  const env = [["程式版本", diag.version], ["資料結構", `v${diag.schema}`], ["Windows", diag.windows],
    ["螢幕", `${diag.screen ? diag.screen.join("×") : "—"}，Windows 縮放 ${diag.dpi_scale || "—"}%，文字大小 ${diag.text_scale || "—"}%`],
    ["可用範圍", `${innerWidth}×${innerHeight}（合計放大 ${Math.round(devicePixelRatio * 100)}%，頁面縮放 ${Math.round(outerWidth / innerWidth * 100)}%）`],
    ["字體／外觀", `${{ normal: "標準", large: "大", xlarge: "特大" }[document.documentElement.dataset.scale] || "—"}／${document.documentElement.dataset.theme === "dark" ? "深色" : "淺色"}`],
    ["瀏覽元件", (navigator.userAgent.match(/Edg\/[\d.]+/) || ["—"])[0]],
    ["畫面擷取", `${diag.capture}（附畫面 ${items.filter((x) => x.shot).length}/${items.length} 則）`],
    ["資料筆數", `帳戶 ${diag.accounts}、傳票 ${diag.vouchers}、投資標的 ${diag.securities}、定期交易 ${diag.recurring}`],
    ["已結帳至", diag.closed_until || "（未結帳）"]];
  for (const [k, v] of env) { para(g, k, y, { size: 26, color: "#64748B" }); y = para(g, "　　　　　　" + v, y, { size: 26 }) + 4; }
  y = para(g, "最近的錯誤紀錄", y + 24, { size: 28, bold: true });
  para(g, diag.error_log ? diag.error_log.split("\n").slice(-40).join("\n") : "（沒有錯誤紀錄）", y + 8,
       { size: 18, color: "#334155", mono: true, lh: 1.45, maxLines: Math.floor((PH - PAD - y - 8) / 26) });
  pages.push(jpeg(c));
  return pages;
}

function Feedback({ shot: shot0, items0, close }) {
  const [shot, setShot] = useState(shot0);
  const [pasted, setPasted] = useState(false);
  const [items, setItems] = useState(items0);
  const [note, setNote] = useState("");
  const [tag, setTag] = useState("");
  const [withShot, setWithShot] = useState(!!shot);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [res, setRes] = useState(null);
  const pageName = window.__pageName || "";
  const dirty = note.trim() || tag || (pasted && withShot);      // 只貼上照片、沒寫字也可以
  async function addItem() {
    const list = await api("feedback_add", { tag, note, page: pageName, shot: withShot ? shot : "" });
    setItems(list); setFbCount(list.length); setNote(""); setTag(""); setWithShot(false); setPasted(false);
    return list;
  }
  async function add() {
    try { const l = await addItem(); setMsg(`已加入，清單共 ${l.length} 則。可以繼續使用程式，有其他問題再按 ♡ 加入；準備好了就按「產生 PDF」。`); }
    catch (e) { errorBox(e.message); }
  }
  async function makePdf() {
    setBusy(true);
    try {
      const list = dirty ? await addItem() : items;
      if (!list.length) { setBusy(false); return errorBox("請先寫下至少一則回饋。"); }
      const diag = await api("feedback_diag");
      const r = await api("feedback_pdf", await buildPages(list, diag), true);
      setFbCount(0); setRes({ ...r, n: list.length });
    } catch (e) { errorBox(e.message); } finally { setBusy(false); }
  }
  async function remove(id) { const l = await api("feedback_remove", id); setItems(l); setFbCount(l.length); }
  // 在說明欄按 Ctrl+V 貼上圖片（例如手機拍的照片、其他截圖），就用這張圖代替目前的畫面
  function onPaste(e) {
    const file = [...(e.clipboardData?.items || [])].find((x) => x.type.startsWith("image/"))?.getAsFile();
    if (!file) return;
    e.preventDefault();
    const r = new FileReader();
    r.onload = () => { setShot(r.result); setWithShot(true); setPasted(true); };
    r.readAsDataURL(file);
  }
  async function copyAgain() {
    const ok = await api("feedback_copy", res.path).catch(() => false);
    toast(ok ? "已再複製一次，可以到 LINE 按 Ctrl+V 貼上" : "無法複製，請從資料夾把 PDF 拖進 LINE", ok ? "ok" : "info");
  }
  if (res) {
    return html`<${Dialog} title="意見回饋" icon="heart" width="44rem" onClose=${() => close(true)}
        footer=${html`<${Btn} icon="copy" onClick=${copyAgain}>再複製一次</${Btn}><${Btn} icon="folder" onClick=${() => api("open_path", res.folder)}>開啟資料夾</${Btn}>
          <${Btn} icon="eye" onClick=${() => api("open_path", res.path)}>看看 PDF</${Btn}><div class="grow"></div>
          <${Btn} kind="primary" onClick=${() => close(true)}>完成</${Btn}>`}>
      <div class="mc-done"><div class="ok"><${Icon} name="check" size="2.4rem" /></div>
        <h2>已產生 PDF（${res.n} 則）${res.copied ? "並複製好了" : ""}！</h2>
        ${res.copied ? html`<p>打開 LINE 和我們的對話，在輸入框按 <kbd>Ctrl</kbd>＋<kbd>V</kbd>，就會附上這個 PDF，再按傳送。</p>
            <p class="muted">如果貼不上，按「開啟資料夾」，把 PDF 檔拖進 LINE 的對話框也可以。</p>`
          : html`<p>請按「開啟資料夾」，把 PDF 檔拖進 LINE 的對話框傳給我們。</p>`}
        <p class="muted small">${res.path}</p></div>
    </${Dialog}>`;
  }
  return html`<${Dialog} title="意見回饋" icon="heart" width="62rem" onClose=${() => close()}
      footer=${html`<span class="hint">不會自動上傳；產生的 PDF 存在「意見回饋」資料夾，由您傳給我們。</span><div class="grow"></div>
        <${Btn} onClick=${() => close()}>關閉</${Btn}>
        <${Btn} icon="plus" disabled=${!dirty || busy} onClick=${add}>加入清單</${Btn}>
        <${Btn} kind="primary" icon="print" disabled=${busy || (!dirty && !items.length)} onClick=${makePdf}>${busy ? "產生中…" : `產生 PDF${items.length + (dirty ? 1 : 0) ? `（${items.length + (dirty ? 1 : 0)} 則）` : ""}`}</${Btn}>`}>
    <div class="fb-grid">
      <div class="fb-new">
        <p class="muted" style="margin-top:0">有看不清楚、不好用、數字怪怪的，或希望新增的功能，都歡迎告訴我們。${pageName ? `（目前畫面：${pageName}）` : ""}</p>
        <div class="row wrap" style="margin-bottom:.6rem">${FB_TAGS.map((t) => html`<button type="button" class=${"pillbtn" + (tag === t ? " on" : "")} onClick=${() => setTag(tag === t ? "" : t)}>${t}</button>`)}</div>
        <textarea class="fb-text" rows="5" value=${note} onInput=${(e) => setNote(e.target.value)} onPaste=${onPaste}
          placeholder="例如：收支明細的字可以再大一點；月結的第 2 步不知道要按哪裡…（也可以按 Ctrl+V 貼上手機照片或其他截圖）" autofocus></textarea>
        ${shot && html`<div class="fb-shot"><${Check} checked=${withShot} onChange=${setWithShot}>${pasted ? "附上剛才貼上的圖片" : "附上剛才的畫面（只拍這個程式，不會拍到其他視窗）"}</${Check}>
          ${withShot && html`<img src=${shot} alt="目前的畫面" />`}</div>`}
        ${msg && html`<div class="msg ok"><${Icon} name="check" />${msg}</div>`}
      </div>
      <div class="fb-list">
        <div class="fb-list-h">待傳送的回饋（${items.length}）</div>
        ${items.length === 0 ? html`<div class="empty-mini">還沒有。可以一次寫一則，按「加入清單」存起來，之後再一起產生 PDF。</div>`
          : items.map((it, i) => html`<div class="fb-item">${it.shot ? html`<img src=${it.shot} alt="" />` : html`<span class="noshot"><${Icon} name="edit" /></span>`}
            <div class="grow"><b>${i + 1}. ${it.tag ? `【${it.tag}】` : ""}${it.page ? html`<small>${it.page}</small>` : ""}</b><span>${it.note}</span><small>${it.at}</small></div>
            <button class="x" title="刪除這則" onClick=${() => remove(it.id)}><${Icon} name="close" /></button></div>`)}
      </div>
    </div>
  </${Dialog}>`;
}
