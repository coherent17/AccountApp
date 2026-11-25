// 操作導覽的引擎：在真正的畫面上打亮一個地方、旁邊說明，一步一步往下看。只看不改：導覽期間不能操作畫面，也不會存任何帳務資料。
// 內容在 guides.js；從 startGuide(id) 開始。看過的紀錄存在帳本的設定 guides（JSON）。
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { api, html } from "./core.js";
import { Btn, Icon, closeTop } from "./ui.js";

let GUIDES = {};
export const guides = () => GUIDES;
export const registerGuides = (g) => { GUIDES = g; };

// ------------------------------------------------------------------ 看過的紀錄
export const state = { seen: {}, offered: [], off: false, ready: false };
const subs = new Set();
const notify = () => subs.forEach((f) => f((x) => x + 1));
export function useGuideState() {
  const [, force] = useState(0);
  useEffect(() => { subs.add(force); return () => subs.delete(force); }, []);
  return state;
}
const apply = (s) => { Object.assign(state, s); notify(); };
export const loadGuides = async () => apply(await api("guide_state"));
export const guidesReady = () => apply({ ready: true });        // 開啟時的視窗（更新說明、到期提醒…）都關了之後，才開始提示
export const markGuide = (id, what) => api("guide_mark", id, what).then(apply).catch(() => {});
export const setGuideOff = (off) => api("guide_off", off).then(apply).catch(() => {});
export const resetGuides = () => api("guide_reset").then(apply);
export const unseen = (id) => !state.off && !state.seen[id] && !state.offered.includes(id);

// ------------------------------------------------------------------ 找出要打亮的地方
const visible = (el) => { const r = el.getBoundingClientRect(); return r.width > 1 && r.height > 1 && getComputedStyle(el).visibility !== "hidden"; };
/** t：CSS 選擇器，或 [選擇器, 文字]（文字相符的那一個；第三項 "up" 表示框住它的外層）。對話框的導覽只在最上面的對話框裡找。 */
export function findTargets(step, g) {
  const root = g.dialog ? [...document.querySelectorAll(".dialog")].pop() : document;
  if (!root || !step.t) return [];
  const [sel, text, up] = Array.isArray(step.t) ? step.t : [step.t];
  const list = [...root.querySelectorAll(sel)].filter((el) => visible(el) && (!text || el.textContent.includes(text))).map((el) => (up ? el.parentElement : el));
  return step.all ? list : list.slice(0, 1);
}
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(step, g, alive) {          // 換頁、換分頁後等畫面出來
  for (let n = 0; n < 40 && alive(); n++) {
    const els = document.querySelector(".skeleton") && !g.dialog ? [] : findTargets(step, g);
    if (els.length) return els;
    if (step.optional && n > 8) return [];
    await wait(70);
  }
  return [];
}

// ------------------------------------------------------------------ 畫面
let setRun = null;
export const guideOpen = () => !!window.__guideOpen;

/** 開始導覽。視窗的導覽（g.dialog）若視窗還沒開著，會先開一個空白的，看完自動關掉。 */
export async function startGuide(id) {
  const g = GUIDES[id];
  if (!g || window.__guideOpen) return;
  window.__guideOpen = id;
  const from = window.__pageId;
  let opened = false;
  if (g.dialog && !(window.__helpStack || []).slice(-1).includes(id)) {
    g.open();
    opened = true;
    for (let n = 0; n < 50 && !(window.__helpStack || []).slice(-1).includes(id); n++) await wait(80);
    if (!(window.__helpStack || []).slice(-1).includes(id)) { window.__guideOpen = null; return; }      // 還不能用（例如沒有帳戶就不能對帳）：視窗本身會說明
    await wait(250);
  }
  if (document.activeElement) document.activeElement.blur();
  if (g.page && window.__pageId !== g.page) { window.__go(g.page); await wait(250); }
  return new Promise((resolve) => setRun({ id, g, i: 0, dir: 1, opened, from, resolve }));
}

const PAD = 7;
function unionRect(els) {
  const rs = els.map((e) => e.getBoundingClientRect());
  const l = Math.min(...rs.map((r) => r.left)), t = Math.min(...rs.map((r) => r.top)), r = Math.max(...rs.map((x) => x.right)), b = Math.max(...rs.map((x) => x.bottom));
  const x = Math.max(4, l - PAD), y = Math.max(4, t - PAD);
  return { x, y, w: Math.min(innerWidth - 4, r + PAD) - x, h: Math.min(innerHeight - 4, b + PAD) - y };
}
/** 說明卡放在打亮處的下、上、右、左中放得下的一邊；都放不下就放在畫面角落（避開打亮處的左上角）。 */
export function placeCard(hole, w, h) {
  const W = innerWidth, H = innerHeight, m = 14;
  const clampX = (x) => Math.max(10, Math.min(W - w - 10, x)), clampY = (y) => Math.max(10, Math.min(H - h - 10, y));
  if (!hole) return { x: (W - w) / 2, y: (H - h) / 2, side: "none" };
  const cx = hole.x + hole.w / 2, cy = hole.y + hole.h / 2;
  if (hole.y + hole.h + m + h <= H - 8) return { x: clampX(cx - w / 2), y: hole.y + hole.h + m, side: "below" };
  if (hole.y - m - h >= 8) return { x: clampX(cx - w / 2), y: hole.y - m - h, side: "above" };
  if (hole.x + hole.w + m + w <= W - 8) return { x: hole.x + hole.w + m, y: clampY(cy - h / 2), side: "right" };
  if (hole.x - m - w >= 8) return { x: hole.x - m - w, y: clampY(cy - h / 2), side: "left" };
  return { x: W - w - 26, y: H - h - 22, side: "none" };
}

/** **粗體** 與 [[按鍵]]。 */
export function Rich({ text }) {
  return (text || "").split(/(\*\*.+?\*\*|\[\[.+?\]\])/).map((p) => (p.startsWith("**") ? html`<b>${p.slice(2, -2)}</b>` : p.startsWith("[[") ? html`<kbd>${p.slice(2, -2)}</kbd>` : p));
}

export function GuideHost() {
  const [run, set] = useState(null);
  setRun = set;
  const [hole, setHole] = useState(null);
  const [pos, setPos] = useState(null);
  const [ready, setReady] = useState(false);
  const card = useRef(null);
  const key = run ? `${run.id}:${run.i}` : "";

  async function finish(done) {
    const r = run;
    window.__guideOpen = null;
    set(null); setHole(null); setPos(null); setReady(false);
    if (r.opened) closeTop();
    if (r.from !== window.__pageId && (!done || r.g.group === "news")) window.__go(r.from);      // 中途結束、看完新功能：回到原來的頁面
    await markGuide(r.id, done ? "seen" : "offered");
    r.resolve(done);
  }
  const move = (d) => {
    const i = run.i + d;
    if (i < 0) return;
    if (i >= run.g.steps.length) return finish(true);
    set({ ...run, i, dir: d });
  };

  // 走到一步：換頁（step.go）、執行 step.before（例如切換分頁），等目標出現再打亮；可略過的步驟找不到就跳過
  useEffect(() => {
    if (!run) return;
    let alive = true, timer = null;
    const step = run.g.steps[run.i];
    (async () => {
      if (step.go && window.__pageId !== step.go) { setHole(null); window.__go(step.go); await wait(250); }
      if (step.before) { try { await step.before(); } catch (_) { /* 找不到就照常說明 */ } await wait(150); }
      const els = step.t ? await settle(step, run.g, () => alive) : [];
      if (!alive) return;
      window.__guideMissing = step.t && !els.length ? key : "";
      if (step.t && !els.length && step.optional) {
        const i = run.i + run.dir;
        if (i < 0) return set({ ...run, i: run.i + 1, dir: 1 });
        return i >= run.g.steps.length ? finish(true) : set({ ...run, i });
      }
      if (els.length) els[0].scrollIntoView({ block: els[0].offsetHeight > innerHeight * .7 ? "start" : "center", behavior: "instant" });
      // 卡片進場、捲動停下來之後才打亮，框與說明卡不會跟著晃
      for (let n = 0, prev = "", same = 0; els.length && n < 16 && same < 2 && alive; n++) {
        await wait(70);
        const now = JSON.stringify(unionRect(els));
        same = now === prev ? same + 1 : 0;
        prev = now;
      }
      if (!alive) return;
      let last = "";
      const follow = () => {           // 畫面可能還在排版或捲動，打亮的框跟著走
        const live = els.filter((e) => e.isConnected);
        const r = live.length ? unionRect(live) : null;
        const s = JSON.stringify(r);
        if (s !== last) { last = s; setHole(r); }
      };
      follow();
      setReady(true);
      timer = setInterval(follow, 120);
    })();
    return () => { alive = false; clearInterval(timer); };
  }, [key]);

  useLayoutEffect(() => {
    if (!run || !card.current) return;
    const r = card.current.getBoundingClientRect();
    setPos(placeCard(hole, card.current.offsetWidth || r.width, card.current.offsetHeight || r.height));
  }, [hole, key, ready]);

  useEffect(() => {
    if (!run) return;
    const onKey = (e) => {
      e.stopPropagation();
      if (e.key === "Escape") { e.preventDefault(); finish(false); }
      else if (e.key === "ArrowRight" || e.key === "Enter" || e.key === " " || e.key === "PageDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); move(-1); }
      else e.preventDefault();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });
  window.__guideStep = run ? { id: run.id, i: run.i, n: run.g.steps.length, title: run.g.steps[run.i].title, hole, pos } : null;
  window.__guideMove = move;

  if (!run) return null;
  const step = run.g.steps[run.i], n = run.g.steps.length, last = run.i === n - 1;
  const p = pos || { x: innerWidth / 2 - 150, y: innerHeight / 2 - 90, side: "none" };
  const caret = hole && p.side !== "none" && (p.side === "below" || p.side === "above"
    ? `left:${Math.max(18, Math.min((card.current?.offsetWidth || 320) - 30, hole.x + hole.w / 2 - p.x - 7))}px`
    : `top:${Math.max(16, Math.min((card.current?.offsetHeight || 180) - 30, hole.y + hole.h / 2 - p.y - 7))}px`);
  return html`<div class="guide" role="dialog" aria-label=${run.g.title}>
    ${hole ? html`<div class="g-hole" style=${`left:${hole.x}px;top:${hole.y}px;width:${hole.w}px;height:${hole.h}px`}></div>` : html`<div class="g-dim"></div>`}
    <div class=${"g-card " + p.side} ref=${card} style=${`left:${p.x}px;top:${p.y}px;visibility:${ready || !step.t ? "visible" : "hidden"}`}>
      ${caret && html`<i class="g-caret" style=${caret}></i>`}
      <div class="g-top"><span class="badge-ic"><${Icon} name=${step.icon || run.g.icon} /></span><small>${run.g.title}</small><span class="grow"></span><small class="num">${run.i + 1} / ${n}</small></div>
      <h3>${step.title}</h3>
      <p><${Rich} text=${step.text} /></p>
      ${last && html`<p class="g-again"><${Icon} name="help" />想再看一次：${run.g.dialog ? "按視窗右上角的 ?，或" : run.g.page ? "按標題旁的 ?，或" : "左邊的「操作導覽」，或"} <kbd>F1</kbd></p>`}
      <div class="g-bar"><i style=${`width:${((run.i + 1) / n) * 100}%`}></i></div>
      <div class="g-foot"><button class="link" onClick=${() => finish(last)}>${last ? "" : "結束導覽"}</button><span class="grow"></span>
        ${run.i > 0 && html`<${Btn} onClick=${() => move(-1)}>上一步</${Btn}>`}
        <${Btn} kind="primary" icon=${last ? "check" : null} onClick=${() => move(1)}>${last ? "知道了" : "下一步"}</${Btn}></div>
    </div></div>`;
}

// ------------------------------------------------------------------ 第一次到某一頁：右下角輕輕提示一次（不擋畫面、不會再出現第二次）
let lastNudge = 0;
export function GuideNudge({ page }) {
  const s = useGuideState();
  const [id, setId] = useState(null);
  useEffect(() => {
    setId(null);
    const gid = Object.keys(GUIDES).find((k) => GUIDES[k].page === page);
    if (!gid || !s.ready) return;
    const t = setTimeout(() => {
      if (window.__modalOpen || window.__guideOpen || !unseen(gid) || Date.now() - lastNudge < 20000) return;
      lastNudge = Date.now();
      setId(gid);
      markGuide(gid, "offered");
    }, 1500);
    return () => clearTimeout(t);
  }, [page, s.ready]);
  useEffect(() => { if (!id) return; const t = setTimeout(() => setId(null), 25000); return () => clearTimeout(t); }, [id]);
  if (!id || s.off || window.__guideOpen) return null;
  const g = GUIDES[id];
  return html`<div class="nudge-card"><span class="badge-ic"><${Icon} name="help" /></span>
    <div class="grow"><b>第一次看「${g.title}」？</b><small>${g.steps.length} 個步驟，帶您認識這一頁。之後隨時可按標題旁的 ? 再看。</small>
      <div class="row"><${Btn} kind="primary" onClick=${() => { setId(null); startGuide(id); }}>帶我看看</${Btn}><${Btn} onClick=${() => setId(null)}>不用了</${Btn}>
        <button class="link" onClick=${() => { setId(null); setGuideOff(true); }}>都不要提示</button></div></div></div>`;
}
