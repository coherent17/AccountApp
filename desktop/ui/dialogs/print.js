// 列印：報表選擇、年度財務報告、預覽（與 v2 相同的報表內容，由 Edge 列印；印表機選「另存為 PDF」即可存成 PDF）。
import { useEffect, useRef, useState } from "preact/hooks";
import { api, html, toast, ymd } from "../lib/core.js";
import { Btn, Check, Dialog, Field, Icon, Select, errorBox, openModal } from "../lib/ui.js";

// 報表 HTML（v2 的 app/printing.py）加上 A4 版面與頁碼
function pageCss(landscape) {
  return `<style>
    @page { size: A4 ${landscape ? "landscape" : "portrait"}; margin: 14mm 12mm 16mm;
      @bottom-center { content: "第 " counter(page) " 頁，共 " counter(pages) " 頁"; font: 8pt "Microsoft JhengHei UI", sans-serif; color: #64748B; } }
    html { background: #fff; }
    body { font-family: "Microsoft JhengHei UI", "Microsoft JhengHei", sans-serif; color: #0F172A; margin: 0; }
    table.t thead { display: table-header-group; }
    table.t tr { break-inside: avoid; }
    @media screen { body { padding: 18px 22px; } }
  </style>`;
}

/** 預覽並列印一份 HTML 報表。 */
export function openPreview(htmlText, title = "列印預覽", landscape = false) {
  return openModal((close) => html`<${Preview} src=${htmlText} title=${title} landscape0=${landscape} close=${close} />`);
}
function Preview({ src, title, landscape0, close }) {
  const frame = useRef(null);
  const [landscape, setLandscape] = useState(landscape0);
  const doc = src.replace("<head>", "<head>" + pageCss(landscape));
  return html`<${Dialog} title=${title} icon="print" width="70rem" cls="preview" onClose=${() => close()}
      footer=${html`<${Check} checked=${landscape} onChange=${setLandscape}>橫向列印（試算表、總分類帳欄位較多時建議使用）</${Check}>
        <div class="grow"></div><span class="hint">要存成 PDF：在列印視窗的「印表機」選「另存為 PDF」。</span>
        <${Btn} onClick=${() => close()}>關閉</${Btn}>
        <${Btn} kind="primary" icon="print" onClick=${() => frame.current.contentWindow.print()}>列印／另存 PDF…</${Btn}>`}>
    <iframe ref=${frame} class="paper" srcdoc=${doc} title=${title}></iframe>
  </${Dialog}>`;
}

export async function printVoucher(tid) {
  try { openPreview(await api("voucher_html", tid), "列印傳票"); } catch (e) { errorBox(e.message); }
}

// ------------------------------------------------------------------ 報表列印
export async function openPrint(start, end) {
  const o = await api("print_options");
  return openModal((close) => html`<${PrintDialog} o=${o} start=${start} end=${end} close=${close} />`);
}
function PrintDialog({ o, start, end, close }) {
  const [keys, setKeys] = useState(new Set(["bs", "is"]));
  const [cmp, setCmp] = useState(o.compare);
  const [landscape, setLandscape] = useState(false);
  const [busy, setBusy] = useState(false);
  const toggle = (k, on) => { const s = new Set(keys); on ? s.add(k) : s.delete(k); setKeys(s); };
  async function go() {
    setBusy(true);
    try {
      api("set_setting", "print_compare", cmp);
      const chosen = o.reports.map((r) => r[0]).filter((k) => keys.has(k));
      const h = await api("print_html", chosen, start, end, cmp);
      openPreview(h, "列印報表", landscape);
    } catch (e) { errorBox(e.message); } finally { setBusy(false); }
  }
  return html`<${Dialog} title="列印報表" icon="print" width="40rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}>
        <${Btn} kind="primary" icon="eye" disabled=${!keys.size || busy} onClick=${go}>預覽與列印</${Btn}>`}>
    <p class="muted">期間：${ymd(start)} 至 ${ymd(end)}（依財務報表頁上方的期間）</p>
    <div class="checks">${o.reports.map(([k, name]) => html`<${Check} checked=${keys.has(k)} onChange=${(v) => toggle(k, v)}>${name}</${Check}>`)}</div>
    <div class="form" style="margin-top:1rem">
      <${Field} label="比較方式" hint="資產負債表、收支損益表與財務比率的比較欄"><${Select} value=${cmp} onChange=${setCmp} options=${[["none", "不比較"], ["prior_period", "與上一期比較"], ["prior_year", "與去年同期比較"]]} /></${Field}>
    </div>
    <${Check} checked=${landscape} onChange=${setLandscape}>橫向列印（試算表、總分類帳欄位較多時建議使用）</${Check}>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 年度財務報告
/** 年度財務報告；year0 為預設年度。看過預覽時傳回 true。 */
export async function openAnnual(years, year0 = null) {
  const o = await api("print_options");
  return openModal((close) => html`<${AnnualDialog} o=${o} years=${years} year0=${year0} close=${close} />`);
}
function AnnualDialog({ o, years, year0, close: done }) {
  const [seen, setSeen] = useState(false);
  const close = () => done(seen);
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(year0 || (years.includes(thisYear - 1) && new Date().getMonth() < 3 ? thisYear - 1 : years[0]));
  const [secs, setSecs] = useState(new Set(o.annual_saved || o.annual.filter((a) => a[2]).map((a) => a[0])));
  const [busy, setBusy] = useState(false);
  const toggle = (k, on) => { const s = new Set(secs); on ? s.add(k) : s.delete(k); setSecs(s); };
  async function go() {
    setBusy(true);
    try {
      const chosen = o.annual.map((a) => a[0]).filter((k) => secs.has(k));
      api("set_setting", "annual_sections", chosen.join(","));
      openPreview(await api("annual_html", year, chosen), `${year} 年度財務報告`); setSeen(true);
    } catch (e) { errorBox(e.message); } finally { setBusy(false); }
  }
  return html`<${Dialog} title="年度財務報告" icon="book" width="44rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}>
        <${Btn} kind="primary" icon="eye" disabled=${busy} onClick=${go}>${busy ? "產生中…" : "預覽與列印"}</${Btn}>`}>
    <p class="hint">一鍵產生整年度的完整報告：封面與重點數字、目錄，以及勾選的章節（每章從新的一頁開始）。</p>
    <div class="form"><${Field} label="年度"><${Select} value=${year} onChange=${setYear} options=${years.map((y) => [y, `${y} 年（民國 ${y - 1911} 年）`])} /></${Field}></div>
    <div class="checks" style="margin-top:.8rem">${o.annual.map(([k, name]) => html`<${Check} checked=${secs.has(k)} onChange=${(v) => toggle(k, v)}>${name}</${Check}>`)}</div>
    ${o.first_year && o.first_year >= year && html`<p class="hint">這是記帳的第一年，比較報表只列今年。</p>`}
  </${Dialog}>`;
}
