// 我的理財帳本 v3：外框（側邊欄、頁面切換、快捷鍵、對話框、提示訊息）。
// Preact + htm，不需要建置步驟；帳務資料由 Python（desktop/api*.py，帳務在 core/）提供。
import { render } from "preact";
import { useEffect, useState } from "preact/hooks";
import { META, api, applyPrefs, changed, html, setMeta, toast, useToasts } from "./lib/core.js";
import { Icon, MenuHost, ModalHost, ask, errorBox } from "./lib/ui.js";
import { Dashboard } from "./pages/dashboard.js";
import { Transactions } from "./pages/transactions.js";
import { Accounts } from "./pages/accounts.js";
import { Investments } from "./pages/investments.js";
import { Reports } from "./pages/reports.js";
import { Settings } from "./pages/settings.js";
import { checkUpdates, openUpdate, showWhatsNew, startUpdateTimer, useAvailableUpdate } from "./dialogs/update.js";
import { openTour } from "./dialogs/tour.js";
import { openFeedback, useFeedbackCount, openForecast, openHealth, openMonthClose, openMonthly, openReminders, previewMonthly } from "./dialogs/tools.js";
import { openChart, openSubject, openYearClose } from "./dialogs/chart.js";
import { openJournal } from "./dialogs/journal.js";
import { openDue, openImport, openReconcile, openRecurring, openSearch, openWelcome } from "./dialogs/more.js";
import { showTransactions } from "./pages/transactions.js";
import { showSecurity } from "./pages/investments.js";
import { askVoidReason, openAudit, openTxn, openVoucher } from "./dialogs/txn.js";
import { openAccount, openAdjust } from "./dialogs/account.js";
import { openPrices, openRates, openSecurity, openSecurityList, openTrade } from "./dialogs/invest.js";
import { openAnnual, openPrint } from "./dialogs/print.js";
import { openExport } from "./dialogs/data.js";

const NAV = [["dashboard", "總覽", "home"], ["transactions", "收支明細", "list"], ["accounts", "帳戶管理", "wallet"],
             ["investments", "投資管理", "chart"], ["reports", "財務報表", "excel"], ["settings", "設定", "settings"]];
const FILL = ["transactions", "reports", "investments"];
const PAGES = { dashboard: Dashboard, transactions: Transactions, accounts: Accounts, investments: Investments, reports: Reports, settings: Settings };

async function undo() {
  const label = await api("undo_label");
  if (!label) return toast("目前沒有可以復原的操作", "info");
  if (!(await ask(`要復原「${label}」嗎？\n\n新增的傳票會改為作廢（保留在帳上），修改會改回原來的內容。`, { title: "復原上一步", yes: "復原" }))) return;
  try { toast(`已復原：${await api("undo")}`); changed(); } catch (e) { errorBox(e.message); }
}
window.__undo = undo;

// 自動測試與截圖用的掛鉤（desktop/devshots.py 透過 evaluate_js 操作畫面）
const ALL = { start: "1900-01-01", end: "2999-12-31" };
window.__t = {
  go: (p) => window.__go(p), openTxn, openAccount, openAdjust, openPrices, openRates, openSecurity, openSecurityList, openTrade, openAnnual, openPrint, openExport, openChart, openSubject, openYearClose, openJournal,
  openRecurring, openDue, openReconcile, openImport, openHealth, openMonthClose, openMonthly, openReminders, previewMonthly, openForecast, openFeedback, openSearch: () => openSearch(window.__go), openWelcome,
  // 目前畫面上「完整看得到」的表格列數（每一個表格各算一次），用來驗證她要求的行數
  visibleRows: () => [...document.querySelectorAll(".tablewrap, .table-card")].filter((w) => w.offsetParent && w.querySelector("tbody")).map((w) => {
    const wr = w.getBoundingClientRect(), vh = window.innerHeight;
    const top = Math.max(wr.top, 0), bottom = Math.min(wr.bottom, vh);
    const rows = [...w.querySelectorAll("tbody tr")].filter((tr) => { const r = tr.getBoundingClientRect(); return r.top >= top - 1 && r.bottom <= bottom + 1; });
    const hbar = w.scrollWidth > w.clientWidth + 2 ? "有橫向捲軸" : "欄位全部顯示";
    const tr = w.querySelector("tbody tr"), th = w.querySelector("thead");
    const fit = tr ? Math.floor((bottom - Math.max(top, th ? th.getBoundingClientRect().bottom : top)) / tr.getBoundingClientRect().height) : 0;
    return `${rows.length} 列，可容納 ${fit} 列（${hbar}）`;
  }).join("；"),
  audit: () => {
    // 每個看得到的表格：完整看得到幾列／共幾列、可容納幾列、是否需要左右捲動
    const out = [];
    for (const t of document.querySelectorAll("table")) {
      if (!t.offsetParent || !t.tBodies[0] || t.closest(".pop")) continue;
      const rows = [...t.tBodies[0].rows].filter((r) => r.getBoundingClientRect().height > 0);
      if (!rows.length) continue;
      let top = 0, bottom = innerHeight, hbar = false;
      for (let e = t.parentElement; e && e !== document.body; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (/(auto|scroll|hidden)/.test(cs.overflowY)) { const r = e.getBoundingClientRect(); top = Math.max(top, r.top); bottom = Math.min(bottom, r.bottom); }
        if (!hbar && /(auto|scroll)/.test(cs.overflowX) && e.scrollWidth > e.clientWidth + 2 && !e.classList.contains("main"))
          hbar = `${e.scrollWidth}>${e.clientWidth}px［${[...(t.tHead ? t.tHead.rows[0].cells : [])].map((c) => c.textContent.slice(0, 4) + Math.round(c.offsetWidth)).join(" ")}］`;
      }
      const th = t.tHead && t.tHead.getBoundingClientRect();
      if (th && th.height && th.top >= top - 1 && th.top < bottom) top = Math.max(top, th.bottom);
      const vis = rows.filter((r) => { const b = r.getBoundingClientRect(); return b.top >= top - 1 && b.bottom <= bottom + 1; }).length;
      const rh = rows.reduce((a, r) => a + r.getBoundingClientRect().height, 0) / rows.length;
      const name = (t.closest(".dialog") ? "[對話框] " : "") + (t.className || "table").replace(/\s+/g, ".");
      out.push(`${name} 看得到 ${vis}/${rows.length} 列，可容納約 ${Math.max(0, Math.floor((bottom - top) / rh))} 列${hbar ? "，有左右捲軸 " + hbar : ""}`);
    }
    const m = document.querySelector(".main");
    if (m && m.scrollHeight > m.clientHeight + 4) out.push(`整頁可上下捲動（${m.scrollHeight}/${m.clientHeight}px）`);
    return out.join("；") || "（沒有表格）";
  },
  openTour, openUpdateFake: (v) => { window.__fakeUpdate(v); },
  openUserJournal: async () => openJournal({ tid: (await api("txn_list", { ...ALL, type: "journal" })).rows.find((r) => !r.source).id }),
  journalTemplate: (name) => { const s = document.querySelector(".journal .jtop select"); const i = [...s.options].findIndex((o) => o.text === name); s.value = i; s.dispatchEvent(new Event("change", { bubbles: true })); },
  tab: (label) => [...document.querySelectorAll(".tabs button")].find((b) => b.textContent.includes(label)).click(), openVoucher, openAudit, askVoid: () => askVoidReason(2),
  prefs: (t, s) => window.__setPrefs(t, s),
  editFirst: async () => openVoucher((await api("txn_list", { ...ALL, type: "expense" })).rows[0].id),
  openFirstOf: async (type) => openVoucher((await api("txn_list", { ...ALL, type })).rows[0].id),
  menuFirst: () => {
    const tr = document.querySelector(".table-card tbody tr");
    const r = tr.getBoundingClientRect();
    tr.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 2 }));
    tr.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, clientX: r.left + 300, clientY: r.top + 10 }));
  },
};

// 提示訊息：可以復原的操作直接附「復原」按鈕
function Toasts() {
  const list = useToasts();
  return html`<div class="toasts">${list.map((t) => {
    const canUndo = /（Ctrl\+Z 可復原）/.test(t.text);
    const text = t.text.replace(/（Ctrl\+Z 可復原）/, "");
    return html`<div class=${"toast " + t.kind} key=${t.id}>
      <${Icon} name=${t.kind === "error" ? "alert" : t.kind === "info" ? "info" : "check"} /><span>${text}</span>
      ${canUndo && html`<button class="undo" onClick=${undo} title="Ctrl+Z">復原</button>`}</div>`;
  })}</div>`;
}

// 結束畫面：關閉視窗時顯示「帳本已儲存」，同時完成第二份備份（由 Python 呼叫）
function farewellHtml(steps, done) {
  const name = META.owner ? `，${META.owner}` : "";
  return `<div class="inner">
    ${done ? `<div class="ok"><svg class="ic" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg></div>` : `<div class="mark"><img src="logo.svg" alt=""></div>`}
    <h1>${done ? "帳本已安全儲存" : "正在儲存帳本…"}</h1>
    <div class="steps">${steps.map((x) => `<div><svg class="ic" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>${x}</div>`).join("")}</div>
    <p>${done ? `祝您有美好的一天${name}，下次見！` : "請稍候，馬上就好"}</p>
    ${done ? "" : `<div class="bar"><i></i></div>`}</div>`;
}
window.__farewell = (steps = [], done = false) => {
  let el = document.getElementById("farewell");
  if (!el) {
    el = document.createElement("div");
    el.id = "farewell";
    el.className = "splash";
    document.body.appendChild(el);
  }
  el.innerHTML = farewellHtml(steps, done);
  return true;
};

const SECTIONS = { dashboard: "", transactions: "記帳", accounts: "記帳", investments: "資產", reports: "報表", settings: "" };

function SideBar({ page, go, setPref }) {
  const r = document.documentElement;
  const upd = useAvailableUpdate();
  const fbN = useFeedbackCount();
  const owner = META.owner || "您好";
  return html`<aside class="side">
    <div class="brand"><div class="logo"><img src="logo.svg" alt="" /></div>
      <div><b>我的理財帳本</b><span>個人資產與記帳管理</span></div></div>
    ${NAV.map(([k, label, ic], i) => html`<button class=${"nav" + (page === k ? " on" : "")} onClick=${() => go(k)}
        title=${"Ctrl+" + (i + 1)}><${Icon} name=${ic} />${label}</button>`)}
    <div class="grow"></div>
    ${upd && html`<button class="update-pill" onClick=${openUpdate} title="按一下查看更新內容並更新"><span class="pulse"></span>
      <div><b>有新版本 ${upd.version}</b><small>按這裡更新</small></div><${Icon} name="download" /></button>`}
    <div class="section-label">快速功能</div>
    <button class="nav" onClick=${() => openTxn({ type: "expense" })}><${Icon} name="plus" />記一筆<kbd>Ctrl+N</kbd></button>
    <button class="nav" onClick=${() => openSearch(go)}><${Icon} name="search" />搜尋<kbd>Ctrl+F</kbd></button>
    <button class="nav" onClick=${undo}><${Icon} name="undo" />復原<kbd>Ctrl+Z</kbd></button>
    <div class="prefs">
      <div class="seg mini" title="外觀：切換後立即生效">
        <button class=${r.dataset.theme === "light" ? "on" : ""} onClick=${() => setPref("light", r.dataset.scale)}>淺色</button>
        <button class=${r.dataset.theme === "dark" ? "on" : ""} onClick=${() => setPref("dark", r.dataset.scale)}><${Icon} name="moon" />深色</button></div>
      <div class="seg mini" title="文字大小">
        ${[["normal", "標準"], ["large", "大"], ["xlarge", "特大"]].map(([k, l]) =>
          html`<button class=${r.dataset.scale === k ? "on" : ""} onClick=${() => setPref(r.dataset.theme, k)}>${l}</button>`)}</div>
    </div>
    <div class="userbox" title="資料只儲存在這台電腦">
      <div class="avatar">${owner.slice(0, 1)}</div>
      <div class="grow"><b>${owner}</b><span><span class="dot"></span>版本 ${META.version}</span></div>
      <button class="iconbtn power fb" title="意見回饋：寫下問題或想法（可累積好幾則），產生 PDF 傳給我們" onClick=${() => openFeedback()}><${Icon} name="heart" />${fbN > 0 && html`<i class="fb-badge">${fbN}</i>`}</button>
      <button class="iconbtn power" title="結束程式（帳本會自動儲存並備份）" onClick=${() => api("quit_app")}><${Icon} name="power" /></button>
    </div>
  </aside>`;
}

function App() {
  const [page, setPage] = useState("dashboard");
  const [, force] = useState(0);
  const go = (p) => setPage(p);
  window.__go = go;
  window.__showTransactions = (f) => showTransactions(go, f);
  window.__showSecurity = (sid) => showSecurity(go, sid);

  useEffect(() => {
    const onKey = (e) => {
      if (window.__modalOpen) return;
      if (e.ctrlKey && e.key >= "1" && e.key <= "6") { go(NAV[+e.key - 1][0]); e.preventDefault(); }
      else if (e.ctrlKey && (e.key === "n" || e.key === "N")) { e.preventDefault(); openTxn({ type: "expense" }); }
      else if (e.ctrlKey && (e.key === "f" || e.key === "F")) { e.preventDefault(); openSearch(go); }
      else if (e.ctrlKey && (e.key === "z" || e.key === "Z") && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); undo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { const m = document.querySelector(".main"); if (m) m.scrollTop = 0; }, [page]);

  const Page = PAGES[page];
  window.__pageName = (NAV.find((n) => n[0] === page) || [, ""])[1];     // 意見回饋記下是在哪一頁
  const setPref = (t, s) => {
    applyPrefs(t, s);
    api("set_pref", "theme_mode", t);
    api("set_pref", "font_scale", s);
    force((x) => x + 1);
  };
  window.__setPrefs = (t, s) => { applyPrefs(t, s); force((x) => x + 1); };

  return html`<div class="shell">
    <${SideBar} page=${page} go=${go} setPref=${setPref} />
    <main class="main"><div class=${"page" + (FILL.includes(page) ? " fill" : "")}>
      <div class="pagefx" key=${page}><${Page} go=${go} /></div>
    </div></main>
    <${ModalHost} /><${MenuHost} /><${Toasts} />
  </div>`;
}

async function boot() {
  try {
    setMeta(await api("meta"));
  window.__folder = META.folder;
  } catch (e) {
    document.getElementById("splash")?.remove();
    document.getElementById("app").innerHTML = `<div class="boot">無法開啟帳本：${e.message}</div>`;
    return;
  }
  const dark = META.theme === "dark" || (META.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  applyPrefs(dark ? "dark" : "light", META.font_scale || "large");
  if (META.animations && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.documentElement.classList.add("animate");
  render(html`<${App} />`, document.getElementById("app"));
  const splash = document.getElementById("splash");               // 啟動畫面：資料準備好後淡出
  if (splash) setTimeout(() => { splash.classList.add("hide"); setTimeout(() => splash.remove(), 600); }, META.smoke ? 0 : 350);
  if (!META.smoke) {
    await new Promise((r) => setTimeout(r, 500));                           // 等啟動畫面淡出
    if (await api("first_run")) await openWelcome();                       // 第一次開啟：稱呼、基本帳戶或範例資料
    else await showWhatsNew();                                             // 剛更新：「已更新到…」與更新內容
    if (await api("tour_status")) await openTour();                        // 第一次使用新介面：三張卡片的導覽
    setTimeout(() => checkUpdates(true).catch(() => {}), 4000);            // 檢查新版本（開啟時，之後每 4 小時）
    startUpdateTimer();
    await openDue().catch(() => {});                                       // 定期交易到期提醒
    const ym = await api("month_close_prompt").catch(() => "");            // 月初：上個月的月結還沒完成就提醒一次
    if (ym) openMonthClose(ym);
  }
}

if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);
