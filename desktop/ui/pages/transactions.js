// 收支明細（日記帳）：篩選、表格、合計；按兩下開啟，右鍵選單可複製、迴轉、作廢、加標籤。
import { useEffect, useMemo, useState } from "preact/hooks";
import { META, PERIOD_PRESETS, api, changed, html, money, presetRange, toast, useLoad, ymd } from "../lib/core.js";
import { Btn, Check, DataTable, DateInput, PeriodChips, Tip, Icon, MenuButton, PageHead, Select, TextInput, TypeBadge, ask, errorBox, info,
         openMenu } from "../lib/ui.js";
import { askVoidReason, openAudit, openTxn, openVoucher, pickTag } from "../dialogs/txn.js";
import { catEmoji } from "../lib/caticon.js";
import { openJournal } from "../dialogs/journal.js";
import { openImport, openRecurring, openRecurringEdit } from "../dialogs/more.js";
import { openAdjust } from "../dialogs/account.js";
import { openChart } from "../dialogs/chart.js";
import { openExport } from "../dialogs/data.js";

const EMPTY = { period: "本月", start: null, end: null, type: null, account: null, category: null, tag: null, keyword: "", void: false };

// 其他頁面（總覽、帳戶、報表、搜尋）可以帶著篩選條件切換到收支明細
let pendingFilter = null;
export function showTransactions(go, f) { pendingFilter = f; go("transactions"); }

function amountText(r) {
  let t = money(r.amount, r.currency, r.signed);
  if (r.to_amount != null) t += ` → ${money(r.to_amount, r.to_currency)}`;
  return t;
}

export function Transactions({ go }) {
  const [f, setF] = useState(() => {
    const init = { ...EMPTY, ...(pendingFilter || {}) };
    pendingFilter = null;
    return init;
  });
  const [kw, setKw] = useState(f.keyword);
  const [sel, setSel] = useState(new Set());
  const [opts] = useLoad(() => api("txn_filters"));
  const set = (patch) => setF((x) => ({ ...x, ...patch }));
  useEffect(() => { if (window.__t) window.__t.filter = set; }, []);

  // 期間：選預設期間時自動算起訖日；改日期即變成「自訂期間」
  const range = useMemo(() => {
    if (f.period === "自訂期間" || !opts) return [f.start, f.end];
    return presetRange(f.period, opts.range);
  }, [f.period, f.start, f.end, opts]);
  useEffect(() => { const t = setTimeout(() => set({ keyword: kw }), 250); return () => clearTimeout(t); }, [kw]);

  const [data] = useLoad(() => (range[0] ? api("txn_list", { ...f, start: range[0], end: range[1] }) : null),
                         [JSON.stringify(f), range[0], range[1]]);
  const rows = data ? data.rows : [];
  const byId = useMemo(() => new Map(rows.map((r) => [r.id, r])), [rows]);
  const selected = [...sel].map((id) => byId.get(id)).filter(Boolean);

  async function voidSelected(list = selected) {
    const live = list.filter((r) => !r.void);
    if (!live.length) return;
    const sys = live.filter((r) => r.source.startsWith("inv:"));
    if (sys.length) {
      if (sys.length < live.length) return info("「投資」類型的傳票是刪除而不是作廢，請將它們與其他傳票分開選取。");
      const desc = await api("inv_voucher_events", sys.map((r) => r.id));
      if (!(await ask("這是「投資管理」自動產生的傳票。刪除後，產生它的投資交易也會一併刪除，系統會重算之後的成本與分錄：\n\n"
        + desc.join("\n") + "\n\n確定要刪除嗎？", { yes: "刪除", danger: true }))) return;
      try { const n = await api("inv_delete_vouchers", sys.map((r) => r.id)); changed(); toast(`已刪除 ${n} 筆投資交易及其傳票`); }
      catch (e) { errorBox(e.message); }
      return;
    }
    const reason = await askVoidReason(live.length);
    if (reason == null) return;
    try { await api("txn_void", live.map((r) => r.id), reason); } catch (e) { return errorBox(e.message); }
    changed();
    toast(`已作廢 ${live.length} 筆傳票（Ctrl+Z 可復原）`);
  }
  async function unvoid(r) {
    try { toast(`${await api("txn_unvoid", r.id)} 已恢復`); changed(); } catch (e) { errorBox(e.message); }
  }
  async function reverse(r) {
    if (!(await ask(`將以今天日期產生一張與 ${r.voucher} 借貸相反的「迴轉分錄」，原傳票保留不變。\n常用於已結帳期間的更正。確定嗎？`, { yes: "產生迴轉分錄" }))) return;
    try { toast(`已產生迴轉分錄 ${await api("txn_reverse", r.id)}`); changed(); } catch (e) { errorBox(e.message); }
  }
  async function copy(r) {
    try {
      const p = await api("txn_copy", r.id);
      if (p.lines) return openJournal({ prefill: p.lines, note: p.note, tags: p.tags });
      openTxn({ prefill: p });
    } catch (e) { errorBox(e.message); }
  }
  async function tagSelected() {
    const ids = selected.filter((r) => !r.source).map((r) => r.id);
    if (!ids.length) return;
    const tag = await pickTag(ids.length, opts ? opts.tags : []);
    if (!tag) return;
    try {
      const n = await api("tag_add", ids, tag);
      changed();
      toast(n ? `已為 ${n} 筆紀錄加上標籤「${tag}」` : "選取的紀錄都已經有這個標籤");
    } catch (e) { errorBox(e.message); }
  }
  async function untag(tag) {
    const n = await api("tag_remove", selected.map((r) => r.id), tag);
    changed();
    toast(`已從 ${n} 筆紀錄移除標籤「${tag}」`);
  }

  function menu(e, r) {
    const sys = r.source.startsWith("inv:");
    const selTags = [...new Set(selected.flatMap((x) => x.tags))].sort().slice(0, 8);
    openMenu(e, [
      ...(r.void ? [{ label: "取消作廢（恢復這筆）", icon: "restore", run: () => unvoid(r) }]
        : [{ label: "開啟／編輯", icon: "edit", run: () => openVoucher(r.id) },
           !sys && { label: "複製一筆（日期改為今天）", icon: "copy", run: () => copy(r) },
           r.type === "journal" && !r.source && { label: "設為定期分錄…", icon: "restore", run: async () => { try { const p = await api("txn_copy", r.id); openRecurringEdit(null, { ...p, note: (p.note || "").replace(/[（(]?\s*(\d{2,4}\s*年)?\s*\d{1,2}\s*月(份)?\s*[)）]?/g, "").trim() || p.note, type: "journal", lines: p.lines, amount: r.amount, date: r.date }); } catch (e) { errorBox(e.message); } } },
           ["income", "expense", "transfer"].includes(r.type) && !r.source && { label: "設為定期交易…", icon: "restore", run: async () => openRecurringEdit(null, await api("txn_copy", r.id).then((p) => ({ ...p, date: r.date }))) },
           "-",
           !sys && { label: "迴轉（產生反向分錄）", icon: "refresh", run: () => reverse(r) },
           sys ? { label: "刪除（一併刪除投資管理的交易）", icon: "trash", danger: true, run: () => voidSelected() }
               : { label: selected.length > 1 ? `作廢選取的 ${selected.length} 筆` : "作廢", icon: "trash", danger: true, run: () => voidSelected() }]),
      ...(!r.source ? ["-", { label: "加上標籤／專案…", icon: "tag", run: tagSelected },
                       ...selTags.map((t) => ({ label: `移除標籤「${t}」`, icon: "minus", run: () => untag(t) }))] : []),
      "-", { label: "修改紀錄", icon: "eye", run: () => openAudit(r.id) },
    ]);
  }

  const columns = [
    { key: "date", title: "日期", render: (r) => ymd(r.date), sort: (r) => r.date + String(r.id).padStart(9, "0"), nowrap: true, cls: (r) => "num" },
    { key: "voucher", title: "傳票號碼", align: "c", nowrap: true, sort: (r) => r.id,
      render: (r) => html`<span class="muted num">${r.voucher}</span>${r.n_attach > 0 && html`<span title="有附件"><${Icon} name="clip" cls="mini" /></span>`}` },
    { key: "type", title: "類型", align: "c", render: (r) => html`<${TypeBadge} type=${r.void ? "void" : r.source ? "invest" : r.type} label=${r.type_label} />`, sort: (r) => r.type_label },
    { key: "category", title: "分類／科目", sort: (r) => r.category, elide: true, tip: (r) => r.category,
      render: (r) => (r.type === "income" || r.type === "expense" ? html`<span class="emo">${catEmoji(r.category, r.type)}</span>${r.category}` : r.category) },
    { key: "account", title: "帳戶", render: (r) => r.account, sort: (r) => r.account, elide: true },
    { key: "note", title: "說明", elide: true, cls: () => "grow",
      tip: (r) => (r.void ? `〔作廢：${r.void_reason}〕` : "") + r.note + r.tags.map((t) => "　#" + t).join(""),
      render: (r) => html`${r.void && html`<span class="muted">〔作廢：${r.void_reason}〕</span>`}${r.note}${r.tags.map((g) => html`<span class="tag">#${g}</span>`)}` },
    { key: "amount", title: "金額", align: "r", nowrap: true, sort: (r) => r.base,
      render: (r) => html`<b class=${"num c-" + (r.void ? "void" : r.type)}>${amountText(r)}</b>` },
  ];

  const pickPeriod = (p) => set({ period: p, ...(p === "自訂期間" ? { start: range[0], end: range[1] } : {}) });
  const setDate = (i, d) => set({ period: "自訂期間", start: i === 0 ? d : range[0], end: i === 1 ? d : range[1] });

  return html`<div class="page-fill">
    <${PageHead} icon="list" color="var(--primary)" title="收支明細" sub="日記帳：逐筆記錄收入、支出、轉帳與分錄傳票">
      <${Btn} kind="expense" icon="minus" big onClick=${() => openTxn({ type: "expense", accountId: f.account })}>記支出</${Btn}>
      <${Btn} kind="income" icon="plus" big onClick=${() => openTxn({ type: "income", accountId: f.account })}>記收入</${Btn}>
      <${Btn} kind="transfer" icon="transfer" big onClick=${() => openTxn({ type: "transfer", accountId: f.account })}>轉帳</${Btn}>
      <${Btn} kind="primary" icon="book" big onClick=${() => openJournal()} title="多行借貸傳票，可分割到多個科目">複式分錄</${Btn}>
      <${MenuButton} label="更多功能" items=${[
        { label: "復原上一步（Ctrl+Z）", icon: "undo", run: () => window.__undo() },
        { label: "更新餘額／市值", icon: "refresh", run: () => openAdjust() },
        { label: "定期交易（每月固定收支）", icon: "restore", run: openRecurring },
        { label: "匯入 Excel／CSV", icon: "upload", run: openImport },
        { label: "匯出 Excel 報表", icon: "download", run: () => openExport(range[0], range[1]) },
        { label: "修改紀錄（稽核軌跡）", icon: "eye", run: () => openAudit() },
        { label: "會計科目表（新增科目）", icon: "list", run: openChart },
      ]} />
    </${PageHead}>

    <div class="card filters">
      <div class="frow">
        <span class="lbl">期間</span>
        <${PeriodChips} value=${f.period} onChange=${pickPeriod} />
        <span class="drange"><${DateInput} value=${range[0]} onChange=${(d) => setDate(0, d)} /><span>～</span>
        <${DateInput} value=${range[1]} onChange=${(d) => setDate(1, d)} /></span>
        <div class="grow"></div>
        <${Check} checked=${f.void} onChange=${(v) => set({ void: v })}>顯示已作廢</${Check}>
      </div>
      <div class="frow">
        <span class="lbl">篩選</span>
        <${Select} value=${f.type} onChange=${(v) => set({ type: v })}
          options=${[[null, "全部類型"], ...Object.entries(META.type_labels || {})]} />
        <${Select} value=${f.account} onChange=${(v) => set({ account: v })}
          options=${[{ value: null, label: "全部帳戶" }, ...(opts ? opts.accounts.map((a) => ({ value: a.id, label: a.name, group: a.kind === "asset" ? "資產" : "負債" })) : [])]} />
        <${Select} value=${f.category} onChange=${(v) => set({ category: v })}
          options=${[{ value: null, label: "全部分類" }, ...(opts ? opts.categories.map((c) => ({ value: c.id, label: c.name, group: c.kind === "income" ? "收入" : "支出" })) : [])]} />
        ${opts && (opts.tags.length > 0 || f.tag) && html`<${Select} value=${f.tag} onChange=${(v) => set({ tag: v })} title="只顯示有這個標籤／專案的紀錄"
          options=${[[null, "全部標籤"], ...opts.tags.map((t) => [t, "#" + t])]} />`}
        <${TextInput} cls="grow" icon="search" value=${kw} onInput=${setKw} placeholder="搜尋說明、分類、帳戶、標籤…" />
        <${Btn} kind="link" onClick=${() => { setF({ ...EMPTY }); setKw(""); }}>清除篩選</${Btn}>
      </div>
    </div>

    <div class="card table-card">
      <${DataTable} columns=${columns} rows=${rows} selected=${sel} onSelect=${setSel} defaultSort=${["date", true]}
        onActivate=${(r) => (r.void ? menu({ preventDefault() {}, clientX: innerWidth / 2, clientY: innerHeight / 2 }, r) : openVoucher(r.id))}
        onMenu=${menu} onDelete=${() => voidSelected()} rowCls=${(r) => (r.void ? "void" : "")}
        empty=${data ? "這個期間沒有符合條件的紀錄" : "讀取中…"}
        emptyAction=${data && html`<div class="row"><${Btn} kind="expense" icon="minus" onClick=${() => openTxn({ type: "expense" })}>記一筆支出</${Btn}>
          <${Btn} kind="link" onClick=${() => set({ period: "全部" })}>看全部期間</${Btn}></div>`} />
    </div>

    <div class="card foot">
      <div class="frow">
        <span>${data ? html`共 <b>${data.count.toLocaleString()}</b> 筆${data.voided ? `（另有已作廢 ${data.voided} 筆）` : ""}` : ""}</span>
        ${sel.size > 1 && html`<span class="muted">已選取 ${sel.size} 筆</span>`}
        <div class="grow"></div>
        ${data && html`<span class="sum c-income">收入 <b class="num">${money(data.income)}</b></span>
          <span class="sum c-expense">支出 <b class="num">${money(data.expense)}</b></span>
          <span class="sum">結餘 <b class="num">${money(data.income - data.expense)}</b></span>`}
      </div>
      <${Tip}>按兩下即可修改；按右鍵可複製、迴轉、作廢或加標籤；Ctrl／Shift 可多選。作廢的傳票保留在帳上並留有修改紀錄，不會真的刪除。「投資」類型的傳票由投資管理自動產生，作廢即刪除該筆投資交易。</${Tip}>
    </div>
  </div>`;
}
