// 檢查新版本與一鍵更新。
import { useEffect, useState } from "preact/hooks";
import { api, html, toast, ymd } from "../lib/core.js";
import { Btn, Dialog, Icon, errorBox, info, openModal } from "../lib/ui.js";

// 有新版本、但她選了「稍後再說」：不再跳出視窗，改在側邊欄顯示「有新版本」，按一下再開啟
let available = null;
const shown = new Set();
const subs = new Set();
const setAvailable = (rel) => { available = rel; subs.forEach((f) => f(rel)); };
export function useAvailableUpdate() {
  const [rel, setRel] = useState(available);
  useEffect(() => { subs.add(setRel); return () => subs.delete(setRel); }, []);
  return rel;
}

/** silent=true：自動檢查（開啟時與每 4 小時），沒有新版或失敗時不打擾；同一版本只自動跳出一次。 */
export async function checkUpdates(silent = true) {
  const s = await api("update_settings");
  if (silent && !s.due) return;
  if (!silent) toast("正在檢查新版本…", "info");
  let rel;
  try { rel = await api("update_fetch"); } catch (e) { if (!silent) errorBox(e.message); return; }
  if (!rel.newer) { setAvailable(null); if (!silent) info(`目前使用的 ${rel.current} 版已經是最新版本。`); return; }
  if (silent && s.skip === rel.version) return;
  setAvailable({ ...rel, auto: s.can_self_update && !!rel.url });
  if (silent && shown.has(rel.version)) return;
  shown.add(rel.version);
  openUpdate();
}
export function openUpdate() {
  if (!available) return;
  const rel = available;
  return openModal((close) => html`<${UpdateDialog} rel=${rel} auto=${rel.auto} close=${close} />`);
}
/** 程式開著的期間，每 30 分鐘看看是否該檢查了（實際上每 4 小時才會連線一次）。 */
export function startUpdateTimer() {
  setInterval(() => checkUpdates(true).catch(() => {}), 30 * 60 * 1000);
}

/** 更新後第一次開啟：「已更新到 x.y.z」與這一版的更新內容。 */
export async function showWhatsNew() {
  const wn = await api("whats_new");
  if (!wn) return false;
  await openModal((close) => html`<${Dialog} title=${`已更新到 ${wn.version} 版`} icon="gift" accent="var(--income)" width="40rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} kind="primary" icon="check" onClick=${() => close()}>開始使用</${Btn}>`}>
    <div class="wn-head"><div class="wn-badge"><img src="logo.svg" alt="" /></div>
      <div><b>更新完成，您的帳本資料都在</b><span class="muted">更新前已自動備份一份帳本，放在「自動備份」資料夾。</span></div></div>
    <div class="section-title sm">這個版本的新功能</div>
    <${Notes} text=${wn.notes} />
  </${Dialog}>`);
  return true;
}

// 更新說明（GitHub 上的 Markdown）：條列與段落
export function Notes({ text }) {
  const blocks = [];
  for (const line of (text || "（沒有說明）").split(/\r?\n/)) {
    const t = line.trim();
    if (!t) continue;
    const li = /^[*\-]\s+(.*)/.exec(t);
    const clean = (s) => s.replace(/\*\*(.+?)\*\*/g, "$1").replace(/^#+\s*/, "");
    if (li) {
      if (!blocks.length || blocks[blocks.length - 1].type !== "ul") blocks.push({ type: "ul", items: [] });
      blocks[blocks.length - 1].items.push(clean(li[1]));
    } else blocks.push({ type: /^#/.test(t) ? "h" : "p", text: clean(t) });
  }
  return html`<div class="notes">${blocks.map((b) => (b.type === "ul" ? html`<ul>${b.items.map((i) => html`<li>${i}</li>`)}</ul>`
    : b.type === "h" ? html`<b>${b.text}</b>` : html`<p>${b.text}</p>`))}</div>`;
}

function UpdateDialog({ rel, auto, close }) {
  const [busy, setBusy] = useState(false);
  const [prog, setProg] = useState(null);
  const [msg, setMsg] = useState("");
  async function now() {
    setBusy(true); setMsg("");
    await api("update_start", rel);
    for (;;) {
      await new Promise((r) => setTimeout(r, 400));
      const p = await api("update_progress");
      setProg(p);
      if (!p.done) continue;
      if (p.error) { setBusy(false); setMsg(p.error + "　也可以按「用瀏覽器下載」。"); return; }
      try {
        const r = await api("update_install", p.path);
        if (r.manual) {
          await info(`新版本已下載到：\n${r.manual}\n\n因為目前程式所在的資料夾無法直接更新，請關閉程式後，用這個新檔案取代原本的程式。`);
          close(); return;
        }
        await info(`已更新為 ${rel.version} 版，按「確定」後程式會重新開啟。`);
        await api("restart_app");
      } catch (e) { setBusy(false); setMsg(e.message); }
      return;
    }
  }
  const pct = prog && prog.total ? Math.round((prog.got / prog.total) * 100) : null;
  return html`<${Dialog} title="有新版本可以更新" icon="download" width="44rem" onClose=${() => !busy && close()}
      footer=${busy ? html`<div class="grow"></div><span class="muted">下載中，請稍候…</span>` : html`
        <${Btn} kind="link" onClick=${async () => { await api("update_skip", rel.version); setAvailable(null); toast(`已略過 ${rel.version} 版，有更新的版本時會再通知您`); close(); }}>略過這個版本</${Btn}>
        <div class="grow"></div><${Btn} onClick=${() => { close(); toast("左側選單會顯示「有新版本」，準備好時再按一下更新", "info"); }}>稍後再說</${Btn}>
        <${Btn} kind=${auto ? "" : "primary"} onClick=${() => { api("open_url", rel.url || rel.page).catch(() => {}); close(); }}>用瀏覽器下載</${Btn}>
        ${auto && html`<${Btn} kind="primary" icon="download" onClick=${now}>立即更新</${Btn}>`}`}>
    <div class="update-head"><b>新版本 ${rel.version} 已推出</b><span class="muted">您目前使用的是 ${rel.current} 版${rel.published ? `　｜　發布日期 ${ymd(rel.published)}` : ""}</span></div>
    <div class="section-title sm">這個版本的更新內容</div>
    <${Notes} text=${rel.notes} />
    <p class="hint">更新只會換掉程式本身，您的帳本、附件與設定都保留在「文件\\我的理財帳本」，不會變動；更新前會先自動備份一份帳本。</p>
    ${busy && html`<div class="progress"><i style=${`width:${pct ?? 30}%`} class=${pct == null ? "indet" : ""}></i></div>
      <div class="muted small">${prog && prog.total ? `正在下載新版本… ${(prog.got / 1e6).toFixed(1)} / ${(prog.total / 1e6).toFixed(1)} MB` : "正在下載新版本…"}</div>`}
    ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
  </${Dialog}>`;
}

// 自動截圖用：模擬「有新版本」與「已更新」的畫面
window.__fakeUpdate = (v) => setAvailable({ version: v, current: "3.1.0", auto: true, published: "2026-11-23", url: "x",
  notes: "新功能說明\n* 第一項改進\n* 第二項改進" });
window.__fakeWhatsNew = () => openModal((close) => html`<${Dialog} title="已更新到 3.2.0 版" icon="gift" accent="var(--income)" width="40rem" onClose=${() => close()}
    footer=${html`<div class="grow"></div><${Btn} kind="primary" icon="check" onClick=${() => close()}>開始使用</${Btn}>`}>
  <div class="wn-head"><div class="wn-badge"><img src="logo.svg" alt="" /></div>
    <div><b>更新完成，您的帳本資料都在</b><span class="muted">更新前已自動備份一份帳本，放在「自動備份」資料夾。</span></div></div>
  <div class="section-title sm">這個版本的新功能</div>
  <${Notes} text=${"更貼心的設計（3.2 版）\n* 總覽新增「本月洞察」與「本月支出排行」\n* 分類加上小圖示\n* 有新版本時左側選單會提醒"} /></${Dialog}>`);
