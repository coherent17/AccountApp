// 新介面導覽：第一次使用新介面時，用三張卡片介紹最常用的地方（之後可在「設定」重新觀看）。
import { useState } from "preact/hooks";
import { api, html } from "../lib/core.js";
import { Btn, Icon, openModal } from "../lib/ui.js";

const SLIDES = [
  { icon: "home", color: "var(--primary)", title: "歡迎使用全新的理財帳本",
    text: "畫面換上新的設計，但您的帳本、會計科目和報表都和以前一樣。左邊的選單可以切換總覽、收支明細、帳戶、投資、報表與設定。",
    tips: [["plus", "記一筆", "左下角「記一筆」或按 Ctrl+N"], ["search", "搜尋", "找任何一筆紀錄：Ctrl+F"]] },
  { icon: "undo", color: "var(--income)", title: "記錯了也不用擔心",
    text: "每次儲存後，右下角的提示會出現「復原」按鈕，按一下就能取消剛才的動作；作廢的紀錄也會保留在帳上，隨時可以恢復。",
    tips: [["undo", "復原", "提示上的「復原」或 Ctrl+Z"], ["restore", "修改紀錄", "每一次修改都留有紀錄"]] },
  { icon: "moon", color: "var(--adjust)", title: "看得清楚、用得舒服",
    text: "左下角可以切換「淺色／深色」與「標準／大／特大」字體，立刻生效。結束時按「⏻」或右上角 ✕，帳本會自動儲存並完成備份。",
    tips: [["moon", "深色模式", "晚上看比較不刺眼"], ["power", "結束程式", "自動儲存、自動備份"]] },
];

export const openTour = () => openModal((close) => html`<${Tour} close=${close} />`);

function Tour({ close }) {
  const [i, setI] = useState(0);
  const s = SLIDES[i];
  const last = i === SLIDES.length - 1;
  const finish = () => { api("tour_done"); close(true); };
  return html`<div class="dialog tour" style="width:min(36rem, calc(100vw - 3rem))" role="dialog">
    <div class="tour-art" style=${`--c:${s.color}`} key=${i}>
      <div class="tour-ic"><${Icon} name=${s.icon} size="2.4rem" /></div>
    </div>
    <div class="tour-body" key=${"b" + i}>
      <h2>${s.title}</h2><p>${s.text}</p>
      <div class="tour-tips">${s.tips.map(([ic, t, d]) => html`<div><span><${Icon} name=${ic} /></span><div><b>${t}</b><small>${d}</small></div></div>`)}</div>
    </div>
    <div class="dfoot">
      <div class="dots">${SLIDES.map((_, j) => html`<i class=${j === i ? "on" : ""} onClick=${() => setI(j)}></i>`)}</div>
      <div class="grow"></div>
      ${i > 0 ? html`<${Btn} onClick=${() => setI(i - 1)}>上一步</${Btn}>` : html`<${Btn} kind="link" onClick=${finish}>略過</${Btn}>`}
      <${Btn} kind="primary" icon=${last ? "check" : null} onClick=${() => (last ? finish() : setI(i + 1))}>${last ? "開始使用" : "下一步"}</${Btn}>
    </div>
  </div>`;
}
