// 我的理財帳本 v3：外框（側邊欄、頁面切換、快捷鍵、對話框、提示訊息）。
// Preact + htm，不需要建置步驟；帳務資料由 Python（v3/api*.py，沿用 v2 的 app/ 模組）提供。
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
import { checkUpdates } from "./dialogs/update.js";
import { openChart, openSubject, openYearClose } from "./dialogs/chart.js";
import { askVoidReason, openAudit, openTxn, openVoucher } from "./dialogs/txn.js";
import { openAccount, openAdjust } from "./dialogs/account.js";
import { openPrices, openRates, openSecurity, openSecurityList, openTrade } from "./dialogs/invest.js";
import { openAnnual, openPrint } from "./dialogs/print.js";
import { openExport } from "./dialogs/data.js";

const NAV = [["dashboard", "總覽", "home"], ["transactions", "收支明細", "list"], ["accounts", "帳戶管理", "wallet"],
             ["investments", "投資管理", "chart"], ["reports", "財務報表", "excel"], ["settings", "設定", "settings"]];
const FILL = ["transactions", "investments", "reports"];
const PAGES = { dashboard: Dashboard, transactions: Transactions, accounts: Accounts, investments: Investments, reports: Reports, settings: Settings };

async function undo() {
  const label = await api("undo_label");
  if (!label) return toast("目前沒有可以復原的操作", "info");
  if (!(await ask(`要復原「${label}」嗎？\n\n新增的傳票會改為作廢（保留在帳上），修改會改回原來的內容。`, { title: "復原上一步", yes: "復原" }))) return;
  try { toast(`已復原：${await api("undo")}`); changed(); } catch (e) { errorBox(e.message); }
}
window.__undo = undo;

// 自動測試與截圖用的掛鉤（v3/devshots.py 透過 evaluate_js 操作畫面）
const ALL = { start: "1900-01-01", end: "2999-12-31" };
window.__t = {
  go: (p) => window.__go(p), openTxn, openAccount, openAdjust, openPrices, openRates, openSecurity, openSecurityList, openTrade, openAnnual, openPrint, openExport, openChart, openSubject, openYearClose,
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

function Toasts() {
  const list = useToasts();
  return html`<div class="toasts">${list.map((t) => html`<div class=${"toast " + t.kind} key=${t.id}>
    <${Icon} name=${t.kind === "error" ? "alert" : t.kind === "info" ? "info" : "check"} />${t.text}</div>`)}</div>`;
}

function App() {
  const [page, setPage] = useState("dashboard");
  const [, force] = useState(0);
  const go = (p) => setPage(p);
  window.__go = go;

  useEffect(() => {
    const onKey = (e) => {
      if (window.__modalOpen) return;
      if (e.ctrlKey && e.key >= "1" && e.key <= "6") { go(NAV[+e.key - 1][0]); e.preventDefault(); }
      else if (e.ctrlKey && (e.key === "n" || e.key === "N")) { e.preventDefault(); openTxn({ type: "expense" }); }
      else if (e.ctrlKey && (e.key === "z" || e.key === "Z") && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); undo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const Page = PAGES[page];
  const r = document.documentElement;
  const setPref = (t, s) => {
    applyPrefs(t, s);
    api("set_pref", "theme_mode", t);
    api("set_pref", "font_scale", s);
    force((x) => x + 1);
  };
  window.__setPrefs = (t, s) => { applyPrefs(t, s); force((x) => x + 1); };

  return html`<div class="shell">
    <aside class="side">
      <div class="brand"><div class="logo"><${Icon} name="book" size="1.35rem" /></div>
        <div><b>我的理財帳本</b><span>個人資產與記帳管理</span></div></div>
      ${NAV.map(([k, label, ic], i) => html`<button class=${"nav" + (page === k ? " on" : "")} onClick=${() => go(k)}
          title=${"Ctrl+" + (i + 1)}><${Icon} name=${ic} />${label}</button>`)}
      <div class="grow"></div><hr />
      <button class="nav" onClick=${() => openTxn({ type: "expense" })}><${Icon} name="plus" />記一筆<kbd>Ctrl+N</kbd></button>
      <button class="nav" onClick=${undo}><${Icon} name="undo" />復原<kbd>Ctrl+Z</kbd></button>
      <div class="prefs">
        <div class="seg mini" title="外觀：切換後立即生效">
          <button class=${r.dataset.theme === "light" ? "on" : ""} onClick=${() => setPref("light", r.dataset.scale)}>淺色</button>
          <button class=${r.dataset.theme === "dark" ? "on" : ""} onClick=${() => setPref("dark", r.dataset.scale)}><${Icon} name="moon" />深色</button></div>
        <div class="seg mini" title="文字大小">
          ${[["normal", "標準"], ["large", "大"], ["xlarge", "特大"]].map(([k, l]) =>
            html`<button class=${r.dataset.scale === k ? "on" : ""} onClick=${() => setPref(r.dataset.theme, k)}>${l}</button>`)}</div>
      </div>
      <div class="foot"><span class="dot"></span>v${META.version}（v3 新介面測試版）<br />資料僅存於本機</div>
    </aside>
    <main class="main"><div class=${"page" + (FILL.includes(page) ? " fill" : "")}>
      ${Page ? html`<${Page} go=${go} key=${page} />`
        : html`<div class="todo"><div><${Icon} name=${NAV.find((n) => n[0] === page)[2]} size="3rem" />
            <b>${NAV.find((n) => n[0] === page)[1]}</b>這一頁正在製作中，目前請使用 v2 版本。</div></div>`}
    </div></main>
    <${ModalHost} /><${MenuHost} /><${Toasts} />
  </div>`;
}

async function boot() {
  try {
    setMeta(await api("meta"));
  window.__folder = META.folder;
  } catch (e) {
    document.getElementById("app").innerHTML = `<div class="boot">無法開啟帳本：${e.message}</div>`;
    return;
  }
  const dark = META.theme === "dark" || (META.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  applyPrefs(dark ? "dark" : "light", META.font_scale || "large");
  if (META.animations && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.documentElement.classList.add("animate");
  render(html`<${App} />`, document.getElementById("app"));
  if (!META.smoke) setTimeout(() => checkUpdates(true).catch(() => {}), 4000);   // 每天第一次開啟時檢查新版本（可在設定關閉）
}

if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);
