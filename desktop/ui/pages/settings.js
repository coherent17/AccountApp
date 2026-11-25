// 設定：個人設定與外觀、收支分類與預算、結帳、網路與版本更新、資料管理與備份、關於。
import { useState } from "preact/hooks";
import { META, api, changed, html, money, toast, useLoad, ymd } from "../lib/core.js";
import { AmountInput, Btn, Card, Check, DataTable, DateInput, Dialog, Field, Icon, PageHead, Segmented, Select, TextInput, ask,
         errorBox, info, openMenu, openModal, Skeleton } from "../lib/ui.js";
import { openChart, openSubject, openYearClose } from "../dialogs/chart.js";
import { checkUpdates } from "../dialogs/update.js";
import { openTour } from "../dialogs/tour.js";
import { openFeedback, openForecast, openHealth, openMonthClose, openReminders, openYearAssist } from "../dialogs/tools.js";

export const resolveTheme = (mode) => (mode === "dark" || (mode === "system" && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light");

export function Settings() {
  const [d, reload] = useLoad(() => api("settings_page"));
  if (!d) return html`<${Skeleton} />`;
  return html`
    <${PageHead} icon="settings" color="var(--transfer)" title="設定" sub="個人資料、收支分類與預算、結帳、備份與還原" />
    <${Personal} d=${d} reload=${reload} />
    <${Categories} d=${d} />
    <${Closing} d=${d} />
    <${Network} d=${d} />
    <${DataBackup} d=${d} reload=${reload} />
    <${Card} title="關於" icon="info">
      <p class="muted" style="margin:0;line-height:1.9">我的理財帳本　版本 ${META.version}<br />
        個人資產管理與記帳工具：日記帳、分類帳、資產負債表、收支損益表、試算表及 Excel 匯出。<br />所有資料僅儲存於本機電腦，不會上傳至網路。</p>
    </${Card}>`;
}

// ------------------------------------------------------------------ 個人設定
function Personal({ d, reload }) {
  const [name, setName] = useState(d.owner);
  const r = document.documentElement;
  const [, force] = useState(0);
  const set = async (k, v, msg) => { await api("set_pref_setting", k, v); if (msg) toast(msg); };
  const theme = (mode) => { set("theme_mode", mode, "已套用新的外觀"); window.__setPrefs(resolveTheme(mode), r.dataset.scale); d.theme = mode; force((x) => x + 1); };
  const scale = (s) => { set("font_scale", s); window.__setPrefs(r.dataset.theme, s); d.font_scale = s; force((x) => x + 1); };
  const anim = (on) => { set("animations", on, on ? "已開啟動畫效果" : "已關閉動畫效果"); r.classList.toggle("animate", on); d.animations = on; force((x) => x + 1); };
  async function base(code) {
    if (code === d.base) return;
    const label = d.currencies.find((c) => c[0] === code)[1];
    if (!(await ask(`確定要將本位幣改為「${label}」嗎？\n改變後請到「帳戶管理」確認各外幣帳戶的匯率是否正確。`))) return;
    await api("set_base_currency", code);
    META.base = code; changed(); reload();
    info("本位幣已變更。");
  }
  return html`<${Card} title="個人設定與外觀" icon="settings"><div class="form">
    <${Field} label="稱呼" hint="顯示在首頁問候與報表「編製者」欄"><div class="row"><${TextInput} cls="grow" value=${name} onInput=${setName} />
      <${Btn} kind="primary" onClick=${async () => { await set("owner_name", name, "已儲存稱呼"); META.owner = name.trim(); changed(); }}>儲存</${Btn}></div></${Field}>
    <${Field} label="文字大小"><${Segmented} value=${d.font_scale} onChange=${scale} options=${[["normal", "標準"], ["large", "大"], ["xlarge", "特大"]]} /></${Field}>
    <${Field} label="外觀" hint="深色模式在晚上或光線較暗時比較不刺眼，切換後立即生效。列印與 PDF 仍使用白底。">
      <${Segmented} value=${d.theme} onChange=${theme} options=${[["light", "淺色", "eye"], ["dark", "深色", "moon"], ["system", "跟隨 Windows 設定", "settings"]]} /></${Field}>
    <${Field} label="動畫效果" hint="若電腦較舊、覺得畫面不夠流暢，或偏好簡潔畫面，可以關閉。">
      <${Check} checked=${d.animations} onChange=${anim}>開啟動畫效果（畫面轉場、數字滾動、圖表動畫）</${Check}></${Field}>
    <${Field} label="新功能導覽"><div class="row"><${Btn} icon="eye" onClick=${openTour}>重新觀看導覽</${Btn}><span class="muted small">介紹記一筆、搜尋、復原與外觀設定</span></div></${Field}>
    <${Field} label="本位幣" hint="所有報表與資產合計皆以本位幣表示；外幣帳戶依帳戶中設定的匯率換算。">
      <${Select} value=${d.base} onChange=${base} options=${d.currencies} /></${Field}>
  </div></${Card}>`;
}

// ------------------------------------------------------------------ 收支分類
function Categories({ d }) {
  return html`<${Card} title="收支分類（會計科目）與每月預算" icon="layers" extra=${html`<${Btn} kind="primary" icon="list" onClick=${openChart}>會計科目表</${Btn}>`}>
    <p class="hint" style="margin-top:0">收入、費用科目在這裡管理；資產、負債科目請到「帳戶管理」。按兩下可修改，按右鍵有更多功能（預算、稅務歸類、排序、隱藏）。</p>
    <div class="grid two">${["expense", "income"].map((k) => html`<${CatTable} kind=${k} rows=${d.categories[k]} tags=${d.tax_tags[k]} />`)}</div>
  </${Card}>`;
}
function CatTable({ kind, rows, tags }) {
  const [sel, setSel] = useState(new Set());
  const cur = rows.find((r) => sel.has(r.id));
  const run = async (fn, msg) => { try { await fn(); changed(); if (msg) toast(msg); } catch (e) { errorBox(e.message); } };
  const budget = async (r) => {
    const v = await openModal((close) => html`<${BudgetDlg} r=${r} close=${close} />`);
    if (v != null) run(() => api("category_update", r.id, { budget: v }), `已設定「${r.name}」每月預算`);
  };
  const tax = async (r) => {
    const v = await openModal((close) => html`<${TaxDlg} r=${r} tags=${tags} close=${close} />`);
    if (v != null) run(() => api("category_update", r.id, { tax_tag: v }), "已更新稅務歸類");
  };
  const del = async (r) => { if (await ask(`確定要刪除分類「${r.name}」嗎？`, { yes: "刪除", danger: true })) run(() => api("category_delete", r.id), `已刪除「${r.name}」`); };
  const menu = (e, r) => openMenu(e, [
    { label: "修改", icon: "edit", run: () => openSubject(null, r.id) },
    kind === "expense" && { label: "設定每月預算…", icon: "wallet", run: () => budget(r) },
    { label: "稅務歸類…", icon: "list", run: () => tax(r) },
    "-", { label: "上移", icon: "up", run: () => run(() => api("category_move", r.id, -1)) },
    { label: "下移", icon: "down", run: () => run(() => api("category_move", r.id, 1)) },
    { label: r.archived ? "顯示（恢復使用）" : "隱藏（記帳時不再出現）", icon: "eye", run: () => run(() => api("category_update", r.id, { archived: !r.archived })) },
    "-", { label: "刪除", icon: "trash", danger: true, run: () => del(r) }]);
  const cols = [
    { key: "code", title: "代號", align: "c", render: (r) => html`<span class="muted num">${r.code}</span>` },
    { key: "name", title: "分類名稱", nowrap: true, cls: () => "grow", render: (r) => html`<b class=${r.archived ? "muted" : ""}>${r.name}</b>` },
    ...(kind === "expense" ? [{ key: "budget", title: "每月預算", align: "r", render: (r) => (r.budget ? html`<span class="num">${money(r.budget)}</span>` : html`<span class="muted">—</span>`) }] : []),
    { key: "tax", title: "稅務歸類", elide: true, render: (r) => (r.tax_label ? html`<span class="c-adjust">${r.tax_label}</span>` : html`<span class="muted">—</span>`), tip: (r) => r.tax_label },
    { key: "st", title: "狀態", align: "c", render: (r) => html`<span class=${"type " + (r.archived ? "b-void" : "b-income")}>${r.archived ? "已隱藏" : "使用中"}</span>` },
  ];
  return html`<div class="col">
    <div class="row"><b class=${kind === "expense" ? "c-expense" : "c-income"}>${kind === "expense" ? "支出分類" : "收入分類"}</b><div class="grow"></div>
      <${Btn} icon="plus" onClick=${() => openSubject(kind)}>新增</${Btn}>
      <${Btn} icon="edit" disabled=${!cur} onClick=${() => openSubject(null, cur.id)}>修改</${Btn}>
      <${Btn} icon="more" disabled=${!cur} onClick=${(e) => { const b = e.currentTarget.getBoundingClientRect(); menu({ preventDefault() {}, clientX: b.left, clientY: b.bottom + 6 }, cur); }}>更多</${Btn}></div>
    <div class="card flush inner"><${DataTable} columns=${cols} rows=${rows} selected=${sel} onSelect=${setSel} onActivate=${(r) => openSubject(null, r.id)}
      onMenu=${menu} sticky=${false} rowCls=${(r) => (r.archived ? "void-soft" : "")} /></div></div>`;
}
function BudgetDlg({ r, close }) {
  const [v, setV] = useState(r.budget || null);
  return html`<${Dialog} title="設定每月預算" icon="wallet" width="30rem" onClose=${() => close(null)}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}><${Btn} kind="primary" onClick=${() => close(v || 0)}>儲存</${Btn}>`}>
    <p>「${r.name}」每月預算（留空或 0 表示不設定）：</p>
    <form onSubmit=${(e) => { e.preventDefault(); close(v || 0); }}><${AmountInput} value=${v} onChange=${setV} big autofocus placeholder="不設定" /></form></${Dialog}>`;
}
function TaxDlg({ r, tags, close }) {
  const [v, setV] = useState(r.tax_tag || "");
  return html`<${Dialog} title="稅務歸類" icon="list" width="32rem" onClose=${() => close(null)}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}><${Btn} kind="primary" onClick=${() => close(v)}>儲存</${Btn}>`}>
    <p>「${r.name}」在報稅彙總中歸類為：</p><${Select} value=${v} onChange=${setV} options=${tags} /></${Dialog}>`;
}

// ------------------------------------------------------------------ 結帳
function Closing({ d }) {
  const [date, setDate] = useState(d.closed_until || new Date(new Date().getFullYear(), 0, 0).toISOString().slice(0, 10));
  const [year, setYear] = useState(d.close_years[0] ? d.close_years[0].year : null);
  async function close() {
    if (!(await ask(`確定要結帳至 ${ymd(date)} 嗎？\n此日期（含）以前的紀錄將被鎖定。`, { yes: "結帳" }))) return;
    if (date < d.closed_until && d.year_closings.length && !(await ask("結帳日往前移，之後年度的年度結帳分錄會一併作廢。確定嗎？", { danger: true }))) return;
    try { await api("set_closed", date); changed(); toast(`已結帳至 ${ymd(date)}`); } catch (e) { errorBox(e.message); }
  }
  async function reopen() {
    if (!d.closed_until) return info("目前尚未結帳。");
    if (!(await ask("確定要解除結帳嗎？解除後所有紀錄都可以修改，年度結帳分錄也會一併作廢。", { yes: "解除結帳", danger: true }))) return;
    await api("set_closed", ""); changed(); toast("已解除結帳");
  }
  return html`<${Card} title="結帳（關帳）" icon="lock">
    <p class="hint" style="margin-top:0">對帳完成後可執行結帳：結帳日（含）以前的紀錄將被鎖定，無法新增、修改或作廢，以確保已核對的帳務不會被誤改。年度結帳另會把該年度損益結轉「本期損益（累積淨值）」，並在日記簿留下結帳分錄。如需更正，可隨時解除結帳（年度結帳分錄會一併作廢）。</p>
    <div class="form">
      <${Field} label="目前狀態"><b class=${d.closed_until ? "c-adjust" : "muted"}>${d.closed_until ? `已結帳至 ${ymd(d.closed_until)}` : "尚未結帳"}${d.year_closings.length ? `　｜　已辦理年度結帳：${d.year_closings.join("、")} 年` : ""}</b></${Field}>
      <${Field} label="結帳至"><div class="row wrap"><${DateInput} value=${date} onChange=${setDate} /><${Btn} kind="primary" icon="lock" onClick=${close}>執行結帳</${Btn}>
        <${Btn} kind="danger" onClick=${reopen}>解除結帳</${Btn}></div></${Field}>
      <${Field} label="年度結帳">${year ? html`<div class="row wrap"><${Select} value=${year} onChange=${setYear}
          options=${d.close_years.map((y) => [y.year, `${y.year} 年（民國 ${y.year - 1911} 年）${y.done ? "　✓ 已結帳" : ""}`])} />
        <${Btn} icon="book" onClick=${() => openYearClose(year)}>年度結帳…</${Btn}></div>` : html`<span class="muted">目前沒有已結束、可辦理結帳的年度。</span>`}</${Field}>
    </div></${Card}>`;
}

// ------------------------------------------------------------------ 網路
function Network({ d }) {
  const [online, setOnline] = useState(d.online);
  const [auto, setAuto] = useState(d.update_auto);
  return html`<${Card} title="網路" icon="refresh"><div class="form">
    <${Field} label="網路更新" hint="開啟後，「市價評價」與「更新匯率」會多一個「從網路取得」按鈕。只會下載公開資料、不會上傳任何個人資料；股價來源為臺灣證券交易所與櫃買中心官方開放資料，匯率為 ExchangeRate-API 國際參考匯率。沒有網路時仍可手動輸入，所有功能都不受影響。">
      <${Check} checked=${online} onChange=${async (v) => { setOnline(v); await api("set_pref_setting", "online_updates", v); META.online = v; toast(v ? "已開啟網路更新（選用）" : "已關閉網路更新，程式不會連線"); }}>允許連線更新匯率與股價（選用，預設關閉）</${Check}></${Field}>
    <${Field} label="版本更新" hint=${`目前版本 ${META.version}。檢查時只會向 GitHub 查詢最新版本號碼；有新版本時會顯示更新內容，按「立即更新」就會自動下載、換成新版並重新開啟，帳本資料不會變動（更新前會先備份）。`}>
      <div class="row wrap"><${Check} checked=${auto} onChange=${async (v) => { setAuto(v); await api("set_pref_setting", "update_auto", v); toast(v ? "開啟程式時會自動檢查新版本" : "已關閉自動檢查新版本"); }}>開啟程式時自動檢查是否有新版本（一天最多一次）</${Check}>
        <div class="grow"></div><${Btn} icon="refresh" onClick=${() => checkUpdates(false)}>立即檢查新版本</${Btn}></div></${Field}>
  </div></${Card}>`;
}

// ------------------------------------------------------------------ 資料與備份
function DataBackup({ d, reload }) {
  const e = d.extra;
  const open = (p) => api("open_path", p).catch((x) => errorBox(x.message));
  async function backupNow() {
    const p = await api("pick_backup_save");
    if (!p) return;
    try { await api("backup_to", p); info(`備份完成！\n${p}\n\n建議將備份檔另外存到隨身碟或雲端硬碟。`); } catch (x) { errorBox(`備份失敗：${x.message}`); }
  }
  async function restore() {
    const p = await api("pick_restore");
    if (!p) return;
    if (!(await ask("還原後，目前帳本內容會被備份檔取代。\n（系統會先自動保存目前的帳本，以防萬一）\n確定要還原嗎？", { yes: "還原", danger: true }))) return;
    try { await api("restore_from", p); changed(); reload(); info("還原完成！"); } catch (x) { errorBox(`還原失敗：${x.message}`); }
  }
  async function reset() {
    if (!(await ask("這會刪除所有帳戶與收支紀錄（分類會恢復為預設值）。\n建議先執行「立即備份」。確定要繼續嗎？", { yes: "繼續", danger: true }))) return;
    const w = await openModal((close) => html`<${ConfirmWord} close=${close} />`);
    if (w == null) return;
    try { await api("reset_all", w); changed(); reload(); info("已清除所有資料（清除前的資料已自動備份到「自動備份」資料夾）。"); } catch (x) { info(x.message); }
  }
  async function setExtra(folder) {
    try {
      let r = await api("extra_set", folder, false);
      if (r.need_confirm) {
        if (!(await ask("這個資料夾跟帳本在同一顆硬碟上，硬碟故障時兩份會一起損壞。\n建議改選隨身碟、外接硬碟或 OneDrive。仍要使用這個資料夾嗎？", { yes: "仍要使用" }))) return;
        r = await api("extra_set", folder, true);
      }
      toast("已完成第二份備份"); reload();
    } catch (x) { reload(); errorBox(x.message); }
  }
  async function choose() { const f = await api("pick_folder", "選擇第二份備份的位置", e.dir); if (f) setExtra(f); }
  async function runNow() { try { await api("extra_run"); toast("已完成第二份備份"); } catch (x) { errorBox(x.message); } reload(); }
  async function disable() { if (await ask("停用後不會再自動做第二份備份（已經備份的檔案會保留）。確定嗎？", { yes: "停用" })) { await api("extra_disable"); reload(); } }
  let status = null;
  if (e.dir) {
    if (e.error && (e.days == null || e.days > 0)) status = html`<span class="c-expense b">上次備份失敗：${e.error}</span>`;
    else if (e.last) status = html`<span class=${(e.remind ? "c-expense" : "c-income") + " b"}>上次成功備份：${ymd(e.last.slice(0, 10))} ${e.last.slice(11, 16)}（${e.days === 0 ? "今天" : `${e.days} 天前`}）</span>`;
    else status = html`<span class="c-gold b">還沒有備份過，按「立即備份」試試看。</span>`;
  }
  return html`<${Card} title="資料管理與備份" icon="save"><div class="form">
    <${Field} label="資料位置" hint="每天第一次開啟程式時會自動備份，保留最近 30 份於「自動備份」資料夾。自動備份跟帳本在同一台電腦上，建議再設定下面的「第二份備份」。">
      <div class="row wrap"><code class="path">${d.db_path}</code><${Btn} icon="folder" onClick=${() => open(d.folder)}>開啟資料夾</${Btn}></div></${Field}>
    <${Field} label="備份與還原"><div class="row wrap">
      <${Btn} icon="save" onClick=${backupNow}>立即備份到…</${Btn}><${Btn} icon="restore" onClick=${restore}>從備份檔還原…</${Btn}>
      <${Btn} icon="folder" onClick=${() => open(d.backup_dir)}>開啟自動備份資料夾</${Btn}><${Btn} kind="danger" icon="trash" onClick=${reset}>清除所有資料…</${Btn}></div></${Field}>
    <${Field} label="帳務工具" hint="健康檢查會確認檔案完整、借貸平衡、備份正常；月結小幫手每月初帶您收好上個月的帳；提醒中心可新增保費、信用卡繳款等提醒。">
      <div class="row wrap"><${Btn} icon="heart" onClick=${() => openHealth()}>資料健康檢查</${Btn}>
        <${Btn} icon="check" onClick=${() => openMonthClose()}>月結小幫手</${Btn}><${Btn} icon="lock" onClick=${() => openYearAssist()}>年度結帳小幫手</${Btn}><${Btn} icon="bell" onClick=${() => openReminders()}>到期提醒中心</${Btn}>
        <${Btn} icon="trend_up" onClick=${() => openForecast()}>現金流預測</${Btn}><${Btn} icon="heart" onClick=${() => openFeedback()}>意見回饋</${Btn}></div></${Field}>
    <${Field} label="第二份備份" hint="每天第一次開啟程式、以及關閉程式時（有記帳的話），帳本會另外複製一份到這裡，連同憑證附件，保留最近 30 天。電腦硬碟故障時，可以用「從備份檔還原…」選這裡的檔案救回帳本。隨身碟沒插上時不會影響記帳，插上後下次開啟就會補上。">
      <div class="extra-box">
        ${e.dir ? html`<b>${e.target}</b>` : html`<span class="muted">尚未設定（建議設定一個隨身碟或 OneDrive 資料夾）</span>`}
        ${status && html`<div>${status}</div>`}
        <div class="row wrap">
          ${e.dir ? html`<${Btn} kind="primary" icon="save" onClick=${runNow}>立即備份</${Btn}><${Btn} icon="folder" onClick=${choose}>改用其他位置…</${Btn}>`
            : html`<${Btn} kind="primary" icon="folder" onClick=${choose}>選擇隨身碟或資料夾…</${Btn}>`}
          ${e.onedrive && e.dir !== e.onedrive && html`<${Btn} icon="save" onClick=${() => setExtra(e.onedrive)}>使用 OneDrive</${Btn}>`}
          ${e.dir && html`<${Btn} icon="folder" onClick=${async () => { try { open(await api("extra_folder")); } catch (x) { errorBox(x.message); } }}>開啟</${Btn}>
            <${Btn} kind="link" onClick=${disable}>停用</${Btn}>`}
        </div></div></${Field}>
  </div></${Card}>`;
}
function ConfirmWord({ close }) {
  const [w, setW] = useState("");
  return html`<${Dialog} title="最後確認" icon="alert" accent="var(--expense)" width="30rem" onClose=${() => close(null)}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}><${Btn} kind="danger-solid" disabled=${w !== "清除"} onClick=${() => close(w)}>清除所有資料</${Btn}>`}>
    <p>請輸入「清除」兩個字以確認：</p><${TextInput} value=${w} onInput=${setW} autofocus /></${Dialog}>`;
}
