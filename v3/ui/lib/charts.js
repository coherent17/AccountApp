// 圖表與數字動畫（ECharts）：依目前配色與字級建立，深色／字型改變時重畫。
import { useEffect, useRef, useState } from "preact/hooks";
import { css, html, money, rootFontPx, usePrefsKey } from "./core.js";
import { Icon } from "./ui.js";

export function CountUp({ value, format }) {
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

export function useChart(build, deps) {
  const prefs = usePrefsKey();
  // ECharts 圖表：依目前配色建立；深色／淺色或字型改變時重畫，視窗大小改變時自動調整
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || !window.echarts) return;
    const chart = echarts.init(ref.current, null, { renderer: "canvas" });
    chart.setOption(build(), true);
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); chart.dispose(); };
  }, [...deps, prefs]);
  return ref;
}

export function chartBase() {
  const fs = rootFontPx();
  return {
    animation: document.documentElement.classList.contains("animate"),
    textStyle: { fontFamily: css("--font"), color: css("--text-2"), fontSize: fs * 0.78 },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: css("--line"),
               textStyle: { color: css("--text"), fontSize: fs * 0.82 }, extraCssText: "border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.12)" },
    grid: { left: 8, right: 12, top: 20, bottom: 4, containLabel: true },
  };
}
export const axis = (data) => ({
  type: "category", data, axisTick: { show: false }, axisLine: { lineStyle: { color: css("--line-strong") } },
  axisLabel: { color: css("--text-3") },
});
export const valueAxis = () => ({
  type: "value", splitLine: { lineStyle: { color: css("--chart-grid"), type: "dashed" } },
  axisLabel: { color: css("--text-3"), formatter: (v) => (Math.abs(v) >= 10000 ? v / 10000 + "萬" : v) },
});
export const PALETTE = () => (document.documentElement.dataset.theme === "dark"
  ? ["#808DFA", "#36D1A4", "#F3BE4E", "#FA7088", "#B59CFF", "#38C5E0", "#F28BC6", "#A5D65A", "#94A0B8", "#F99A5B"]
  : ["#4655DA", "#0E9F7E", "#E8A317", "#E0435B", "#7A4DDA", "#1AA6C2", "#D94F9B", "#6FA81E", "#6B7591", "#EE7A35"]);

export function Spark({ values, prefsKey }) {
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


/** 數字卡片：圖示、標題、金額（滾動動畫）、說明；hero 為漸層的淨資產卡。 */
export function Kpi({ title, icon, color, value, sub, delta, hero, spark, prefsKey, delay = 0 }) {
  const style = hero ? "" : `color:${color}`;
  return html`<div class=${"card kpi rise" + (hero ? " hero" : "")} style=${`animation-delay:${delay}ms;--accent:${color || "var(--primary)"}`}>
    ${hero && spark && html`<${Spark} values=${spark} prefsKey=${prefsKey} />`}
    <div class="t"><span class="badge-ic" style=${hero ? "" : `background:color-mix(in srgb, ${color} 13%, transparent);color:${color}`}>
      <${Icon} name=${icon} /></span>${title}</div>
    <div class="v" style=${style}><${CountUp} value=${value} format=${(v) => money(v)} /></div>
    <div class="s">${delta}${sub}</div>
  </div>`;
}


/** 長條圖的漸層填色（上亮下深），看起來更有立體感。 */
export function barFill(cssVar) {
  const c = css(cssVar);
  return new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: c }, { offset: 1, color: c + "99" }]);
}
/** 環圈圖中間的總額文字。 */
export function donutCenter(label, value) {
  const fs = rootFontPx();
  return [{ type: "text", left: "center", top: "41%", style: { text: label, fill: css("--text-3"), fontSize: fs * 0.78, align: "center" } },
          { type: "text", left: "center", top: "51%", style: { text: value, fill: css("--text"), fontWeight: 800, fontSize: fs * 1.15, align: "center" } }];
}
export const shortMoney = (v) => (Math.abs(v) >= 100000 ? (v / 10000).toFixed(1) + " 萬" : Math.round(v).toLocaleString());
