// 匯出 Excel 報表（與 v2 相同的工作表、公式與平衡檢查）。
import { useState } from "preact/hooks";
import { api, html, toast } from "../lib/core.js";
import { Btn, Check, DateInput, Dialog, Icon, Segmented, Select, TextInput, errorBox, openModal } from "../lib/ui.js";

export async function openExport(start, end) {
  let f;
  try { f = await api("export_form"); } catch (e) { return errorBox(e.message); }
  return openModal((close) => html`<${ExportDialog} f=${f} start=${start} end=${end} close=${close} />`);
}

function ExportDialog({ f, start, end, close }) {
  const [mode, setMode] = useState(start ? "custom" : "year");
  const [year, setYear] = useState(f.years[0]);
  const [d1, setD1] = useState(start || `${new Date().getFullYear()}-01-01`);
  const [d2, setD2] = useState(end || f.range[1]);
  const [sheets, setSheets] = useState(new Set(f.saved || f.sheets.map((s) => s[0])));
  const [openAfter, setOpenAfter] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [a, b] = mode === "year" ? [`${year}-01-01`, `${year}-12-31`] : mode === "all" ? f.range : (d1 <= d2 ? [d1, d2] : [d2, d1]);
  const tag = mode === "year" ? `${year}年度` : mode === "all" ? "全部資料" : `${a.replaceAll("-", "")}-${b.replaceAll("-", "")}`;
  const [path, setPath] = useState("");
  const shown = path || `${f.folder}\\理財報表_${tag}.xlsx`;
  const toggle = (k, on) => { const s = new Set(sheets); on ? s.add(k) : s.delete(k); setSheets(s); };
  async function go() {
    setBusy(true); setMsg("");
    try {
      const p = await api("export_excel", a, b, f.sheets.map((s) => s[0]).filter((k) => sheets.has(k)), shown);
      toast("Excel 報表匯出完成");
      if (openAfter) api("open_path", p).catch(() => {});
      close(p);
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  }
  return html`<${Dialog} title="匯出 Excel 報表" icon="excel" accent="var(--income)" width="46rem" onClose=${() => close()}
      footer=${html`<${Check} checked=${openAfter} onChange=${setOpenAfter}>匯出完成後自動開啟檔案</${Check}><div class="grow"></div>
        <${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="download" disabled=${busy} onClick=${go}>${busy ? "匯出中…" : "匯出"}</${Btn}>`}>
    <div class="section-title sm">報表期間</div>
    <div class="row wrap"><${Segmented} value=${mode} onChange=${setMode} options=${[["year", "指定年度"], ["custom", "自訂期間"], ["all", "全部資料"]]} />
      ${mode === "year" && html`<${Select} value=${year} onChange=${setYear} options=${f.years.map((y) => [y, `${y} 年（民國 ${y - 1911} 年）`])} />`}
      ${mode === "custom" && html`<span class="drange"><${DateInput} value=${d1} onChange=${setD1} /><span>至</span><${DateInput} value=${d2} onChange=${setD2} /></span>`}</div>
    <div class="row" style="margin-top:1.1rem"><div class="section-title sm grow">要匯出的報表</div>
      <${Btn} kind="link" onClick=${() => setSheets(new Set(f.sheets.map((s) => s[0])))}>全選</${Btn}><${Btn} kind="link" onClick=${() => setSheets(new Set())}>全不選</${Btn}></div>
    <div class="checks three">${f.sheets.map(([n, desc]) => html`<span title=${desc}><${Check} checked=${sheets.has(n)} onChange=${(v) => toggle(n, v)}>${n}</${Check}></span>`)}</div>
    <p class="hint">合計欄位皆使用 Excel 公式，可直接在 Excel 內稽核與修改。未勾選、但被其他報表公式引用的工作表（例如收支明細）會以隱藏工作表保留。</p>
    <div class="section-title sm">存檔位置</div>
    <div class="row"><${TextInput} cls="grow" value=${shown} onInput=${setPath} />
      <${Btn} icon="folder" onClick=${async () => { const p = await api("pick_save", shown); if (p) setPath(p); }}>瀏覽…</${Btn}></div>
    ${msg && html`<div class="msg bad" style="margin-top:.6rem"><${Icon} name="alert" />${msg}</div>`}
  </${Dialog}>`;
}
