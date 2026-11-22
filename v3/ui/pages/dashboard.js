// 總覽頁：淨資產、本月收支、財務健康、提醒、圖表、預算、最近的紀錄。
import { META, css, html, longDate, money, pct, rootFontPx, useLoad, api, toast, ymd } from "../lib/core.js";
import { Icon, Skeleton, Tip } from "../lib/ui.js";
import { CountUp, PALETTE, axis, barFill, chartBase, useChart, valueAxis } from "../lib/charts.js";
import { openTxn, openVoucher } from "../dialogs/txn.js";
import { openDue } from "../dialogs/more.js";
import { catEmoji } from "../lib/caticon.js";
import { Btn, ask, errorBox } from "../lib/ui.js";
import { changed } from "../lib/core.js";

async function clearSample() {
  if (!(await ask("確定要清除所有範例資料嗎？\n清除後會保留「現金」與「銀行存款」兩個空白帳戶，您可以到「帳戶管理」修改或新增帳戶。", { yes: "清除並開始" }))) return;
  await api("clear_sample"); changed(); toast("已清除範例資料，可以開始正式記帳了！");
}
async function backupNow() {
  try { await api("extra_run"); toast("第二份備份完成"); } catch (e) { errorBox(e.message); }
  changed();
}

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "夜深了" : h < 11 ? "早安" : h < 18 ? "午安" : "晚安";
}

// ------------------------------------------------------------------ 上方的數字卡片（同一個格線，邊緣對齊）
function HeroCard({ d, savings, prefsKey }) {
  const vals = d.net_series;
  const flat = !vals.length || Math.max(...vals) - Math.min(...vals) < 1;
  const change = vals.length > 1 ? d.net - vals[0] : 0;
  const ref = useChart(() => ({
    animation: document.documentElement.classList.contains("animate"),
    grid: { left: 0, right: 0, top: 8, bottom: 0 },
    tooltip: { trigger: "axis", backgroundColor: "rgba(15,23,42,.85)", borderWidth: 0, textStyle: { color: "#fff", fontSize: rootFontPx() * 0.8 },
               valueFormatter: (v) => money(v), extraCssText: "border-radius:10px" },
    xAxis: { type: "category", show: false, boundaryGap: false, data: d.months.map((m) => `${m.slice(0, 4)}/${+m.slice(5)}`) },
    yAxis: { type: "value", show: false, min: (v) => v.min - (v.max - v.min) * 0.25 },
    series: [{ name: "淨資產", type: "line", data: vals, smooth: 0.4, symbol: "circle", symbolSize: 6, showSymbol: false,
               lineStyle: { color: "rgba(255,255,255,.95)", width: 2.5 }, itemStyle: { color: "#fff" },
               areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                 { offset: 0, color: "rgba(255,255,255,.38)" }, { offset: 1, color: "rgba(255,255,255,0)" }]) } }],
  }), [d, prefsKey, flat]);
  return html`<div class="card hero2 rise">
    <div class="aurora"></div>
    <div class="t"><span class="badge-ic"><${Icon} name="scale" /></span>淨資產（業主權益）
      ${!flat && html`<span class="glass pill2">${change >= 0 ? "▲" : "▼"} ${money(Math.abs(change))}　近 12 個月</span>`}</div>
    <div class="v"><${CountUp} value=${d.net} format=${(v) => money(v)} /></div>
    <div class="s">資產總計 − 負債總計</div>
    ${flat ? html`<div class="hero-empty"><${Icon} name="trend_up" />開始記帳後，這裡會畫出每個月淨資產的變化</div>`
      : html`<div class="hero-chart" ref=${ref}></div>`}
    <div class="hero-foot">
      <div class="glass"><span>本月結餘</span><b class="num">${money(d.month.net, META.base, true)}</b></div>
      <div class="glass"><span>本月儲蓄率</span><b class="num">${savings == null ? "—" : pct(savings, 0)}</b></div>
    </div>
  </div>`;
}

function StatCard({ title, icon, color, value, sub, delta, delay = 0, children }) {
  const c = `var(${color})`;
  return html`<div class="card stat rise" style=${`animation-delay:${delay}ms;--accent:${c}`}>
    <div class="t"><span class="badge-ic" style=${`background:color-mix(in srgb, ${c} 13%, transparent);color:${c}`}><${Icon} name=${icon} /></span>
      <span class="grow">${title}</span>${delta}</div>
    <div class="v" style=${`color:${c}`}><${CountUp} value=${value} format=${(v) => money(v)} /></div>
    <div class="s">${sub}</div>
    <div class="viz">${children}</div>
  </div>`;
}

/** 資產配置：一條分段的橫條，滑鼠移上去看名稱與占比。 */
function AllocBar({ items }) {
  const pos = items.filter((x) => x.value > 0);
  const total = pos.reduce((s, x) => s + x.value, 0);
  const pal = PALETTE();
  if (!total) return html`<div class="viz-empty">尚無資產</div>`;
  return html`<div class="segbar">${pos.map((x, i) => html`<i style=${`flex:${x.value};background:${pal[i % pal.length]}`}
      title=${`${x.name}　${money(x.value)}（${pct(x.value / total, 0)}）`}></i>`)}</div>
    <div class="viz-label">${pos.slice(0, 3).map((x, i) => html`<span><i style=${`background:${pal[i % pal.length]}`}></i>${x.name} ${pct(x.value / total, 0)}</span>`)}</div>`;
}

/** 負債比率：負債 ÷ 資產。 */
function RatioBar({ ratio }) {
  const v = ratio || 0;
  const col = v <= 0.3 ? "var(--income)" : v <= 0.5 ? "var(--gold)" : "var(--expense)";
  return html`<div class="meter thick"><i style=${`width:${Math.max(1.5, Math.min(100, v * 100))}%;background:${col}`}></i></div>
    <div class="viz-label"><span>負債比率 <b style=${`color:${col}`}>${pct(ratio)}</b></span><span class="muted">30% 以下為佳</span></div>`;
}

/** 近 6 個月的小長條圖（最右邊是本月），滑鼠移上去看金額。 */
function MiniBars({ months, values, color }) {
  const m = months.slice(-6), v = values.slice(-6);
  const max = Math.max(...v, 0);
  if (!max) return html`<div class="viz-empty">近 6 個月沒有紀錄</div>`;
  return html`<div class="minibars">${v.map((x, i) => html`<div class="mb" title=${`${+m[i].slice(5)}月　${money(x)}`}>
      <i style=${`height:${Math.max(4, (x / max) * 100)}%;background:var(${color});opacity:${i === v.length - 1 ? 1 : 0.38}`}></i>
      <span>${+m[i].slice(5)}月</span></div>`)}</div>`;
}

// ------------------------------------------------------------------ 本月洞察、支出排行
function Insights({ items, go }) {
  return html`<div class="card rise insights" style="animation-delay:280ms"><h3><${Icon} name="eye" />本月洞察<small>系統幫您留意的事</small></h3>
    ${items.length === 0 ? html`<div class="muted">記帳一段時間後，這裡會用白話整理出值得注意的事，例如支出變化、超出預算的分類。</div>`
      : html`<div class="ilist">${items.map((x, i) => html`<div class=${"insight " + x.tone} style=${`animation-delay:${320 + i * 60}ms`}>
          <span class="i-ic">${x.category ? catEmoji(x.category, "expense") : html`<${Icon} name=${x.icon} />`}</span>
          <div><b>${x.text}</b>${x.sub && html`<small>${x.sub}</small>`}</div></div>`)}</div>`}
  </div>`;
}

function Ranking({ rows }) {
  const max = Math.max(...rows.map((r) => r.total), 1);
  return html`<div class="card rise ranking" style="animation-delay:320ms"><h3><${Icon} name="chart" />本月支出排行<small>與上月比較</small></h3>
    ${rows.length === 0 ? html`<div class="muted">本月還沒有支出紀錄。</div>` : rows.map((r, i) => {
      const d = r.prev ? (r.total - r.prev) / r.prev : null;
      return html`<div class="rk" style=${`animation-delay:${360 + i * 50}ms`}>
        <span class="rk-emo">${catEmoji(r.name, "expense")}</span>
        <div class="rk-main"><div class="rk-top"><b>${r.name}</b><span class="num">${money(r.total)}</span></div>
          <div class="rk-bar"><i style=${`width:${Math.max(3, (r.total / max) * 100)}%`}></i></div></div>
        <span class=${"rk-d " + (d == null || Math.abs(d) < 0.005 ? "" : d > 0 ? "up" : "down")}>${d == null ? "新" : Math.abs(d) < 0.005 ? "持平" : (d > 0 ? "▲" : "▼") + " " + Math.abs(d * 100).toFixed(0) + "%"}</span>
      </div>`;
    })}</div>`;
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
export function Dashboard({ prefsKey, go }) {
  const [d] = useLoad(() => api("dashboard"));
  if (!d) return html`<${Skeleton} />`;
  return html`<${DashboardView} d=${d} prefsKey=${prefsKey} go=${go} />`;
}

function DashboardView({ d, prefsKey, go }) {
  const monthLabels = d.months.map((m) => (m.endsWith("-01") ? m.slice(0, 4) + "/1" : +m.slice(5) + "月"));
  const r = d.ratios;
  const dark = document.documentElement.dataset.theme === "dark";

  const bars = useChart(() => ({
    ...chartBase(), legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: css("--text-2") } },
    grid: { left: 8, right: 12, top: 34, bottom: 4, containLabel: true },
    xAxis: axis(monthLabels), yAxis: valueAxis(),
    series: [
      { name: "收入", type: "bar", data: d.monthly.map((x) => x.income), barGap: "15%", barMaxWidth: 16,
        itemStyle: { color: barFill("--income"), borderRadius: [6, 6, 2, 2] } },
      { name: "支出", type: "bar", data: d.monthly.map((x) => x.expense), barMaxWidth: 16,
        itemStyle: { color: barFill("--expense"), borderRadius: [6, 6, 2, 2] } },
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
    graphic: [{ type: "text", left: "center", top: "42%", style: { text: "總資產", fill: css("--text-3"), fontSize: rootFontPx() * 0.8, align: "center" } },
              { type: "text", left: "center", top: "52%", style: { text: Math.abs(d.assets) >= 100000 ? (d.assets / 10000).toFixed(1) + " 萬" : money(d.assets), fill: css("--text"), fontWeight: 700, fontSize: rootFontPx() * 1.05, align: "center" } }],
  }), [d, prefsKey]);

  const level = (v, good, warn, lowerIsBetter) => v == null ? null
    : lowerIsBetter ? (v <= good ? "good" : v <= warn ? "warn" : "bad") : (v >= good ? "good" : v >= warn ? "warn" : "bad");
  const colorOf = (lv) => ({ good: css("--income"), warn: css("--gold"), bad: css("--expense") }[lv] || css("--primary"));
  const lDebt = level(r.debt_ratio, 0.3, 0.5, true), lEm = level(r.emergency_months, 6, 3), lSav = level(r.savings_rate, 0.2, 0.05);
  const lCur = r.current_ratio == null ? "good" : level(r.current_ratio, 2, 1);
  const savings = d.month.income ? d.month.net / d.month.income : null;

  return html`
    <div class="head rise">
      <div><h1>${greeting()}，${META.owner || "您好"}</h1>
        <div class="sub">${longDate(d.today)}
          ${d.today_count > 0
            ? html`<span class="nudge good"><${Icon} name="check" />今天已記 ${d.today_count} 筆${d.streak > 1 ? html`・連續記帳 ${d.streak} 天 🔥` : ""}</span>`
            : html`<span class="nudge" onClick=${() => openTxn({ type: "expense" })}><${Icon} name="plus" />今天還沒有記帳，按這裡記一筆</span>`}</div></div>
      <div class="actions">
        <button class="btn t-expense" onClick=${() => openTxn({ type: "expense" })}><${Icon} name="minus" />記支出</button>
        <button class="btn t-income" onClick=${() => openTxn({ type: "income" })}><${Icon} name="plus" />記收入</button>
        <button class="btn t-transfer" onClick=${() => openTxn({ type: "transfer" })}><${Icon} name="transfer" />轉帳</button>
        <button class="btn primary" onClick=${() => go("investments")}><${Icon} name="refresh" />更新市值</button>
      </div>
    </div>
    ${META.demo ? html`<div class="banner rise"><${Icon} name="eye" />這是範例帳本（不會讀取或修改您的帳本），可以放心試用每一項功能。</div>`
      : d.sample && html`<div class="banner rise"><${Icon} name="eye" /><span class="grow">目前顯示的是範例資料，試用完畢後可以一鍵清除，開始記錄您自己的帳。</span>
          <${Btn} kind="primary" onClick=${clearSample}>清除範例資料，開始正式記帳</${Btn}></div>`}

    <div class="kgrid">
      <${HeroCard} d=${d} savings=${savings} prefsKey=${prefsKey} />
      <${StatCard} title="資產總計" icon="bank" color="--primary" value=${d.assets} delay=${60} sub="現金、存款、投資、保單…">
        <${AllocBar} items=${d.allocation} /></${StatCard}>
      <${StatCard} title="負債總計" icon="card" color="--expense" value=${d.liabilities} delay=${110} sub="信用卡、貸款…">
        <${RatioBar} ratio=${r.debt_ratio} /></${StatCard}>
      <${StatCard} title="本月收入" icon="trend_up" color="--income" value=${d.month.income} delay=${160} sub=${"上月 " + money(d.prev_month.income)}
        delta=${html`<${Delta} cur=${d.month.income} prev=${d.prev_month.income} />`}>
        <${MiniBars} months=${d.months} values=${d.monthly.map((x) => x.income)} color="--income" /></${StatCard}>
      <${StatCard} title="本月支出" icon="trend_down" color="--expense" value=${d.month.expense} delay=${210} sub=${"上月 " + money(d.prev_month.expense)}
        delta=${html`<${Delta} cur=${d.month.expense} prev=${d.prev_month.expense} goodWhenUp=${false} />`}>
        <${MiniBars} months=${d.months} values=${d.monthly.map((x) => x.expense)} color="--expense" /></${StatCard}>
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

    <div class="grid insights-row">
      <${Insights} items=${d.insights} go=${go} />
      <${Ranking} rows=${d.ranking} />
    </div>

    ${d.reminders.length > 0 && html`<div class="card remind rise" style="animation-delay:300ms">
      <h3><${Icon} name="bell" />提醒事項</h3>
      ${d.reminders.map((x) => x.kind === "due" || x.kind === "backup"
        ? html`<div class="ritem"><span class="badge-ic"><${Icon} name=${x.kind === "due" ? "bell" : "save"} /></span><div class="txt"><b>${x.text}</b></div>
                 <button class="btn primary" onClick=${() => (x.kind === "due" ? openDue() : backupNow())}>${x.action}</button></div>`
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

    <div class="card rise" style="animation-delay:500ms"><h3><${Icon} name="list" />最近的紀錄<small>按一下可開啟傳票</small><button class="link" onClick=${() => go("transactions")}>全部紀錄 →</button></h3>
      <table class="list"><thead><tr><th>日期</th><th>傳票號碼</th><th>類型</th><th>分類</th><th>帳戶</th><th>說明</th><th class="r">金額</th></tr></thead>
        <tbody>${d.recent.map((t) => html`<tr onClick=${() => openVoucher(t.id)}>
          <td class="num">${ymd(t.date)}</td><td class="muted num">${t.voucher}</td>
          <td><span class=${"type b-" + t.type}>${t.type_label}</span></td><td>${t.type === "income" || t.type === "expense" ? html`<span class="emo">${catEmoji(t.category, t.type)}</span>` : ""}${t.category}</td><td>${t.account}</td>
          <td class="note" title=${t.note}>${t.note}${t.tags.map((g) => html`<span class="tag">#${g}</span>`)}</td>
          <td class=${"r num c-" + t.type}><b>${money(t.amount, t.currency, t.signed)}</b></td></tr>`)}</tbody></table>
    </div>`;
}

