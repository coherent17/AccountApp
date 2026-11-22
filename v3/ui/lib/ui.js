// 共用元件：圖示、按鈕、對話框、表單欄位、表格、右鍵選單。
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import { ICONS } from "../icons.js";
import { catEmoji } from "./caticon.js";
import { PERIOD_PRESETS, dateLabel, decimalsFor, evalAmount, html, isoOf, num, parseDate, presetRange } from "./core.js";

export const Icon = ({ name, size, cls = "" }) =>
  html`<svg class=${"ic " + cls} viewBox="0 0 24 24" style=${size ? `width:${size};height:${size}` : ""}
            dangerouslySetInnerHTML=${{ __html: ICONS[name] || "" }}></svg>`;

/** kind：primary（每個畫面一個主要動作）、income/expense/transfer/adjust（淡色）、danger（外框）、link、ghost */
export function Btn({ kind = "", icon, children, onClick, title, disabled, type = "button", cls = "", big }) {
  const k = { income: "t-income", expense: "t-expense", transfer: "t-transfer", adjust: "t-adjust" }[kind] || kind;
  return html`<button type=${type} class=${`btn ${k} ${big ? "big" : ""} ${cls}`} onClick=${onClick} title=${title}
                      disabled=${disabled}>${icon && html`<${Icon} name=${icon} />`}${children}</button>`;
}

// ------------------------------------------------------------------ 對話框
// openModal(render) 顯示一個對話框，傳回 Promise；render(close) 中呼叫 close(值) 關閉並傳回該值。
let modalSet = null;
let modalSeq = 0;
const stack = [];          // 目前開著的對話框（由下而上），Esc 關閉最上面的一個
export function openModal(render) {
  return new Promise((resolve) => {
    const id = ++modalSeq;
    const m = { id, render };
    m.close = (v) => {
      const i = stack.indexOf(m);
      if (i < 0) return;
      stack.splice(i, 1);
      modalSet([...stack]);
      resolve(v);
    };
    stack.push(m);
    modalSet([...stack]);
  });
}
export function ModalHost() {
  const [list, setList] = useState([]);
  modalSet = setList;
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && stack.length) { e.preventDefault(); e.stopPropagation(); stack[stack.length - 1].close(undefined); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);
  window.__modalOpen = list.length > 0;
  return list.map((m, i) => html`<div class="overlay" key=${m.id} style=${`z-index:${50 + i}`}
      onMouseDown=${(e) => { if (e.target === e.currentTarget) e.currentTarget.dataset.down = "1"; }}
      onMouseUp=${(e) => { if (e.target === e.currentTarget && e.currentTarget.dataset.down) m.close(undefined); delete e.currentTarget.dataset.down; }}>
    ${m.render(m.close)}</div>`);
}

/** 對話框外框：標題列、內容、按鈕列。 */
export function Dialog({ title, icon, accent, width = "38rem", onClose, children, footer, cls = "" }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current && ref.current.querySelector("[data-autofocus] input, [data-autofocus], input:not([type=hidden]):not(.native), select, textarea, button.primary");
    if (el) setTimeout(() => el.focus(), 30);
  }, []);
  return html`<div class=${"dialog " + cls} ref=${ref} style=${`width:min(${width}, calc(100vw - 3rem))`} role="dialog">
    <div class="dhead">${icon && html`<span class="badge-ic" style=${accent ? `background:color-mix(in srgb, ${accent} 14%, transparent);color:${accent}` : ""}><${Icon} name=${icon} /></span>`}
      <h2>${title}</h2><button class="x" onClick=${() => onClose()} title="關閉（Esc）"><${Icon} name="close" /></button></div>
    <div class="dbody">${children}</div>
    ${footer && html`<div class="dfoot">${footer}</div>`}
  </div>`;
}

export function ask(text, { title = "請確認", yes = "確定", no = "取消", danger = false, detail } = {}) {
  return openModal((close) => html`<${Dialog} title=${title} icon=${danger ? "alert" : "info"} width="30rem" onClose=${() => close(false)}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(false)}>${no}</${Btn}>
        <${Btn} kind=${danger ? "danger-solid" : "primary"} onClick=${() => close(true)}>${yes}</${Btn}>`}>
      <p class="pre">${text}</p>${detail && html`<div class="hint">${detail}</div>`}</${Dialog}>`);
}
export function info(text, title = "提示") {
  return openModal((close) => html`<${Dialog} title=${title} icon="info" width="30rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} kind="primary" onClick=${() => close()}>確定</${Btn}>`}>
      <p class="pre">${text}</p></${Dialog}>`);
}
export function errorBox(text, title = "無法完成") {
  return openModal((close) => html`<${Dialog} title=${title} icon="alert" accent="var(--expense)" width="32rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} kind="primary" onClick=${() => close()}>確定</${Btn}>`}>
      <p class="pre">${text}</p></${Dialog}>`);
}

// ------------------------------------------------------------------ 表單
export const Field = ({ label, children, hint, top, cls = "" }) =>
  html`<div class=${"field " + (top || hint ? "top " : "") + cls}><label>${label}</label><div class="fv">${children}
    ${hint && html`<div class="hint">${hint}</div>`}</div></div>`;

/** options: [{value, label, group?, disabled?}] 或 [[value, label]]；value 可為數字、字串或 null。 */
export function Select({ value, onChange, options, cls = "", title, disabled, style }) {
  const opts = options.map((o) => (Array.isArray(o) ? { value: o[0], label: o[1] } : o));
  const idx = Math.max(0, opts.findIndex((o) => o.value === value));
  const groups = [];
  for (const [i, o] of opts.entries()) {
    const g = o.group || "";
    if (!groups.length || groups[groups.length - 1].g !== g) groups.push({ g, items: [] });
    groups[groups.length - 1].items.push([i, o]);
  }
  const optEl = ([i, o]) => html`<option value=${i} disabled=${o.disabled}>${o.label}</option>`;
  return html`<div class=${"select " + cls} style=${style}><select value=${idx} title=${title} disabled=${disabled}
      onChange=${(e) => onChange(opts[+e.target.value].value)}>
    ${groups.map((g) => (g.g ? html`<optgroup label=${g.g}>${g.items.map(optEl)}</optgroup>` : g.items.map(optEl)))}
  </select><${Icon} name="chevron_down" /></div>`;
}

/** 可直接打字的日期欄：西元或民國年皆可；↑↓ 前後一天；右側按鈕開月曆。 */
export function DateInput({ value, onChange, cls = "" }) {
  const [text, setText] = useState(dateLabel(value));
  const [bad, setBad] = useState(false);
  const picker = useRef(null);
  useEffect(() => { setText(dateLabel(value)); setBad(false); }, [value]);
  const commit = () => {
    const d = parseDate(text);
    if (d) { setBad(false); if (d !== value) onChange(d); else setText(dateLabel(d)); }
    else setBad(true);
  };
  const shift = (n) => { const d = new Date((parseDate(text) || value) + "T00:00:00"); d.setDate(d.getDate() + n); onChange(isoOf(d)); };
  return html`<div class=${"date " + (bad ? "bad " : "") + cls}>
    <input value=${text} onInput=${(e) => setText(e.target.value)} onBlur=${commit}
      title="可直接輸入，例如 2026/11/5、115/11/5、1151105 或 11/5；↑↓ 前後一天"
      onKeyDown=${(e) => {
        if (e.key === "Enter") commit();
        else if (e.key === "ArrowUp") { e.preventDefault(); shift(1); }
        else if (e.key === "ArrowDown") { e.preventDefault(); shift(-1); }
      }} />
    <button type="button" tabindex="-1" title="開啟月曆" onClick=${() => { try { picker.current.showPicker(); } catch { picker.current.click(); } }}>
      <${Icon} name="calendar" /></button>
    <input type="date" ref=${picker} class="native" value=${value} tabindex="-1"
      onChange=${(e) => e.target.value && onChange(e.target.value)} />
  </div>`;
}

/** 金額欄：可輸入算式（120+35*2），離開欄位時計算並加上千分位。value 為數字或 null。 */
export function AmountInput({ value, onChange, code, decimals, allowNegative = false, big, placeholder, autofocus, suffix }) {
  const d = decimals ?? decimalsFor(code);
  const fmt = (v) => (v == null ? "" : num(v, code, false, d));
  const [text, setText] = useState(fmt(value));
  const focused = useRef(false);
  useEffect(() => { if (!focused.current) setText(fmt(value)); }, [value, d]);
  const v = evalAmount(text, d);
  const isExpr = /[+\-*/×÷()]/.test(text.replace(/^-/, ""));
  const invalid = text.trim() && (v == null || (!allowNegative && v < 0));
  return html`<div class=${"amount " + (big ? "big " : "") + (invalid ? "bad" : "")} data-autofocus=${autofocus ? "1" : undefined}>
    <input inputmode="decimal" value=${text} placeholder=${placeholder ?? "0"}
      onFocus=${(e) => { focused.current = true; e.target.select(); }}
      onInput=${(e) => { setText(e.target.value); const x = evalAmount(e.target.value, d); onChange(x == null || (!allowNegative && x < 0) ? null : x); }}
      onBlur=${() => { focused.current = false; if (v != null) setText(fmt(v)); }} />
    ${isExpr && v != null && html`<span class="calc">= ${num(v, code, false, d)}</span>`}
    ${suffix && html`<span class="suffix">${suffix}</span>`}
  </div>`;
}

/** 標籤欄：輸入後按 Enter 或「、」加入；有建議清單。value 為字串陣列。 */
export function TagInput({ value, onChange, suggestions = [] }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const add = (t) => {
    const parts = t.split(/[、,，;；#\s]+/).map((x) => x.trim()).filter(Boolean);
    const next = [...value];
    for (const p of parts) if (!next.includes(p)) next.push(p);
    onChange(next);
    setText("");
  };
  const sugg = suggestions.filter((s) => !value.includes(s) && (!text || s.includes(text))).slice(0, 8);
  return html`<div class="tagin" onClick=${(e) => e.currentTarget.querySelector("input").focus()}>
    ${value.map((t) => html`<span class="chip"><${Icon} name="tag" />${t}
      <button type="button" title="移除" onClick=${(e) => { e.stopPropagation(); onChange(value.filter((x) => x !== t)); }}><${Icon} name="close" /></button></span>`)}
    <input value=${text} placeholder=${value.length ? "" : "例如：日本旅遊、房屋修繕（可留空）"}
      onInput=${(e) => { const v = e.target.value; if (/[、,，;；]$/.test(v)) add(v); else setText(v); }}
      onFocus=${() => setOpen(true)} onBlur=${() => { setTimeout(() => setOpen(false), 150); if (text.trim()) add(text); }}
      onKeyDown=${(e) => {
        if (e.key === "Enter" && text.trim()) { e.preventDefault(); add(text); }
        else if (e.key === "Backspace" && !text && value.length) onChange(value.slice(0, -1));
      }} />
    ${open && sugg.length > 0 && html`<div class="pop">${sugg.map((s) => html`<div onMouseDown=${(e) => { e.preventDefault(); add(s); }}>
      <${Icon} name="tag" />${s}</div>`)}</div>`}
  </div>`;
}

/** 文字欄（可附建議清單）。 */
export function TextInput({ value, onInput, placeholder, suggestions, icon, autofocus, cls = "" }) {
  const [open, setOpen] = useState(false);
  const sugg = suggestions && value ? suggestions.filter((s) => s !== value && s.toLowerCase().includes(value.toLowerCase())).slice(0, 8) : [];
  return html`<div class=${"text " + (icon ? "with-ic " : "") + cls} data-autofocus=${autofocus ? "1" : undefined}>
    ${icon && html`<${Icon} name=${icon} />`}
    <input value=${value} placeholder=${placeholder} onInput=${(e) => onInput(e.target.value)}
      onFocus=${() => setOpen(true)} onBlur=${() => setTimeout(() => setOpen(false), 150)} />
    ${value && icon === "search" && html`<button type="button" class="clr" onClick=${() => onInput("")} title="清除"><${Icon} name="close" /></button>`}
    ${open && sugg.length > 0 && html`<div class="pop">${sugg.map((s) => html`<div onMouseDown=${(e) => { e.preventDefault(); onInput(s); setOpen(false); }}>${s}</div>`)}</div>`}
  </div>`;
}

export const Check = ({ checked, onChange, children }) =>
  html`<label class="check"><input type="checkbox" checked=${checked} onChange=${(e) => onChange(e.target.checked)} /><span class="box"><${Icon} name="check" /></span>${children}</label>`;

export function Segmented({ value, onChange, options, cls = "" }) {
  return html`<div class=${"seg " + cls}>${options.map(([k, label, icon, kind]) =>
    html`<button type="button" class=${(value === k ? "on " : "") + (kind ? "k-" + kind : "")} onClick=${() => onChange(k)}>
      ${icon && html`<${Icon} name=${icon} />`}${label}</button>`)}</div>`;
}

/** 分類選擇：一格一格的按鈕。 */
export function Chips({ items, value, onChange, kind }) {
  return html`<div class=${"chips k-" + (kind || "")}>${items.map((it) =>
    html`<button type="button" class=${it.id === value ? "on" : ""} onClick=${() => onChange(it.id)} title=${it.code ? it.code + "　" + it.name : it.name}>
      <span class="emo">${catEmoji(it.name, kind)}</span>${it.name}</button>`)}</div>`;
}

// ------------------------------------------------------------------ 右鍵選單
let menuSet = null;
export function openMenu(e, items) {
  e.preventDefault();
  menuSet({ x: e.clientX, y: e.clientY, items: items.filter((x) => x !== false && x != null) });
}
export function MenuHost() {
  const [m, setM] = useState(null);
  menuSet = setM;
  const ref = useRef(null);
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    if (!m || !ref.current) { setPos(null); return; }
    const r = ref.current.getBoundingClientRect();
    setPos({ x: Math.min(m.x, innerWidth - r.width - 8), y: Math.min(m.y, innerHeight - r.height - 8) });
  }, [m]);
  useEffect(() => {
    if (!m) return;
    const off = () => setM(null);
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); off(); } };
    window.addEventListener("mousedown", off);
    window.addEventListener("blur", off);
    window.addEventListener("keydown", onKey, true);
    return () => { window.removeEventListener("mousedown", off); window.removeEventListener("blur", off); window.removeEventListener("keydown", onKey, true); };
  }, [m]);
  if (!m) return null;
  return html`<div class="menu" ref=${ref} style=${`left:${(pos || m).x}px;top:${(pos || m).y}px;visibility:${pos ? "visible" : "hidden"}`}
      onMouseDown=${(e) => e.stopPropagation()}>
    ${m.items.map((it) => (it === "-" ? html`<hr />` : html`<button class=${it.danger ? "danger" : ""} disabled=${it.disabled}
        onClick=${() => { setM(null); it.run(); }}><${Icon} name=${it.icon || "check"} cls=${it.icon ? "" : "hidden"} />${it.label}</button>`))}
  </div>`;
}

/** 下拉選單按鈕（例如「更多功能」）。 */
export function MenuButton({ label, icon = "more", items, kind = "" }) {
  return html`<${Btn} kind=${kind} icon=${icon} onClick=${(e) => {
    const r = e.currentTarget.getBoundingClientRect();
    openMenu({ preventDefault() {}, clientX: r.left, clientY: r.bottom + 6 }, items);
  }}>${label}<${Icon} name="chevron_down" /></${Btn}>`;
}

// ------------------------------------------------------------------ 表格
/**
 * columns: [{key, title, render(row) → 內容, sort(row) → 值, align: "r"|"c", width, cls(row), elide, nowrap}]
 * 點標題排序；按一下選取（Ctrl／Shift 多選）；按兩下或 Enter 開啟；右鍵選單；Delete 鍵。
 * 列數多時先畫前 400 列，往下捲動再補上（避免一次畫幾千列）。
 */
/** 剛儲存的紀錄：在表格中短暫發光，讓她看到新紀錄放在哪裡。 */
export function flashRow(id) {
  window.__flashId = id;
  setTimeout(() => { if (window.__flashId === id) window.__flashId = null; }, 3500);
}

export function DataTable({ columns, rows, rowKey = (r) => r.id, onActivate, onMenu, onDelete, selected, onSelect,
                            defaultSort, empty = "沒有資料", emptyAction, rowCls, sticky = true, maxHeight, foot }) {
  const [sort, setSort] = useState(defaultSort || null);
  const [limit, setLimit] = useState(400);
  const anchor = useRef(null);
  const wrap = useRef(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort[0]);
    if (!col || !col.sort) return rows;
    const k = rows.map((r, i) => [col.sort(r), i, r]);
    k.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] - b[1]) * (sort[1] ? -1 : 1));
    return k.map((x) => x[2]);
  }, [rows, sort, columns]);
  useEffect(() => setLimit(400), [rows]);
  const sel = selected || new Set();
  const click = (e, r, i) => {
    if (!onSelect) return;
    const key = rowKey(r);
    if (e.shiftKey && anchor.current != null) {
      const a = sorted.findIndex((x) => rowKey(x) === anchor.current);
      const [lo, hi] = a < i ? [a, i] : [i, a];
      onSelect(new Set(sorted.slice(lo, hi + 1).map(rowKey)));
    } else if (e.ctrlKey || e.metaKey) {
      const s = new Set(sel);
      s.has(key) ? s.delete(key) : s.add(key);
      onSelect(s);
      anchor.current = key;
    } else {
      onSelect(new Set([key]));
      anchor.current = key;
    }
  };
  const keyDown = (e) => {
    if (!sorted.length) return;
    const i = sorted.findIndex((x) => sel.has(rowKey(x)));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const j = Math.max(0, Math.min(sorted.length - 1, (i < 0 ? -1 : i) + (e.key === "ArrowDown" ? 1 : -1)));
      onSelect && onSelect(new Set([rowKey(sorted[j])]));
      anchor.current = rowKey(sorted[j]);
      const tr = wrap.current.querySelectorAll("tbody tr")[j];
      tr && tr.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && i >= 0 && onActivate) onActivate(sorted[i]);
    else if (e.key === "Delete" && onDelete && sel.size) onDelete();
    else if (e.key === "a" && e.ctrlKey && onSelect) { e.preventDefault(); onSelect(new Set(sorted.map(rowKey))); }
  };
  return html`<div class="tablewrap" ref=${wrap} tabindex="0" onKeyDown=${keyDown} style=${maxHeight ? `max-height:${maxHeight}` : ""}
      onScroll=${(e) => { const t = e.currentTarget; if (limit < sorted.length && t.scrollTop + t.clientHeight > t.scrollHeight - 600) setLimit(limit + 400); }}>
    <table class=${"list" + (sticky ? " sticky" : "") + (onSelect ? " selectable" : "")}>
      <thead><tr>${columns.map((c) => html`<th class=${(c.align || "") + (c.sort ? " sortable" : "")} style=${c.width ? `width:${c.width}` : ""}
          onClick=${() => c.sort && setSort(sort && sort[0] === c.key ? [c.key, !sort[1]] : [c.key, false])}>
          ${c.title}${sort && sort[0] === c.key && html`<span class="arrow">${sort[1] ? "▼" : "▲"}</span>`}</th>`)}</tr></thead>
      <tbody>${sorted.slice(0, limit).map((r, i) => html`<tr key=${rowKey(r)} class=${(sel.has(rowKey(r)) ? "sel " : "") + (rowCls ? rowCls(r) : "") + (window.__flashId != null && rowKey(r) === window.__flashId ? " flash" : "")}
          onMouseDown=${(e) => { if (e.button === 0) click(e, r, i); else if (e.button === 2 && !sel.has(rowKey(r)) && onSelect) { onSelect(new Set([rowKey(r)])); anchor.current = rowKey(r); } }}
          onDblClick=${() => onActivate && onActivate(r)}
          onContextMenu=${(e) => onMenu && onMenu(e, r)}>
        ${columns.map((c) => html`<td class=${(c.align || "") + (c.elide ? " elide" : "") + (c.nowrap ? " nowrap" : "") + " " + (c.cls ? c.cls(r) : "")}
            title=${c.elide ? c.tip ? c.tip(r) : (typeof c.render(r) === "string" ? c.render(r) : "") : undefined}>${c.render(r)}</td>`)}</tr>`)}
      </tbody>
      ${foot && html`<tfoot>${foot}</tfoot>`}
    </table>
    ${!sorted.length && html`<div class="empty"><div class="empty-ic"><${Icon} name="list" size="1.8rem" /></div><div>${empty}</div>${emptyAction}</div>`}
  </div>`;
}

export const TypeBadge = ({ type, label }) => html`<span class=${"type b-" + type}>${label}</span>`;

export const Card = ({ title, icon, extra, children, cls = "", style }) =>
  html`<div class=${"card " + cls} style=${style}>${title && html`<h3>${icon && html`<${Icon} name=${icon} />`}${title}${extra && html`<div class="extra">${extra}</div>`}</h3>`}${children}</div>`;

/** 頁首：彩色圖示方塊＋標題＋說明，右側是這一頁的動作按鈕。 */
export const PageHead = ({ title, sub, icon, color = "var(--primary)", children }) =>
  html`<div class="head"><div class="ph">${icon && html`<div class="ph-ic" style=${`--c:${color}`}><${Icon} name=${icon} /></div>`}
    <div><h1>${title}</h1>${sub && html`<div class="sub">${sub}</div>`}</div></div><div class="actions">${children}</div></div>`;

/** 頁尾的小提示：柔和的說明框（取代一大段灰色小字）。 */
export const Tip = ({ children }) => html`<div class="tip"><span class="tip-ic"><${Icon} name="info" /></span><div>${children}</div></div>`;

/** 常用期間的快捷按鈕（本月、上月…），日期改過時顯示「自訂」。 */
const CHIP_PERIODS = ["本月", "上月", "近 3 個月", "今年", "去年", "全部"];
export function PeriodChips({ value, onChange }) {
  return html`<div class="pchips">${CHIP_PERIODS.map((p) => html`<button type="button" class=${value === p ? "on" : ""} onClick=${() => onChange(p)}>${p}</button>`)}
    ${value === "自訂期間" && html`<button type="button" class="on">自訂</button>`}</div>`;
}

// ------------------------------------------------------------------ 分頁、期間
/** 分頁：一列的膠囊軌道；放不下時左右出現箭頭，選到的分頁會自動捲到看得見的地方。 */
export function Tabs({ tabs, value, onChange }) {
  const ref = useRef(null);
  const [edge, setEdge] = useState({ l: false, r: false });
  const measure = () => {
    const el = ref.current;
    if (el) setEdge({ l: el.scrollLeft > 4, r: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 });
  };
  useLayoutEffect(() => {
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  useEffect(() => { const b = ref.current && ref.current.querySelector("button.on"); b && b.scrollIntoView({ block: "nearest", inline: "nearest" }); }, [value]);
  const scroll = (d) => ref.current.scrollBy({ left: d * ref.current.clientWidth * 0.6, behavior: "smooth" });
  return html`<div class="tabs-wrap">
    ${edge.l && html`<button class="tab-arrow l" onClick=${() => scroll(-1)} title="往左"><${Icon} name="chevron_down" /></button>`}
    <div class="tabs" role="tablist" ref=${ref} onScroll=${measure}>${tabs.map(([k, label, icon]) => html`<button role="tab" class=${value === k ? "on" : ""}
      onClick=${() => onChange(k)}>${icon && html`<${Icon} name=${icon} />`}${label}</button>`)}</div>
    ${edge.r && html`<button class="tab-arrow r" onClick=${() => scroll(1)} title="往右，還有更多分頁"><${Icon} name="chevron_down" /></button>`}
  </div>`;
}

/** 期間選擇：常用期間＋起訖日期（改日期即變成「自訂期間」）。value = {period, start, end}；傳回 [起, 訖]。 */
export function usePeriod(initial, dataRange) {
  const [p, setP] = useState({ period: initial, start: null, end: null });
  const range = p.period === "自訂期間" ? [p.start, p.end] : presetRange(p.period, dataRange || [isoOf(new Date()), isoOf(new Date())]);
  const sorted = range[0] && range[1] && range[0] > range[1] ? [range[1], range[0]] : range;
  return [sorted, p, setP, range];
}
export function PeriodPicker({ state, label = "期間" }) {
  const [, p, setP, range] = state;
  return html`<span class="frow nogap">${label && html`<span class="lbl">${label}</span>`}
    <${PeriodChips} value=${p.period} onChange=${(v) => setP({ period: v, start: range[0], end: range[1] })} />
    <span class="drange"><${DateInput} value=${range[0]} onChange=${(d) => setP({ period: "自訂期間", start: d, end: range[1] })} /><span>～</span>
    <${DateInput} value=${range[1]} onChange=${(d) => setP({ period: "自訂期間", start: range[0], end: d })} /></span></span>`;
}

/** 可搜尋的下拉選單：輸入代號或名稱篩選，↑↓ 選擇、Enter 確定。options: [{value, label, group?, hint?}] */
export function Combo({ value, onChange, options, placeholder = "輸入代號或名稱搜尋…", disabled, cls = "" }) {
  const cur = options.find((o) => o.value === value);
  const [text, setText] = useState(null);       // null：顯示目前選項；文字：搜尋中
  const [hi, setHi] = useState(0);
  const listRef = useRef(null);
  const q = (text || "").trim().toLowerCase();
  const shown = text == null ? [] : options.filter((o) => !q || o.label.toLowerCase().includes(q)).slice(0, 80);
  const pick = (o) => { setText(null); if (o) onChange(o.value); };
  useEffect(() => {
    const el = listRef.current && listRef.current.children[hi];
    el && el.scrollIntoView({ block: "nearest" });
  }, [hi]);
  return html`<div class=${"text combo " + cls}>
    <input value=${text ?? (cur ? cur.label : "")} placeholder=${placeholder} disabled=${disabled} title=${cur ? cur.label : ""}
      onFocus=${(e) => { setText(""); setHi(Math.max(0, options.indexOf(cur))); }}
      onBlur=${() => setTimeout(() => setText(null), 150)}
      onInput=${(e) => { setText(e.target.value); setHi(0); }}
      onKeyDown=${(e) => {
        if (e.key === "ArrowDown") { e.preventDefault(); setHi(Math.min(shown.length - 1, hi + 1)); }
        else if (e.key === "ArrowUp") { e.preventDefault(); setHi(Math.max(0, hi - 1)); }
        else if (e.key === "Enter" && shown[hi]) { e.preventDefault(); pick(shown[hi]); e.target.blur(); }
        else if (e.key === "Escape") { e.stopPropagation(); setText(null); e.target.blur(); }
      }} />
    <${Icon} name="chevron_down" cls="arrow" />
    ${text != null && shown.length > 0 && html`<div class="pop" ref=${listRef}>${shown.map((o, i) => html`<div class=${i === hi ? "hi" : ""}
        onMouseDown=${(e) => { e.preventDefault(); pick(o); e.currentTarget.closest(".combo").querySelector("input").blur(); }}>
      <span class="grow">${o.label}</span>${o.hint && html`<span class="muted small">${o.hint}</span>`}</div>`)}</div>`}
  </div>`;
}

/** 載入中的骨架畫面（閃爍的灰色區塊），比「讀取中…」文字更穩定，不會跳動。 */
export function Skeleton({ kind = "page" }) {
  if (kind === "block") return html`<div class="skeleton"><div class="sk" style="height:22rem"></div></div>`;
  return html`<div class="skeleton">
    <div class="row" style="justify-content:space-between"><div class="sk" style="width:16rem;height:3.2rem"></div><div class="sk" style="width:22rem;height:2.9rem"></div></div>
    <div class="grid" style="grid-template-columns:1.3fr 1fr 1fr"><div class="sk" style="height:9.5rem"></div><div class="sk" style="height:9.5rem"></div><div class="sk" style="height:9.5rem"></div></div>
    <div class="sk" style="height:20rem"></div></div>`;
}
