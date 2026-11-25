// 操作導覽的目錄：所有導覽都能從這裡重看（側邊欄「操作導覽」、F1、設定）。
import { useState } from "preact/hooks";
import { META, html, toast } from "../lib/core.js";
import { Btn, Check, Dialog, Icon, openModal } from "../lib/ui.js";
import { guides, resetGuides, setGuideOff, startGuide, useGuideState } from "../lib/guide.js";
import { GROUPS } from "../guides.js";
import { openTour } from "./tour.js";

export async function openGuides() {
  const id = await openModal((close) => html`<${GuideCenter} close=${close} />`);
  if (id === "slides") return (await openTour()) === "walk" && startGuide("screen");
  if (id) setTimeout(() => startGuide(id), 60);
}

function GuideCenter({ close }) {
  const s = useGuideState();
  const [group, setGroup] = useState("all");
  const all = Object.entries(guides());
  const here = all.find(([, g]) => g.page === window.__pageId);
  const done = all.filter(([id]) => s.seen[id]).length;
  const Item = ([id, g], hi) => html`<button class=${"gitem" + (hi ? " hi" : "")} onClick=${() => close(id)}>
      <span class="badge-ic"><${Icon} name=${g.icon} /></span>
      <span class="gtxt"><b>${hi ? `這一頁：${g.title}` : g.title}</b><small>${g.desc}</small></span>
      ${s.seen[id] ? html`<span class="gseen" title=${`看過（${s.seen[id].replace(/-/g, "/")}），按一下再看一次`}><${Icon} name="check" /></span>` : html`<span class="gn num">${g.steps.length} 步</span>`}</button>`;
  const shown = GROUPS.filter(([k]) => group === "all" || group === k);
  return html`<${Dialog} title="操作導覽" icon="help" width="60rem" cls="listdlg guides" onClose=${() => close()}
      footer=${html`<${Check} checked=${!s.off} onChange=${(v) => setGuideOff(!v)}>第一次到新的頁面時，輕輕提示一次</${Check}>
        <${Btn} kind="link" icon="restore" onClick=${async () => { await resetGuides(); toast("已清除看過的紀錄，每一頁會再提示一次"); }}>重新開始</${Btn}>
        <div class="grow"></div><span class="muted small">看過 ${done} / ${all.length}</span><${Btn} kind="primary" onClick=${() => close()}>關閉</${Btn}>`}>
    <div class="pchips gtabs"><button type="button" class=${group === "all" ? "on" : ""} onClick=${() => setGroup("all")}>全部</button>
      ${GROUPS.map(([k, l]) => html`<button type="button" class=${group === k ? "on" : ""} onClick=${() => setGroup(k)}>${l}</button>`)}</div>
    <div class="tablewrap glist">
      ${group === "all" && here && Item(here, true)}
      ${shown.map(([k, label]) => html`<div class="gsec">${label}</div><div class="ggrid">
        ${all.filter(([, g]) => g.group === k).map((x) => Item(x))}
        ${k === "page" && html`<button class="gitem" onClick=${() => close("slides")}><span class="badge-ic"><${Icon} name="insight" /></span>
          <span class="gtxt"><b>歡迎導覽</b><small>第一次使用時的三張卡片</small></span><span class="gn num">3 張</span></button>`}</div>`)}
    </div>
  </${Dialog}>`;
}
