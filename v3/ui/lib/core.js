// 共用核心：格式化、呼叫 Python、資料變更通知、提示訊息。所有畫面都從這裡匯入。
import { h } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import htm from "htm";

export const html = htm.bind(h);
export let META = { base: "TWD", currencies: { TWD: { symbol: "NT$", decimals: 0, name: "新台幣" } } };
export const setMeta = (m) => { META = m; };

// ------------------------------------------------------------------ 呼叫 Python
// Python 端的錯誤（例如「此期間已結帳」）以 {__error__: 訊息} 傳回，這裡轉成 Error 丟出。
export async function api(name, ...args) {
  const fn = window.pywebview.api[name];
  if (!fn) throw new Error(`程式錯誤：找不到 ${name}`);
  const r = await fn(...args);
  if (r && typeof r === "object" && "__error__" in r) {
    const e = new Error(r.__error__);
    e.user = !r.__bug__;
    throw e;
  }
  return r;
}

// ------------------------------------------------------------------ 資料變更
// 任何寫入成功後呼叫 changed()，所有用 useLoad 讀資料的畫面都會重新讀取（等同 v2 的 ctx.changed）。
let version = 0;
const subs = new Set();
export function changed() { version += 1; subs.forEach((f) => f(version)); }
export function useVersion() {
  const [v, setV] = useState(version);
  useEffect(() => { subs.add(setV); return () => subs.delete(setV); }, []);
  return v;
}

/** 讀取資料：deps 改變或帳本有變更時重新讀取；回傳 [data, reload]。 */
export function useLoad(loader, deps = []) {
  const v = useVersion();
  const [data, setData] = useState(null);
  const seq = useRef(0);
  const run = () => {
    const my = ++seq.current;
    Promise.resolve(loader()).then((d) => { if (my === seq.current) setData(d); })
      .catch((e) => { if (my === seq.current) toast(e.message, "error"); });
  };
  useEffect(run, [...deps, v]);
  return [data, run];
}

// ------------------------------------------------------------------ 提示訊息
const toastSubs = new Set();
export function toast(text, kind = "ok") { toastSubs.forEach((f) => f({ text, kind, id: Math.random() })); }
export function useToasts() {
  const [list, setList] = useState([]);
  useEffect(() => {
    const f = (t) => {
      setList((l) => [...l.slice(-2), t]);
      setTimeout(() => setList((l) => l.filter((x) => x.id !== t.id)), t.kind === "error" ? 6000 : 3200);
    };
    toastSubs.add(f);
    return () => toastSubs.delete(f);
  }, []);
  return list;
}

// ------------------------------------------------------------------ 格式
export function cur(code) { return META.currencies[code] || { symbol: code + " ", decimals: 2, name: code }; }
export const decimalsFor = (code) => cur(code || META.base).decimals;

export function num(v, code = META.base, signed = false, decimals) {
  const d = decimals ?? decimalsFor(code);
  const x = Math.round((v || 0) * 10 ** d) / 10 ** d + 0;
  const s = Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  return (x < 0 ? "-" : signed && x > 0 ? "+" : "") + s;
}
export function money(v, code = META.base, signed = false) {
  const d = decimalsFor(code);
  const x = Math.round((v || 0) * 10 ** d) / 10 ** d + 0;
  return (x < 0 ? "-" : signed && x > 0 ? "+" : "") + cur(code).symbol + num(Math.abs(x), code);
}
export const pct = (v, d = 1) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
export const ymd = (iso) => (iso ? iso.replaceAll("-", "/") : "");
export const WEEK = "日一二三四五六";
export function longDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日（民國${d.getFullYear() - 1911}年）星期${WEEK[d.getDay()]}`;
}
export const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
export const rootFontPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize);

export function isoToday(offset = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return isoOf(d);
}
export const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** 手動輸入的日期：西元或民國年，例如 2026/11/5、115/11/5、20261105、1151105、11/5（與 v2 相同）。 */
export function parseDate(text) {
  let t = (text || "").normalize("NFKC").split("(")[0].split("（")[0].trim();
  if (!t) return null;
  let parts;
  if (/^\d+$/.test(t)) {
    const n = t.length;
    if (![4, 7, 8].includes(n)) return null;
    parts = n > 4 ? [t.slice(0, -4), t.slice(-4, -2), t.slice(-2)] : [t.slice(0, 2), t.slice(2)];
  } else {
    parts = t.split(/[/\-.\s年月日]+/).filter(Boolean);
  }
  if (![2, 3].includes(parts.length) || !parts.every((p) => /^\d+$/.test(p))) return null;
  const nums = parts.map(Number);
  if (nums.length === 2) nums.unshift(new Date().getFullYear());
  if (nums[0] < 1000) nums[0] += 1911;
  const [y, m, d] = nums;
  const dt = new Date(y, m - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d || y < 1900 || y > 2200) return null;
  return isoOf(dt);
}
export function dateLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return `${ymd(iso)}（${WEEK[d.getDay()]}）`;
}

/** 金額算式（加減乘除與括號），與 v2 的 safe_eval 相同；失敗傳回 null。 */
export function evalAmount(expr, digits = 2) {
  let s = (expr ?? "").toString().replace(/[,，\s]/g, "").replace(/＋/g, "+").replace(/－/g, "-")
    .replace(/[×xX＊]/g, "*").replace(/[÷／]/g, "/").normalize("NFKC");
  if (!s) return null;
  let i = 0;
  const peek = () => s[i];
  function factor() {
    if (peek() === "+") { i++; return factor(); }
    if (peek() === "-") { i++; return -factor(); }
    if (peek() === "(") { i++; const v = expr_(); if (s[i++] !== ")") throw 0; return v; }
    const m = /^\d+(\.\d*)?|^\.\d+/.exec(s.slice(i));
    if (!m) throw 0;
    i += m[0].length;
    return parseFloat(m[0]);
  }
  function term() {
    let v = factor();
    while (peek() === "*" || peek() === "/") {
      const op = s[i++], r = factor();
      if (op === "/" && r === 0) throw 0;
      v = op === "*" ? v * r : v / r;
    }
    return v;
  }
  function expr_() {
    let v = term();
    while (peek() === "+" || peek() === "-") { const op = s[i++]; const r = term(); v = op === "+" ? v + r : v - r; }
    return v;
  }
  try {
    const v = expr_();
    if (i !== s.length || !isFinite(v)) return null;
    return Math.round(v * 10 ** digits) / 10 ** digits;
  } catch { return null; }
}

// ------------------------------------------------------------------ 期間
export const PERIOD_PRESETS = ["本月", "上月", "近 3 個月", "今年", "去年", "全部", "自訂期間"];
export function presetRange(name, dataRange) {
  const t = new Date(), y = t.getFullYear(), m = t.getMonth();
  const iso = (yy, mm, dd) => isoOf(new Date(yy, mm, dd));
  switch (name) {
    case "本月": return [iso(y, m, 1), iso(y, m + 1, 0)];
    case "上月": return [iso(y, m - 1, 1), iso(y, m, 0)];
    case "近 3 個月": return [iso(y, m - 2, 1), isoOf(t)];
    case "今年": return [iso(y, 0, 1), iso(y, 11, 31)];
    case "去年": return [iso(y - 1, 0, 1), iso(y - 1, 11, 31)];
    default: return dataRange;
  }
}

export const TYPE_LABELS = { income: "收入", expense: "支出", transfer: "轉帳", adjust: "餘額調整", journal: "分錄" };

// ------------------------------------------------------------------ 外觀（深色、字級）
// 切換後立即生效；圖表依此重畫。
const prefSubs = new Set();
export function applyPrefs(theme, scale) {
  const r = document.documentElement;
  r.dataset.theme = theme;
  r.dataset.scale = scale;
  prefSubs.forEach((f) => f(theme + scale));
}
export function usePrefsKey() {
  const r = document.documentElement;
  const [k, setK] = useState(r.dataset.theme + r.dataset.scale);
  useEffect(() => { prefSubs.add(setK); return () => prefSubs.delete(setK); }, []);
  return k;
}
