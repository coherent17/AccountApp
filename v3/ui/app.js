// 我的理財帳本 v3（試作）：總覽頁。Preact + htm，不需要建置步驟；資料由 Python（v3/api.py）提供。
import { h, render } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import htm from "htm";
import { ICONS } from "./icons.js";

const html = htm.bind(h);
let META = { base: "TWD", currencies: { TWD: { symbol: "NT$", decimals: 0 } } };

// ------------------------------------------------------------------ 格式
function money(v, cur = META.base, signed = false) {
  const c = META.currencies[cur] || { symbol: cur + " ", decimals: 2 };
  const n = Math.abs(v || 0).toLocaleString("en-US", { minimumFractionDigits: c.decimals, maximumFractionDigits: c.decimals });
  const neg = (v || 0) < 0 && Math.abs(v) >= Math.pow(10, -c.decimals) / 2;
  return (neg ? "-" : signed && v > 0 ? "+" : "") + c.symbol + n;
}
const pct = (v, d = 1) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
const ymd = (iso) => iso.replaceAll("-", "/");
const WEEK = "日一二三四五六";
function longDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日（民國${d.getFullYear() - 1911}年）星期${WEEK[d.getDay()]}`;
}
function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "夜深了" : h < 11 ? "早安" : h < 18 ? "午安" : "晚安";
}
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// ------------------------------------------------------------------ 元件
const Icon = ({ name, size }) =>
  html`<svg class="ic" viewBox="0 0 24 24" style=${size ? `width:${size};height:${size}` : ""}
            dangerouslySetInnerHTML=${{ __html: ICONS[name] || "" }}></svg>`;

function CountUp({ value, format }) {
  // 數字滾動：與 v2 的動畫開關共用（關閉時直接顯示）
  const [shown, setShown] = useState(value);
  const from = useRef(0);
  useEffect(() => {
    if (!document.documentElement.classList.contains("animate")) { setShown(value); return; }
    const start = performance.now(), a = from.current, b = value, dur = 900;
    let raf;
    const step = (t) => {
      const k = Math.min(1, (t - start) / dur), e = 1 - Math.pow(1 - k, 3);
      setShown(a + (b - a) * e);
      if (k < 1) raf = requestAnimationFrame(step); else from.current = b;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return html`<span class="num">${format(shown)}</span>`;
}

function useChart(build, deps) {
  // ECharts 圖表：依目前配色建立；深色／淺色或字型改變時重畫，視窗大小改變時自動調整
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || !window.echarts) return;
    const chart = echarts.init(ref.current, null, { renderer: "canvas" });
    chart.setOption(build(), true);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, deps);
  return ref;
}

function chartBase() {
  const fs = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return {
    animation: document.documentElement.classList.contains("animate"),
    textStyle: { fontFamily: css("--font"), color: css("--text-2"), fontSize: fs * 0.78 },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--line"),
               textStyle: { color: css("--text"), fontSize: fs * 0.82 }, extraCssText: "border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.12)" },
    grid: { left: 8, right: 12, top: 20, bottom: 4, containLabel: true },
  };
}
const axis = (data) => ({
  type: "category", data, axisTick: { show: false }, axisLine: { lineStyle: { color: css("--line-strong") } },
  axisLabel: { color: css("--text-3") },
});
const valueAxis = () => ({
  type: "value", splitLine: { lineStyle: { color: css("--chart-grid"), type: "dashed" } },
  axisLabel: { color: css("--text-3"), formatter: (v) => (Math.abs(v) >= 10000 ? v / 10000 + "萬" : v) },
});
const PALETTE = () => (document.documentElement.dataset.theme === "dark"
  ? ["#6E8EF7", "#3FCB94", "#F5B342", "#F4757A", "#AC94F8", "#2CC3D5", "#F07DB8", "#9BD13A", "#8A97AD", "#F7914F"]
  : ["#3056D3", "#0C9A6A", "#F0A020", "#DC444A", "#7350DD", "#0EA5B7", "#E45FA2", "#7CB518", "#64748B", "#F07A2E"]);

function Spark({ values, prefsKey }) {
  const ref = useChart(() => ({
    animation: true, grid: { left: 0, right: 0, top: 6, bottom: 0 },
    xAxis: { type: "category", show: false, boundaryGap: false, data: values.map((_, i) => i) },
    yAxis: { type: "value", show: false, min: (v) => v.min - (v.max - v.min) * 0.35 },
    series: [{ type: "line", data: values, smooth: 0.35, symbol: "none", lineStyle: { color: "rgba(255,255,255,.95)", width: 2.5 },
               areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                 { offset: 0, color: "rgba(255,255,255,.35)" }, { offset: 1, color: "rgba(255,255,255,0)" }]) } }],
  }), [values, prefsKey]);
  return html`<div class="spark" ref=${ref}></div>`;
}

function Kpi({ title, icon, color, value, sub, delta, hero, spark, prefsKey, delay = 0 }) {
  const style = hero ? "" : `color:${color}`;
  return html`<div class=${"card kpi rise" + (hero ? " hero" : "")} style=${`animation-delay:${delay}ms`}>
    ${hero && spark && html`<${Spark} values=${spark} prefsKey=${prefsKey} />`}
    <div class="t"><span class="badge-ic" style=${hero ? "" : `background:color-mix(in srgb, ${color} 13%, transparent);color:${color}`}>
      <${Icon} name=${icon} /></span>${title}</div>
    <div class="v" style=${style}><${CountUp} value=${value} format=${(v) => money(v)} /></div>
    <div class="s">${delta}${sub}</div>
  </div>`;
}

function Delta({ cur, prev, goodWhenUp = true }) {
  if (!prev) return null;
  const d = (cur - prev) / Math.abs(prev);
  if (!isFinite(d) || Math.abs(d) < 0.0005) return null;
  const good = (d > 0) === goodWhenUp;
  return html`<span class=${"delta " + (good ? "up" : "down")}>${d > 0 ? "▲" : "▼"} ${pct(Math.abs(d), 0)}</span>`;
}

function Metric({ name, value, hint, level, fill, color, bad = "偏高" }) {
  const label = { good: "良好", warn: "留意", bad }[level];
  return html`<div class="metric">
    <div class="name">${name}${level && html`<span class=${"pill " + level}>${label}</span>`}</div>
    <div class="val num">${value}</div>
    <div class="meter"><i style=${`width:${Math.max(2, Math.min(100, fill * 100))}%;background:${color}`}></i></div>
    <div class="hint">${hint}</div>
  </div>`;
}

// ------------------------------------------------------------------ 總覽
function Dashboard({ data, prefsKey, toast }) {
  const d = data;
  const monthLabels = d.months.map((m) => (m.endsWith("-01") ? m.slice(0, 4) + "/1" : +m.slice(5) + "月"));
  const r = d.ratios;
  const dark = document.documentElement.dataset.theme === "dark";

  const bars = useChart(() => ({
    ...chartBase(), legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: css("--text-2") } },
    grid: { left: 8, right: 12, top: 34, bottom: 4, containLabel: true },
    xAxis: axis(monthLabels), yAxis: valueAxis(),
    series: [
      { name: "收入", type: "bar", data: d.monthly.map((x) => x.income), barGap: "15%", barMaxWidth: 16,
        itemStyle: { color: css("--income"), borderRadius: [5, 5, 0, 0] } },
      { name: "支出", type: "bar", data: d.monthly.map((x) => x.expense), barMaxWidth: 16,
        itemStyle: { color: css("--expense"), borderRadius: [5, 5, 0, 0] } },
    ],
  }), [d, prefsKey]);

  const trend = useChart(() => ({
    ...chartBase(), xAxis: { ...axis(monthLabels), boundaryGap: false },
    yAxis: { ...valueAxis(), scale: true },
    series: [{ name: "淨資產", type: "line", data: d.net_series, smooth: 0.3, symbolSize: 7,
               lineStyle: { width: 3, color: css("--primary") }, itemStyle: { color: css("--primary"), borderColor: css("--surface"), borderWidth: 2 },
               areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                 { offset: 0, color: dark ? "rgba(101,132,244,.35)" : "rgba(48,86,211,.22)" }, { offset: 1, color: "rgba(48,86,211,0)" }]) } }],
  }), [d, prefsKey]);

  const totalAlloc = d.allocation.reduce((s, x) => s + Math.max(0, x.value), 0) || 1;
  const pal = PALETTE();
  const donut = useChart(() => ({
    ...chartBase(), tooltip: { ...chartBase().tooltip, trigger: "item", valueFormatter: (v) => money(v) },
    series: [{ type: "pie", radius: ["62%", "88%"], padAngle: 2, itemStyle: { borderRadius: 6 }, label: { show: false },
               data: d.allocation.map((x, i) => ({ name: x.name, value: Math.max(0, x.value), itemStyle: { color: pal[i % pal.length] } })),
               emphasis: { scale: true, scaleSize: 6 } }],
    graphic: [{ type: "text", left: "center", top: "42%", style: { text: "總資產", fill: css("--text-3"), fontSize: parseFloat(getComputedStyle(document.documentElement).fontSize) * 0.8, align: "center" } },
              { type: "text", left: "center", top: "52%", style: { text: Math.abs(d.assets) >= 100000 ? (d.assets / 10000).toFixed(1) + " 萬" : money(d.assets), fill: css("--text"), fontWeight: 700, fontSize: parseFloat(getComputedStyle(document.documentElement).fontSize) * 1.05, align: "center" } }],
  }), [d, prefsKey]);

  const level = (v, good, warn, lowerIsBetter) => v == null ? null
    : lowerIsBetter ? (v <= good ? "good" : v <= warn ? "warn" : "bad") : (v >= good ? "good" : v >= warn ? "warn" : "bad");
  const colorOf = (lv) => ({ good: css("--income"), warn: css("--gold"), bad: css("--expense") }[lv] || css("--primary"));
  const lDebt = level(r.debt_ratio, 0.3, 0.5, true), lEm = level(r.emergency_months, 6, 3), lSav = level(r.savings_rate, 0.2, 0.05);
  const lCur = r.current_ratio == null ? "good" : level(r.current_ratio, 2, 1);
  const savings = d.month.income ? d.month.net / d.month.income : null;

  return html`
    <div class="head rise">
      <div><h1>${greeting()}，${META.owner || "您好"}</h1><div class="sub">${longDate(d.today)}</div></div>
      <div class="actions">
        <button class="btn t-expense" onClick=${() => toast("試作版：記帳視窗尚未製作")}><${Icon} name="minus" />記支出</button>
        <button class="btn t-income" onClick=${() => toast("試作版：記帳視窗尚未製作")}><${Icon} name="plus" />記收入</button>
        <button class="btn t-transfer" onClick=${() => toast("試作版：記帳視窗尚未製作")}><${Icon} name="transfer" />轉帳</button>
        <button class="btn primary" onClick=${() => toast("試作版：市價評價尚未製作")}><${Icon} name="refresh" />更新市值</button>
      </div>
    </div>
    ${META.demo && html`<div class="banner rise"><${Icon} name="eye" />這是 v3 介面的試作版，使用範例帳本（不會讀取或修改您的帳本）。目前只完成「總覽」頁。</div>`}

    <div class="grid kpis">
      <${Kpi} hero title="淨資產（業主權益）" icon="scale" value=${d.net} spark=${d.net_series} prefsKey=${prefsKey}
              sub=${html`<span>資產總計 − 負債總計</span>`}
              delta=${d.net_series.length > 1 && html`<span class="pill">${money(d.net - d.net_series[0], META.base, true)}　近 12 個月</span>`} />
      <${Kpi} title="資產總計" icon="bank" color=${css("--primary")} value=${d.assets} delay=${60} sub="現金、存款、投資、保單…" />
      <${Kpi} title="負債總計" icon="card" color=${css("--expense")} value=${d.liabilities} delay=${120} sub="信用卡、貸款…" />
    </div>
    <div class="grid kpis2">
      <${Kpi} title="本月收入" icon="trend_up" color=${css("--income")} value=${d.month.income} delay=${160}
              delta=${html`<${Delta} cur=${d.month.income} prev=${d.prev_month.income} />`} sub=${"上月 " + money(d.prev_month.income)} />
      <${Kpi} title="本月支出" icon="trend_down" color=${css("--expense")} value=${d.month.expense} delay=${200}
              delta=${html`<${Delta} cur=${d.month.expense} prev=${d.prev_month.expense} goodWhenUp=${false} />`} sub=${"上月 " + money(d.prev_month.expense)} />
      <${Kpi} title="本月結餘" icon="dollar" color=${d.month.net >= 0 ? css("--income") : css("--expense")} value=${d.month.net} delay=${240}
              sub=${savings == null ? "" : "儲蓄率 " + pct(savings, 0)} />
    </div>

    <div class="card rise" style="animation-delay:260ms">
      <h3><${Icon} name="heart" />財務健康指標<small>以今天為基準日</small></h3>
      <div class="grid health">
        <${Metric} name="負債比率" value=${pct(r.debt_ratio)} hint="負債 ÷ 資產，30% 以下為佳" level=${lDebt}
                   fill=${r.debt_ratio || 0} color=${colorOf(lDebt)} />
        <${Metric} name="流動比率" value=${r.current_ratio == null ? "無流動負債" : r.current_ratio.toFixed(2) + " 倍"}
                   hint="流動資產 ÷ 流動負債，1 倍以上可償還短期負債" level=${lCur} bad="不足"
                   fill=${r.current_ratio == null ? 1 : Math.min(1, r.current_ratio / 3)} color=${colorOf(lCur)} />
        <${Metric} name="緊急預備金" value=${r.emergency_months == null ? "—" : r.emergency_months.toFixed(1) + " 個月"}
                   hint="現金 ÷ 平均月支出，建議 6 個月以上" level=${lEm} bad="不足"
                   fill=${Math.min(1, (r.emergency_months || 0) / 12)} color=${colorOf(lEm)} />
        <${Metric} name="近 12 月儲蓄率" value=${pct(r.savings_rate)} hint="（收入－支出）÷ 收入，20% 以上為佳"
                   level=${lSav} bad="偏低" fill=${Math.max(0, r.savings_rate || 0)} color=${colorOf(lSav)} />
      </div>
    </div>

    ${d.reminders.length > 0 && html`<div class="card remind rise" style="animation-delay:300ms">
      <h3><${Icon} name="bell" />提醒事項</h3>
      ${d.reminders.map((x) => x.kind === "due"
        ? html`<div class="ritem"><span class="badge-ic"><${Icon} name="bell" /></span><div class="txt"><b>${x.text}</b></div>
                 <button class="btn primary" onClick=${() => toast("試作版：入帳視窗尚未製作")}>${x.action}</button></div>`
        : html`<div class=${"ritem" + (x.urgent ? " urgent" : "")}><span class="badge-ic"><${Icon} name="book" /></span>
                 <div class="txt"><b>${x.name} 將於 ${ymd(x.date)} 到期（${x.when}）</b>
                 <small>金額 ${money(x.amount, x.currency)}${x.interest ? "，預估利息 " + money(x.interest, x.currency) : ""}</small></div></div>`)}
    </div>`}

    <div class="grid wide">
      <div class="card rise" style="animation-delay:340ms"><h3><${Icon} name="chart" />近 12 個月收支</h3>
        <div class="chart" ref=${bars}></div></div>
      <div class="card rise" style="animation-delay:380ms"><h3><${Icon} name="pie" />資產配置</h3>
        <div class="alloc"><div class="chart" ref=${donut}></div>
          <div class="legend">${d.allocation.map((x, i) => html`<div><i style=${`background:${pal[i % pal.length]}`}></i>
            ${x.name}<span class="num">${pct(Math.max(0, x.value) / totalAlloc, 0)}</span></div>`)}</div></div></div>
    </div>

    <div class="grid wide">
      <div class="card rise" style="animation-delay:420ms"><h3><${Icon} name="trend_up" />淨資產趨勢<small>每月月底</small></h3>
        <div class="chart" ref=${trend}></div></div>
      <div class="card rise" style="animation-delay:460ms"><h3><${Icon} name="layers" />本月預算執行</h3>
        ${d.budgets.length === 0 ? html`<div class="muted">尚未設定預算。可到「設定 → 收支分類」為支出分類設定每月預算。</div>`
          : html`<div class="budget">${d.budgets.map((b) => {
              const k = b.used / b.budget;
              const col = k > 1 ? css("--expense") : k > 0.85 ? css("--gold") : css("--primary");
              return html`<div class=${"brow" + (k > 1 ? " over" : "")}><div class="top"><b>${b.name}</b>
                <span class="num">${money(b.used)} / ${money(b.budget)}（${pct(k, 0)}）</span></div>
                <div class="meter"><i style=${`width:${Math.min(100, k * 100)}%;background:${col}`}></i></div></div>`;
            })}</div>`}
      </div>
    </div>

    <div class="card rise" style="animation-delay:500ms"><h3><${Icon} name="list" />最近的紀錄<small>按一下可開啟傳票</small></h3>
      <table class="list"><thead><tr><th>日期</th><th>傳票號碼</th><th>類型</th><th>分類</th><th>帳戶</th><th>說明</th><th class="r">金額</th></tr></thead>
        <tbody>${d.recent.map((t) => html`<tr onClick=${() => toast(`試作版：${t.voucher} 的傳票視窗尚未製作`)}>
          <td class="num">${ymd(t.date)}</td><td class="muted num">${t.voucher}</td>
          <td><span class=${"type b-" + t.type}>${t.type_label}</span></td><td>${t.category}</td><td>${t.account}</td>
          <td class="note" title=${t.note}>${t.note}${t.tags.map((g) => html`<span class="tag">#${g}</span>`)}</td>
          <td class=${"r num c-" + t.type}><b>${money(t.amount, t.currency, t.signed)}</b></td></tr>`)}</tbody></table>
    </div>`;
}

// ------------------------------------------------------------------ 外框
const NAV = [["dashboard", "總覽", "home"], ["transactions", "收支明細", "list"], ["accounts", "帳戶管理", "wallet"],
             ["investments", "投資管理", "chart"], ["reports", "財務報表", "excel"], ["settings", "設定", "settings"]];

function App() {
  const [data, setData] = useState(null);
  const [page, setPage] = useState("dashboard");
  const [theme, setTheme] = useState(document.documentElement.dataset.theme);
  const [scale, setScale] = useState(document.documentElement.dataset.scale);
  const [msg, setMsg] = useState("");
  const prefsKey = theme + scale;

  const toast = (t) => { setMsg(t); clearTimeout(window.__tt); window.__tt = setTimeout(() => setMsg(""), 2600); };
  const applyPrefs = (t, s, save = true) => {
    document.documentElement.dataset.theme = t;
    document.documentElement.dataset.scale = s;
    setTheme(t); setScale(s);
    if (save) { window.pywebview.api.set_pref("theme_mode", t); window.pywebview.api.set_pref("font_scale", s); }
  };
  window.__setPrefs = (t, s) => applyPrefs(t, s, false);

  useEffect(() => { window.pywebview.api.dashboard().then(setData); }, []);
  useEffect(() => {
    const onKey = (e) => {
      if (e.ctrlKey && e.key >= "1" && e.key <= "6") { setPage(NAV[+e.key - 1][0]); e.preventDefault(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return html`<div class="shell">
    <aside class="side">
      <div class="brand"><div class="logo"><${Icon} name="book" size="1.35rem" /></div>
        <div><b>我的理財帳本</b><span>個人資產與記帳管理</span></div></div>
      ${NAV.map(([k, label, ic], i) => html`<button class=${"nav" + (page === k ? " on" : "")} onClick=${() => setPage(k)}
          title=${"Ctrl+" + (i + 1)}><${Icon} name=${ic} />${label}</button>`)}
      <div class="grow"></div><hr />
      <button class="nav" onClick=${() => toast("試作版：全域搜尋尚未製作")}><${Icon} name="search" />搜尋<kbd>Ctrl+F</kbd></button>
      <button class="nav" onClick=${() => toast("試作版：記帳視窗尚未製作")}><${Icon} name="plus" />記一筆<kbd>Ctrl+N</kbd></button>
      <div class="foot"><span class="dot"></span>v3 試作版<br />資料僅存於本機</div>
    </aside>
    <main class="main"><div class="page">
      <div class="prefs" style="justify-content:flex-end">
        <div class="seg" title="外觀：切換後立即生效，不必重新開啟">
          <button class=${theme === "light" ? "on" : ""} onClick=${() => applyPrefs("light", scale)}>淺色</button>
          <button class=${theme === "dark" ? "on" : ""} onClick=${() => applyPrefs("dark", scale)}><${Icon} name="moon" />深色</button></div>
        <div class="seg" title="文字大小">
          ${[["normal", "標準"], ["large", "大"], ["xlarge", "特大"]].map(([k, l]) =>
            html`<button class=${scale === k ? "on" : ""} onClick=${() => applyPrefs(theme, k)}>${l}</button>`)}</div>
      </div>
      ${page === "dashboard"
        ? (data ? html`<${Dashboard} data=${data} prefsKey=${prefsKey} toast=${toast} />` : html`<div class="boot">讀取中…</div>`)
        : html`<div class="todo"><div><${Icon} name=${NAV.find((n) => n[0] === page)[2]} size="3rem" />
            <b>${NAV.find((n) => n[0] === page)[1]}</b>試作版只完成「總覽」；確定採用新介面後，其餘頁面會依序製作。</div></div>`}
    </div></main>
    ${msg && html`<div class="toast"><${Icon} name="check" />${msg}</div>`}
  </div>`;
}

async function boot() {
  META = await window.pywebview.api.meta();
  const root = document.documentElement;
  root.dataset.theme = META.theme === "dark" || (META.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
  root.dataset.scale = META.font_scale || "large";
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) root.classList.add("animate");
  render(html`<${App} />`, document.getElementById("app"));
}

if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);
