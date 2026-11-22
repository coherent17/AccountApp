// 帳戶管理：資產與負債科目、合計、封存、刪除；按兩下編輯，右鍵有更多功能。
import { useState } from "preact/hooks";
import { META, api, changed, css, html, money, num, pct, toast, useLoad, ymd } from "../lib/core.js";
import { Kpi } from "../lib/charts.js";
import { Btn, Card, Check, DataTable, MenuButton, PageHead, ask, errorBox, openMenu, Skeleton } from "../lib/ui.js";
import { openAccount, openAdjust } from "../dialogs/account.js";
import { showTransactions } from "./transactions.js";
import { openReconcile } from "../dialogs/more.js";
import { openRates } from "../dialogs/invest.js";
import { openChart } from "../dialogs/chart.js";

export function Accounts({ go }) {
  const [archived, setArchived] = useState(false);
  const [sel, setSel] = useState(new Set());
  const [d] = useLoad(() => api("accounts_page", archived), [archived]);
  if (!d) return html`<${Skeleton} />`;
  const all = [...d.groups.asset, ...d.groups.liability];
  const current = all.find((a) => sel.has(a.id));

  async function toggleArchive(a) {
    if (!a.archived && Math.abs(a.balance) > 0.004 && !(await ask(
      `「${a.name}」目前仍有餘額 ${money(a.balance, a.currency)}，封存後仍會計入資產負債，但不會出現在記帳選單中。確定要封存嗎？`, { yes: "封存" }))) return;
    await api("account_archive", a.id, !a.archived);
    changed();
    toast(a.archived ? `已取消封存「${a.name}」` : `已封存「${a.name}」`);
  }
  async function del(a) {
    if (!(await ask(`確定要刪除帳戶「${a.name}」嗎？`, { yes: "刪除", danger: true }))) return;
    try { await api("account_delete", a.id); changed(); toast(`已刪除帳戶「${a.name}」`); } catch (e) { errorBox(e.message, "無法刪除"); }
  }
  const ledger = (a) => { window.__pendingReport = { tab: "ledger", account: a.id }; go("reports"); };
  const menu = (e, a) => openMenu(e, [
    { label: "編輯帳戶", icon: "edit", run: () => openAccount(a.id) },
    !a.invest && { label: "更新餘額／市值", icon: "refresh", run: () => openAdjust(a.id) },
    { label: "查看這個帳戶的收支明細", icon: "eye", run: () => showTransactions(go, { account: a.id, period: "全部" }) },
    { label: "查看分類帳（借貸與累計餘額）", icon: "list", run: () => ledger(a) },
    { label: "銀行對帳…", icon: "check", run: () => openReconcile(a.id) },
    "-",
    { label: a.archived ? "取消封存" : "封存", icon: "archive", run: () => toggleArchive(a) },
    { label: "刪除", icon: "trash", danger: true, run: () => del(a) },
  ]);

  const cols = (kind) => [
    { key: "code", title: "代號", align: "c", render: (a) => html`<span class="muted num">${a.code}</span>`, sort: (a) => a.code },
    { key: "name", title: "帳戶名稱", render: (a) => html`<b>${a.name}</b>${a.archived && html`<span class="muted">（已封存）</span>`}`, sort: (a) => a.name, nowrap: true },
    { key: "category", title: "類別", render: (a) => a.category, sort: (a) => a.category, nowrap: true },
    { key: "current", title: "流動性", align: "c", nowrap: true, render: (a) => html`<span class="muted">${a.current ? "流動" : "非流動"}</span>`, sort: (a) => a.current },
    { key: "currency", title: "幣別", align: "c", render: (a) => a.currency },
    { key: "balance", title: kind === "asset" ? "餘額（原幣）" : "欠款（原幣）", align: "r", nowrap: true, sort: (a) => a.balance,
      render: (a) => html`<span class=${"num " + (a.balance < 0 ? "c-expense" : "")}>${num(a.balance, a.currency)}</span>` },
    { key: "rate", title: "匯率", align: "r", render: (a) => (a.rate === 1 ? "" : html`<span class="num">${a.rate.toFixed(4)}</span>`) },
    { key: "value", title: `折合${META.base}`, align: "r", nowrap: true, sort: (a) => a.value,
      render: (a) => html`<b class=${"num " + (a.value < 0 ? "c-expense" : "")}>${num(a.value)}</b>` },
    { key: "share", title: "占比", align: "r", sort: (a) => a.share,
      render: (a) => html`<div class="share"><span class="num">${pct(a.share)}</span><i style=${`width:${Math.max(0, Math.min(100, a.share * 100))}%`}></i></div>` },
    { key: "maturity", title: "到期日", align: "c", nowrap: true, sort: (a) => a.maturity,
      render: (a) => html`<span class=${a.maturity_soon ? "c-expense" : "muted"}>${ymd(a.maturity)}</span>` },
    { key: "note", title: "備註", elide: true, cls: () => "grow muted",
      tip: (a) => a.note + (a.interest ? `（年利率 ${a.interest}%）` : ""),
      render: (a) => a.note + (a.interest ? `（年利率 ${a.interest}%）` : "") },
  ];

  const table = (kind, title, total) => html`<${Card} cls="flush" title=${title} icon=${kind === "asset" ? "bank" : "card"}
      extra=${html`<span class="muted">合計 <b class="num">${money(total)}</b>　｜　${d.groups[kind].length} 個帳戶</span>`}>
    <${DataTable} columns=${cols(kind)} rows=${d.groups[kind]} selected=${sel} onSelect=${setSel} defaultSort=${["code", false]}
      onActivate=${(a) => openAccount(a.id)} onMenu=${menu} rowCls=${(a) => (a.archived ? "void-soft" : "")} sticky=${false}
      empty=${kind === "asset" ? "還沒有資產帳戶，按右上角「新增帳戶」開始" : "沒有負債帳戶（信用卡、貸款）"} />
  </${Card}>`;

  return html`
    <${PageHead} title="帳戶管理" sub="資產與負債科目：銀行、現金、投資、信用卡、貸款等">
      <${Btn} icon="list" big onClick=${openChart} title="檢視全部會計科目、新增科目（含自訂代號）">會計科目表</${Btn}>
      <${MenuButton} label="更多功能" items=${[{ label: "銀行對帳（與存摺逐筆核對）", icon: "check", run: () => openReconcile(current ? current.id : null) },
                                            { label: "更新匯率", icon: "refresh", run: openRates }]} />
      <${Btn} kind="adjust" icon="refresh" big onClick=${() => openAdjust(current && !current.invest ? current.id : null)}>更新餘額／市值</${Btn}>
      <${Btn} kind="primary" icon="plus" big onClick=${() => openAccount()}>新增帳戶</${Btn}>
    </${PageHead}>
    <div class="grid kpis">
      <${Kpi} hero title="淨資產（業主權益）" icon="scale" value=${d.net} sub=${html`<span>資產總計 − 負債總計</span>`} />
      <${Kpi} title="資產總計" icon="bank" color=${css("--income")} value=${d.assets} delay=${60} sub=${`${d.groups.asset.length} 個資產帳戶`} />
      <${Kpi} title="負債總計" icon="card" color=${css("--expense")} value=${d.liabilities} delay=${120} sub=${`${d.groups.liability.length} 個負債帳戶`} />
    </div>
    ${table("asset", "資產", d.assets)}
    ${table("liability", "負債", d.liabilities)}
    <div class="row wrap">
      <${Check} checked=${archived} onChange=${setArchived}>顯示已封存的帳戶</${Check}>
      <div class="grow"></div>
      <${Btn} icon="list" disabled=${!current} onClick=${() => ledger(current)}>查看分類帳</${Btn}>
      <${Btn} icon="edit" disabled=${!current} onClick=${() => openAccount(current.id)}>編輯</${Btn}>
      <${Btn} icon="archive" disabled=${!current} onClick=${() => toggleArchive(current)}>${current && current.archived ? "取消封存" : "封存"}</${Btn}>
      <${Btn} kind="danger" icon="trash" disabled=${!current} onClick=${() => del(current)}>刪除</${Btn}>
    </div>
    <div class="hint">說明：資產帳戶的收入會增加餘額、支出會減少餘額；信用卡等負債帳戶刷卡（支出）會增加欠款，從銀行轉帳繳款會減少欠款。按兩下帳戶可修改，按右鍵有更多功能。</div>`;
}
