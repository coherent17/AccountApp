// 檢查新版本與一鍵更新。
import { useState } from "preact/hooks";
import { api, html, toast, ymd } from "../lib/core.js";
import { Btn, Dialog, Icon, errorBox, info, openModal } from "../lib/ui.js";

/** silent=true：開啟程式時的每日自動檢查，沒有新版或失敗時不打擾。 */
export async function checkUpdates(silent = true) {
  const s = await api("update_settings");
  if (silent && !s.due) return;
  if (!silent) toast("正在檢查新版本…", "info");
  let rel;
  try { rel = await api("update_fetch"); } catch (e) { if (!silent) errorBox(e.message); return; }
  if (!rel.newer) { if (!silent) info(`目前使用的 ${rel.current} 版已經是最新版本。`); return; }
  if (silent && s.skip === rel.version) return;
  openModal((close) => html`<${UpdateDialog} rel=${rel} auto=${s.can_self_update && !!rel.url} close=${close} />`);
}

// 更新說明（GitHub 上的 Markdown）：條列與段落
function Notes({ text }) {
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
        <${Btn} kind="link" onClick=${async () => { await api("update_skip", rel.version); toast(`已略過 ${rel.version} 版，有更新的版本時會再通知您`); close(); }}>略過這個版本</${Btn}>
        <div class="grow"></div><${Btn} onClick=${() => close()}>稍後再說</${Btn}>
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
