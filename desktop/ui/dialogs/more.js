// 定期交易、到期提醒、銀行對帳、匯入 Excel／CSV、全域搜尋、歡迎畫面。
import { useEffect, useRef, useState } from "preact/hooks";
import { META, api, changed, cur, html, isoToday, money, num, toast, ymd } from "../lib/core.js";
import { AmountInput, Btn, Check, DataTable, DateInput, Dialog, Field, Icon, Segmented, Select, TextInput, TypeBadge, ask,
         errorBox, info, openModal } from "../lib/ui.js";
import { openVoucher } from "./txn.js";
import { openJournal } from "./journal.js";

// ------------------------------------------------------------------ 定期交易
export const openRecurring = () => openModal((close) => html`<${RecurringManager} close=${close} />`);
function RecurringManager({ close }) {
  const [d, setD] = useState(null);
  const [sel, setSel] = useState(new Set());
  const load = () => api("recurring_list").then(setD);
  useEffect(() => { load(); }, []);
  if (!d) return null;
  const cur_ = d.rows.find((r) => sel.has(r.id));
  const edit = async (r) => { if (await openRecurringEdit(r)) load(); };
  async function del() {
    if (!(await ask(`確定要刪除定期交易「${cur_.name}」嗎？\n（已入帳的紀錄不受影響）`, { yes: "刪除", danger: true }))) return;
    await api("recurring_delete", cur_.id); changed(); load();
  }
  async function checkDue() { const due = await api("due_list"); if (!due.length) return info("目前沒有到期的定期交易。"); await openDue(due); load(); }
  const cols = [
    { key: "name", title: "名稱", render: (r) => html`<b>${r.name}</b>`, nowrap: true },
    { key: "type", title: "類型", align: "c", render: (r) => html`<${TypeBadge} type=${r.type} label=${r.type_label} />` },
    { key: "acc", title: "帳戶", render: (r) => r.account, nowrap: true },
    { key: "target", title: "分類／轉入", render: (r) => r.target, nowrap: true },
    { key: "amount", title: "金額", align: "r", render: (r) => html`<span class="num">${num(r.amount)}</span>` },
    { key: "freq", title: "頻率", align: "c", render: (r) => r.freq_label, nowrap: true },
    { key: "next", title: "下次日期", align: "c", render: (r) => html`<span class="num">${r.next ? ymd(r.next) : "—"}</span>` },
    { key: "st", title: "狀態", align: "c", render: (r) => html`<span class=${"type " + (r.active ? "b-income" : "b-void")}>${r.active ? "啟用" : "停用"}</span>` },
  ];
  return html`<${Dialog} title="定期交易" icon="restore" width="66rem" cls="listdlg" onClose=${() => close()}
      footer=${html`<${Btn} kind="primary" icon="plus" onClick=${() => edit(null)}>新增</${Btn}>
        <${Btn} icon="edit" disabled=${!cur_} onClick=${() => edit(cur_)}>編輯</${Btn}>
        <${Btn} icon="eye" disabled=${!cur_} onClick=${async () => { await api("recurring_toggle", cur_.id); changed(); load(); }}>啟用／停用</${Btn}>
        <${Btn} kind="danger" icon="trash" disabled=${!cur_} onClick=${del}>刪除</${Btn}>
        <${Btn} icon="refresh" onClick=${checkDue}>檢查到期項目</${Btn}><div class="grow"></div><${Btn} onClick=${() => close()}>關閉</${Btn}>`}>
    <p class="hint" style="margin-top:0">每月固定的收入或支出（退休金、水電、保費、房租…）可設為定期交易，到期時程式會提醒您一鍵入帳。</p>
    <${DataTable} columns=${cols} rows=${d.rows} selected=${sel} onSelect=${setSel} onActivate=${edit} maxHeight="50vh" empty="還沒有定期交易，按「新增」設定第一筆。" />
  </${Dialog}>`;
}

/** 新增或編輯定期交易；fromTxn：由收支明細的紀錄建立。 */
export async function openRecurringEdit(rec = null, fromTxn = null) {
  const form = await api("txn_form", null);
  const fr = await api("recurring_list");
  return openModal((close) => html`<${RecurringEdit} rec=${rec} from=${fromTxn} form=${form} freqs=${fr.freqs} close=${close} />`);
}
function RecurringEdit({ rec, from, form, freqs, close }) {
  const data = rec ? rec.data : from || {};
  const [name, setName] = useState(rec ? rec.name : data.note || "");
  const [type, setType] = useState(data.type || "expense");
  const [account, setAccount] = useState(data.account_id || form.accounts[0]?.id);
  const [toAccount, setTo] = useState(data.to_account_id || form.accounts[1]?.id);
  const [category, setCategory] = useState(data.category_id || null);
  const [jr, setJr] = useState(from && from.type === "journal" ? { lines: from.lines, note: from.note, tags: from.tags, amount: from.amount } : null);
  useEffect(() => { if (rec && rec.type === "journal") api("recurring_lines", rec.id).then((x) => setJr({ ...x, amount: data.amount })); }, []);
  async function editLines() {
    const r = await openJournal({ draft: true, prefill: jr ? jr.lines : [], note: jr ? jr.note : name, tags: jr ? jr.tags : [] });
    if (r && r.lines) { setJr(r); if (!name.trim()) setName(r.note); }
  }
  const [amount, setAmount] = useState(data.amount || null);
  const [note, setNote] = useState(data.note || "");
  const [freq, setFreq] = useState(rec ? rec.freq : "monthly");
  const [day, setDay] = useState(rec ? rec.day : +((data.date || isoToday()).slice(8)));
  // 由現有的傳票設定時，從明天起算：這一張已經記了，不要再提醒一次
  const [start, setStart] = useState(rec ? rec.start_date : from ? isoToday(1) : isoToday());
  const [hasEnd, setHasEnd] = useState(!!(rec && rec.end_date));
  const [end, setEnd] = useState(rec && rec.end_date ? rec.end_date : isoToday(365));
  const [active, setActive] = useState(rec ? !!rec.active : true);
  const [msg, setMsg] = useState("");
  const cats = form.categories[type] || [];
  async function save() {
    setMsg("");
    try {
      const n = await api("recurring_save", rec ? rec.id : null, { name, type, account_id: account, to_account_id: toAccount, category_id: category,
        amount, note: type === "journal" ? (jr ? jr.note : "") : note, lines: jr ? jr.lines : null, tags: jr ? jr.tags : [], freq, day, start_date: start, end_date: hasEnd ? end : "", active });
      changed(); toast(`已儲存定期交易：${n}`); close(true);
    } catch (e) { setMsg(e.message); }
  }
  return html`<${Dialog} title=${rec ? "編輯定期交易" : "新增定期交易"} icon="restore" width="42rem" onClose=${() => close()}
      footer=${html`<div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${save}>儲存</${Btn}>`}>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <${Field} label="名稱"><${TextInput} value=${name} onInput=${setName} placeholder="例如：月退休金、水電費、保險費" autofocus /></${Field}>
      <${Field} label="類型"><${Segmented} value=${type} onChange=${(t) => { setType(t); setCategory(null); }} options=${[["expense", "支出", "minus"], ["income", "收入", "plus"], ["transfer", "轉帳", "transfer"], ["journal", "複式分錄", "book"]]} /></${Field}>
      ${type === "journal" ? html`<${Field} label="分錄內容"><div class="row wrap">${jr ? html`<span>${jr.lines.filter((l) => l.key).length} 行，借貸各 <b class="num">${num(jr.amount)}</b>${jr.note ? `，摘要：${jr.note}` : ""}</span>` : html`<span class="muted">還沒有輸入</span>`}
          <${Btn} icon="edit" onClick=${editLines}>${jr ? "修改內容…" : "輸入分錄…"}</${Btn}></div></${Field}>` : html`
      <${Field} label=${type === "transfer" ? "轉出帳戶" : "帳戶"}><${Select} value=${account} onChange=${setAccount} options=${form.accounts.map((a) => [a.id, a.name])} /></${Field}>
      ${type === "transfer" ? html`<${Field} label="轉入帳戶"><${Select} value=${toAccount} onChange=${setTo} options=${form.accounts.map((a) => [a.id, a.name])} /></${Field}>`
        : html`<${Field} label="分類"><${Select} value=${category} onChange=${setCategory} options=${[[null, "（請選擇）"], ...cats.map((c) => [c.id, c.name])]} /></${Field}>`}
      <${Field} label="金額"><${AmountInput} value=${amount} onChange=${setAmount} /></${Field}>
      <${Field} label="說明"><${TextInput} value=${note} onInput=${setNote} placeholder="入帳時的說明（可留空，預設為名稱）" /></${Field}>`}
      <${Field} label="頻率"><div class="row"><${Select} value=${freq} onChange=${setFreq} options=${freqs} />
        <div style="width:6rem"><${AmountInput} value=${day} onChange=${(v) => setDay(Math.max(1, Math.min(31, Math.round(v || 1))))} decimals=${0} suffix="日" /></div></div></${Field}>
      <${Field} label="開始日期"><${DateInput} value=${start} onChange=${setStart} /></${Field}>
      <${Field} label="結束"><div class="row wrap"><${Check} checked=${hasEnd} onChange=${setHasEnd}>設定結束日期</${Check}>${hasEnd && html`<${DateInput} value=${end} onChange=${setEnd} />`}</div></${Field}>
      <${Field} label="狀態"><${Check} checked=${active} onChange=${setActive}>啟用</${Check}></${Field}>
      <div class="hint">到期時程式會提醒您確認入帳（金額可在入帳前修改），不會自動記帳。每季、每年依開始日期的月份推算。</div>
      ${msg && html`<div class="msg bad"><${Icon} name="alert" />${msg}</div>`}
    </form>
  </${Dialog}>`;
}

/** 到期提醒：勾選要入帳的項目（金額可修改），或略過本期。 */
export async function openDue(due = null) {
  due = due || (await api("due_list"));
  if (!due.length) return false;
  return openModal((close) => html`<${DueDialog} due=${due} close=${close} />`);
}
function DueDialog({ due, close }) {
  const [rows, setRows] = useState(due.map((d, i) => ({ ...d, i, on: true })));
  const set = (i, p) => setRows(rows.map((r) => (r.i === i ? { ...r, ...p } : r)));
  // 定期分錄：開啟分錄視窗修改後入帳，入帳後從清單移除
  async function editPost(r) {
    try {
      const p = await api("recurring_lines", r.rec_id);
      if (await openJournal({ prefill: p.lines, note: p.note, tags: p.tags, date: r.date, recurring: { rec_id: r.rec_id, date: r.date } })) {
        const left = rows.filter((x) => x.i !== r.i);
        left.length ? setRows(left) : close(true);
      }
    } catch (e) { errorBox(e.message); }
  }
  async function go(skip) {
    const items = rows.filter((r) => r.on).map((r) => ({ rec_id: r.rec_id, date: r.date, amount: r.amount }));
    const res = await api("due_post", items, skip);
    changed();
    if (res.errors.length) await errorBox("以下項目無法入帳：\n" + res.errors.join("\n"));
    toast(skip ? `已略過 ${res.n} 筆（本期不入帳）` : `已入帳 ${res.n} 筆定期交易（Ctrl+Z 可復原）`);
    close(true);
  }
  return html`<${Dialog} title="定期交易到期提醒" icon="bell" accent="var(--gold)" width="54rem" cls="listdlg" onClose=${() => close()}
      footer=${html`<${Btn} onClick=${() => close()}>稍後再說</${Btn}><div class="grow"></div>
        <${Btn} onClick=${() => go(true)}>略過所選（本期不入帳）</${Btn}><${Btn} kind="primary" icon="check" onClick=${() => go(false)}>入帳所選</${Btn}>`}>
    <p><b>有 ${due.length} 筆定期交易已到期，請確認是否入帳：</b></p>
    <p class="hint">金額若與實際不同（例如水電費），可直接修改後再入帳。</p>
    <div class="tablewrap"><table class="list edit sticky"><thead><tr><th class="c">入帳</th><th>日期</th><th>名稱</th><th class="c">類型</th><th class="r" style="width:12rem">金額</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td class="c"><${Check} checked=${r.on} onChange=${(v) => set(r.i, { on: v })} /></td>
        <td class="num">${ymd(r.date)}</td><td><b>${r.name}</b></td><td class="c"><${TypeBadge} type=${r.type} label=${r.type_label} /></td>
        <td>${r.type === "journal" ? html`<div class="row nowrap"><span class="grow r num">${num(r.amount)}</span><${Btn} icon="edit" onClick=${() => editPost(r)} title="開啟分錄，修改後入帳">修改</${Btn}></div>`
          : html`<${AmountInput} value=${r.amount} onChange=${(v) => set(r.i, { amount: v })} />`}</td></tr>`)}</tbody></table></div>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 銀行對帳
export const openReconcile = (aid = null) => openModal((close) => html`<${Reconcile} aid0=${aid} close=${close} />`);
function Reconcile({ aid0, close }) {
  const [aid, setAid] = useState(aid0);
  const [date, setDate] = useState(isoToday());
  const [d, setD] = useState(null);
  const [bal, setBal] = useState(null);
  const [checked, setChecked] = useState(new Set());
  const [hist, setHist] = useState(false);
  const [smart, setSmart] = useState(null);
  useEffect(() => { api("recon_load", aid, date).then((x) => { setD(x); if (!aid) setAid(x.account); setBal(x.book); setChecked(new Set()); setSmart(null); }); }, [aid, date]);
  if (!d) return null;
  if (!d.account) return html`<${Dialog} title="銀行對帳" icon="list" onClose=${() => close()}><p>請先新增帳戶。</p></${Dialog}>`;
  const c = d.currency;
  const s = d.items.filter((i) => checked.has(i.txn_id)).reduce((a, i) => a + i.effect, 0);
  const after = d.cleared + s, diff = Math.round(((bal || 0) - after) * 100) / 100, ok = Math.abs(diff) < 0.005;
  async function finish() {
    if (!ok && !(await ask(`仍有差額 ${money(diff, c)}，可能有漏記或金額不符。\n確定仍要儲存這次對帳嗎？`, { yes: "仍要儲存" }))) return;
    await api("recon_save", aid, date, bal, [...checked]);
    changed(); toast(`「${d.name}」對帳完成，核銷 ${checked.size} 筆`); close(true);
  }
  const toggle = (id) => { const n = new Set(checked); n.has(id) ? n.delete(id) : n.add(id); setChecked(n); };
  // 智慧對帳：讀取網路銀行下載的明細，金額相同、日期差 3 天內的自動勾選
  async function smartMatch() {
    const [p] = await api("pick_files", "選擇銀行下載的交易明細（Excel 或 CSV）", "import");
    if (!p) return;
    try {
      const r = await api("recon_match", aid, date, p);
      setChecked(new Set([...checked, ...r.matched]));
      r.balance_used = r.last_balance != null && r.last_date <= date;
      if (r.balance_used) setBal(r.last_balance);
      setSmart(r);
      setTimeout(() => document.querySelector("table.recon tr.auto")?.scrollIntoView({ block: "center" }), 80);   // 捲到自動勾選的紀錄
    } catch (e) { errorBox(e.message); }
  }
  return html`<${Dialog} title="銀行對帳" icon="list" width="64rem" cls="listdlg" onClose=${() => close()}
      footer=${html`<${Btn} icon="list" onClick=${() => setHist(!hist)}>${hist ? "回到對帳" : "對帳紀錄"}</${Btn}>
        ${!hist && html`<${Btn} icon="upload" onClick=${smartMatch} title="選擇網路銀行下載的交易明細，自動勾選帳上對應的紀錄">匯入銀行明細自動勾選</${Btn}>`}<div class="grow"></div>
        <${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="check" onClick=${finish}>完成對帳</${Btn}>`}>
    <p class="hint" style="margin-top:0">拿出銀行存摺或對帳單，輸入對帳單日期與期末餘額，再勾選存摺上已出現的每一筆紀錄。差額為 0 即對帳完成；未勾選的就是「未達帳項」。</p>
    <div class="form two-fields">
      <${Field} label="帳戶"><${Select} value=${aid} onChange=${setAid} options=${d.accounts.map((a) => [a.id, a.name])} /></${Field}>
      <${Field} label="對帳單日期"><${DateInput} value=${date} onChange=${setDate} /></${Field}>
      <${Field} label="期末餘額"><${AmountInput} value=${bal} onChange=${setBal} code=${c} suffix=${cur(c).name} /></${Field}>
    </div>
    ${hist ? html`<${DataTable} rows=${d.history} maxHeight="45vh" empty="還沒有對帳紀錄"
        columns=${[{ key: "d", title: "對帳單日期", render: (r) => ymd(r.statement_date) }, { key: "b", title: "對帳單餘額", align: "r", render: (r) => num(r.statement_balance, c) },
                   { key: "n", title: "核銷筆數", align: "r", render: (r) => r.n }, { key: "t", title: "對帳時間", render: (r) => r.created_at.replace("T", " ") }]} />`
      : html`${smart && html`<div class="smart"><span class="s-ic"><${Icon} name="check" /></span><div class="grow">
          <b>已依銀行明細自動勾選 ${smart.matched.length} 筆</b><span class="muted">（明細共 ${smart.rows} 筆${smart.later ? `，其中 ${smart.later} 筆在對帳單日期之後` : ""}${smart.balance_used ? `；期末餘額已帶入 ${money(smart.last_balance, c)}` : ""}）</span>
          ${smart.bank_only.length > 0 && html`<div class="s-miss">銀行明細有 ${smart.bank_only.length} 筆在帳上找不到（可能漏記，例如手續費、利息）：
            ${smart.bank_only.slice(0, 6).map((b) => html`<span>${ymd(b.date)} ${b.note || ""} <b class=${b.amount < 0 ? "c-expense" : "c-income"}>${money(b.amount, c, true)}</b></span>`)}${smart.bank_only.length > 6 ? "…" : ""}</div>`}
        </div><button class="x" title="關閉" onClick=${() => setSmart(null)}><${Icon} name="close" /></button></div>`}
      <div class="tablewrap" style="max-height:45vh;margin-top:.6rem"><table class="list sticky recon"><thead><tr><th class="c">✓</th><th>日期</th><th class="c">傳票號碼</th><th>摘要</th><th class="r">增加（存入）</th><th class="r">減少（提出）</th></tr></thead>
        <tbody>${d.items.map((i) => html`<tr class=${(checked.has(i.txn_id) ? "sel" : "") + (smart && smart.matched.includes(i.txn_id) ? " auto" : "")} onClick=${() => toggle(i.txn_id)}>
          <td class="c"><${Check} checked=${checked.has(i.txn_id)} onChange=${() => toggle(i.txn_id)} /></td><td class="num">${ymd(i.date)}</td>
          <td class="c muted num">${i.voucher}</td><td>${i.note}</td><td class="r num c-income">${i.effect > 0 ? num(i.effect, c) : ""}</td>
          <td class="r num c-expense">${i.effect < 0 ? num(-i.effect, c) : ""}</td></tr>`)}</tbody></table>
        ${!d.items.length && html`<div class="empty">沒有未核銷的紀錄</div>`}</div>
      <div class="row wrap" style="margin-top:.6rem"><${Btn} kind="link" onClick=${() => setChecked(new Set(d.items.map((i) => i.txn_id)))}>全部勾選</${Btn}>
        <${Btn} kind="link" onClick=${() => setChecked(new Set())}>全部取消</${Btn}><div class="grow"></div>
        <b class=${ok ? "c-income" : "c-expense"}>上次對帳餘額 ${money(d.cleared, c)} ＋ 勾選 ${money(s, c)} ＝ ${money(after, c)}　｜　差額 ${money(diff, c)}${ok ? "　✓" : ""}</b></div>`}
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 匯入
export const openImport = () => openModal((close) => html`<${ImportDialog} close=${close} />`);
function ImportDialog({ close }) {
  const [file, setFile] = useState(null);
  const [map, setMap] = useState({});
  const [acc, setAcc] = useState(null);
  const [sign, setSign] = useState("expense_positive");
  const [createCat, setCreateCat] = useState(true);
  const [pv, setPv] = useState(null);
  useEffect(() => { if (file) api("import_preview", map, acc, sign, createCat).then(setPv).catch((e) => errorBox(e.message)); }, [file, JSON.stringify(map), acc, sign, createCat]);
  async function pick() {
    const [p] = await api("pick_files", "選擇要匯入的檔案", "import");
    if (!p) return;
    try { const f = await api("import_read", p); setFile(f); setMap(f.mapping); setAcc(f.accounts[0]?.id ?? null); } catch (e) { errorBox(e.message); }
  }
  async function run() {
    if (!(await ask(`確定要匯入 ${pv.ok} 筆紀錄嗎？\n匯入前會自動備份帳本。`, { yes: "匯入" }))) return;
    try {
      const r = await api("import_run"); changed(); toast(`匯入完成：${r.n} 筆（Ctrl+Z 可復原）`);
      await info(`匯入完成！成功 ${r.n} 筆，略過 ${r.skipped} 筆。\n如需復原，可按 Ctrl+Z，或從「自動備份」資料夾的「匯入前備份」還原。`); close(true);
    } catch (e) { errorBox(e.message); }
  }
  return html`<${Dialog} title="匯入 Excel／CSV" icon="upload" width="72rem" onClose=${() => close()}
      footer=${html`${pv && html`<b>共 ${pv.total} 筆：可匯入 ${pv.ok} 筆，無法匯入 ${pv.total - pv.ok} 筆${pv.total > 500 ? "（只顯示前 500 筆）" : ""}</b>`}
        <div class="grow"></div><${Btn} onClick=${() => close()}>取消</${Btn}><${Btn} kind="primary" icon="upload" disabled=${!pv || !pv.ok} onClick=${run}>開始匯入</${Btn}>`}>
    <div class="row wrap"><${Btn} kind="primary" icon="folder" onClick=${pick}>選擇檔案…</${Btn}><${Btn} icon="excel" onClick=${() => api("import_template")}>下載匯入範本</${Btn}>
      <span class="muted">${file ? `${file.name}（標題列：第 ${file.header + 1} 列）` : "尚未選擇檔案（支援 .xlsx 與 .csv，也可以直接匯入本程式匯出的報表）"}</span></div>
    ${file && html`<div class="section-title sm" style="margin-top:1rem">欄位對應</div>
      <div class="mapgrid">${file.fields.map(([k, label]) => html`<label><span class="lbl">${label}</span>
        <${Select} value=${map[k] ?? null} onChange=${(v) => setMap({ ...map, [k]: v })} options=${[[null, "（不使用）"], ...file.columns.map((c, i) => [i, c])]} /></label>`)}</div>
      <div class="row wrap" style="margin:.8rem 0"><span class="lbl">帳戶欄空白時使用</span><${Select} value=${acc} onChange=${setAcc} options=${file.accounts.map((a) => [a.id, a.name])} />
        <span class="lbl">只有一個金額欄時</span><${Select} value=${sign} onChange=${setSign} options=${[["expense_positive", "正數為支出、負數為收入"], ["income_positive", "正數為收入、負數為支出"]]} />
        <${Check} checked=${createCat} onChange=${setCreateCat}>找不到的分類自動新增</${Check}></div>
      ${pv && html`<${DataTable} rows=${pv.rows} rowKey=${(r) => r.row} maxHeight="38vh"
        columns=${[{ key: "row", title: "列", align: "r", render: (r) => r.row },
                   { key: "st", title: "狀態", render: (r) => html`<span class=${r.error ? "c-expense" : r.new_category ? "c-adjust" : "c-income"}>${r.error || (r.new_category ? "新分類" : "可匯入")}</span>`, nowrap: true },
                   { key: "date", title: "日期", render: (r) => ymd(r.date), nowrap: true }, { key: "type", title: "類型", align: "c", render: (r) => r.type },
                   { key: "cat", title: "分類", render: (r) => r.category }, { key: "acc", title: "帳戶", render: (r) => r.account },
                   { key: "note", title: "說明", elide: true, render: (r) => r.note }, { key: "amt", title: "金額", align: "r", render: (r) => html`<span class="num">${num(r.amount)}</span>` }]} />`}`}
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 全域搜尋
let lastSearch = "";
export const openSearch = (go) => openModal((close) => html`<${SearchDialog} go=${go} close=${close} />`);
function SearchDialog({ go, close }) {
  const [text, setText] = useState(lastSearch);
  const [res, setRes] = useState(null);
  const [sel, setSel] = useState(new Set());
  useEffect(() => {
    lastSearch = text;
    const t = setTimeout(() => (text.trim() ? api("search", text).then(setRes) : setRes(null)), 250);
    return () => clearTimeout(t);
  }, [text]);
  function open(r) {
    if (r.kind === "voucher") return openVoucher(r.id);
    if (r.kind === "special") return setText(r.title);
    close();
    if (r.kind === "account") { window.__pendingReport = { tab: "ledger", account: r.id }; go("reports"); }
    else if (r.kind === "category") window.__showTransactions({ category: r.id, period: "全部" });
    else if (r.kind === "security") window.__showSecurity(r.id);
    else if (r.kind === "recurring") api("recurring_list").then((d) => { const rec = d.rows.find((x) => x.id === r.id); rec ? openRecurringEdit(rec) : info("找不到這筆定期交易，可能已被刪除。"); });
  }
  const cols = [
    { key: "g", title: "類別", align: "c", render: (r) => html`<span class=${"type " + ({ 科目: "b-journal", 投資標的: "b-gold", 定期交易: "b-adjust" }[r.group] || (r.void ? "b-void" : "b-transfer"))}>${r.group}</span>` },
    { key: "date", title: "日期", render: (r) => html`<span class="num">${ymd(r.date)}</span>`, nowrap: true },
    { key: "ref", title: "號碼／代號", render: (r) => html`<span class="muted num">${r.ref}</span>`, nowrap: true },
    { key: "title", title: "名稱／摘要", render: (r) => html`<b class=${r.void ? "muted" : ""}>${r.title}</b>`, elide: true },
    { key: "detail", title: "內容", render: (r) => html`<span class="muted">${r.detail}</span>`, elide: true, cls: () => "grow" },
    { key: "amt", title: "金額", align: "r", render: (r) => (r.amount == null ? "" : html`<span class="num">${money(r.amount, r.currency || META.base)}</span>`) },
  ];
  return html`<${Dialog} title="全域搜尋" icon="search" width="72rem" cls="listdlg" onClose=${() => close()}
      footer=${html`<span class="hint">可輸入多個關鍵字（空白分隔，全部符合才列出）：傳票號碼 V000123、日期 2025-03 或 114/3/5、金額、代號，或說明、科目、標的、附件名稱。按兩下開啟。</span>
        <div class="grow"></div><${Btn} onClick=${() => close()}>關閉</${Btn}>`}>
    <${TextInput} icon="search" value=${text} onInput=${setText} placeholder="搜尋傳票、科目、投資標的、定期交易…" autofocus cls="big-search" />
    ${res && html`<div class="muted small" style="margin:.6rem 0">${res.rows.length ? `找到 ${res.rows.length} 筆` : "沒有符合的結果"}${res.truncated ? `（傳票共 ${res.total} 筆，只顯示前 300 筆，請加上更多關鍵字）` : ""}</div>`}
    ${res && res.rows.length > 0 && html`<${DataTable} columns=${cols} rows=${res.rows} rowKey=${(r) => r.kind + r.id + r.ref} selected=${sel} onSelect=${setSel}
      onActivate=${open} maxHeight="55vh" />`}
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 歡迎畫面
export const openWelcome = () => openModal((close) => html`<${Welcome} close=${close} />`);
function Welcome({ close }) {
  const [name, setName] = useState("游媽媽");
  const finish = async (choice) => { await api("welcome_finish", name, choice); META.owner = name.trim(); changed(); close(choice); };
  return html`<${Dialog} title="歡迎使用我的理財帳本" icon="book" width="40rem" onClose=${() => finish("basic")}>
    <div class="welcome">
      <h2>歡迎使用「我的理財帳本」</h2>
      <p class="muted">清楚掌握每一筆收支與整體資產，隨時匯出 Excel 報表。<br />所有資料都只存放在這台電腦上，安全又安心。</p>
      <${Field} label="怎麼稱呼您？"><${TextInput} value=${name} onInput=${setName} placeholder="例如：游媽媽" /></${Field}>
      <button class="choice primary" onClick=${() => finish("basic")}><${Icon} name="wallet" size="1.6rem" /><div><b>建立基本帳戶，馬上開始記帳</b>
        <span>會先建立「現金」與「銀行存款」兩個帳戶，之後可以再自行新增或修改。</span></div></button>
      <button class="choice" onClick=${() => finish("sample")}><${Icon} name="eye" size="1.6rem" /><div><b>載入範例資料，先試用看看</b>
        <span>試用後，在「總覽」頁最上方按「清除範例資料，開始正式記帳」即可一鍵清除。</span></div></button>
    </div>
  </${Dialog}>`;
}
