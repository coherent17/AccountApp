// 記一筆（支出／收入／轉帳／餘額調整）、傳票檢視、作廢原因、修改紀錄、加標籤。
import { useEffect, useMemo, useState } from "preact/hooks";
import { META, TYPE_LABELS, api, changed, cur, html, isoToday, money, num, toast, ymd } from "../lib/core.js";
import { openJournal } from "./journal.js";
import { printVoucher } from "./print.js";
import { flashRow } from "../lib/ui.js";
import { catEmoji } from "../lib/caticon.js";
import { AmountInput, Btn, Chips, DataTable, DateInput, Dialog, Field, Icon, Segmented, Select, TagInput, TextInput,
         ask, errorBox, info, openModal } from "../lib/ui.js";

const ACCENT = { expense: "var(--expense)", income: "var(--income)", transfer: "var(--transfer)", adjust: "var(--adjust)" };
const ICON = { expense: "minus", income: "plus", transfer: "transfer", adjust: "scale" };

/** 開啟記一筆視窗。opts：type、tid（編輯）、prefill（複製）、accountId。儲存後傳回 true。 */
export async function openTxn(opts = {}) {
  let form;
  try { form = await api("txn_form", opts.tid || null); } catch (e) { errorBox(e.message); return false; }
  return openModal((close) => html`<${TxnDialog} form=${form} opts=${opts} close=${close} />`);
}

/** 依傳票類型開啟：一般傳票開編輯視窗，分錄與系統傳票開傳票檢視，已作廢的提示如何恢復。 */
export async function openVoucher(tid) {
  let v;
  try { v = await api("voucher", tid); } catch (e) { errorBox(e.message); return; }
  if (v.void && v.type !== "journal") {
    info(`${v.voucher} 已作廢（原因：${v.void_reason || "未填寫"}）。\n如需恢復，請在收支明細勾選「顯示已作廢」，在這筆按右鍵選「取消作廢」。`);
    return;
  }
  if (v.type === "journal") return openJournal({ tid });
  if (v.source) return openModal((close) => html`<${VoucherView} v=${v} close=${close} />`);
  return openTxn({ tid });
}

function accLabel(a) {
  return `${a.name}　（${a.kind === "liability" ? "欠款 " : ""}${money(a.balance, a.currency)}）`;
}

function TxnDialog({ form, opts, close }) {
  const t = form.txn;
  const editing = !!t;
  const src = t || opts.prefill || {};
  const [type, setType] = useState(src.type || opts.type || "expense");
  const [date, setDate] = useState(src.date || isoToday());
  const [amount, setAmount] = useState(src.amount ?? null);
  const firstAcc = opts.accountId || src.account_id || form.last_account || (form.accounts[0] && form.accounts[0].id);
  const [account, setAccount] = useState(form.accounts.some((a) => a.id === firstAcc) ? firstAcc : form.accounts[0]?.id);
  const [toAccount, setToAccount] = useState(src.to_account_id || null);
  const [toAmount, setToAmount] = useState(src.to_amount ?? null);
  const [category, setCategory] = useState(src.category_id || null);
  const [note, setNote] = useState(src.note || "");
  const [tags, setTags] = useState(src.tags || []);
  const [pending, setPending] = useState([]);
  const [saved, setSaved] = useState(t ? t.attachments : []);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [savedAny, setSavedAny] = useState(false);
  const [amountKey, setAmountKey] = useState(0);

  const accs = useMemo(() => Object.fromEntries(form.accounts.map((a) => [a.id, a])), [form]);
  const acc = accs[account];
  const toChoices = form.accounts.filter((a) => a.id !== account);
  useEffect(() => {
    if (type === "transfer" && (!toAccount || toAccount === account)) setToAccount(toChoices[0]?.id || null);
  }, [type, account]);
  const toAcc = accs[toAccount];
  const c1 = acc ? acc.currency : META.base;
  const fx = type === "transfer" && toAcc && toAcc.currency !== c1;
  const cats = form.categories[type] || [];
  const locked = t && t.locked;

  const label = { expense: "支出金額", income: "收入金額", transfer: "轉出金額", adjust: "調整金額" }[type];
  const accLbl = type === "transfer" ? "轉出帳戶" : type === "income" ? "收入存入" : "帳戶";

  async function save(again) {
    setMsg(null);
    if (amount == null) return setMsg({ bad: true, text: "請輸入金額（可輸入數字或算式）" });
    if ((type === "income" || type === "expense") && !category) return setMsg({ bad: true, text: "請點選一個分類" });
    if (fx && toAmount == null) return setMsg({ bad: true, text: "兩個帳戶幣別不同，請輸入轉入金額" });
    const data = { date, type, account_id: account, amount, note, tags,
                   category_id: category, to_account_id: type === "transfer" ? toAccount : null,
                   to_amount: type === "transfer" ? (fx ? toAmount : amount) : null };
    setBusy(true);
    try {
      const r = await api("txn_save", data, t ? t.id : null, pending.map((p) => p.path));
      flashRow(r.id);
      changed();
      const what = { expense: "支出", income: "收入", transfer: "轉帳" }[type] || "紀錄";
      toast(`已${t ? "更新" : "儲存"}${what} ${r.voucher}：${money(amount, c1)}（Ctrl+Z 可復原）`);
      if (again) {
        setAmount(null); setNote(""); setToAmount(null); setPending([]); setAmountKey((k) => k + 1);
        setSavedAny(true);
        setMsg({ text: "已儲存，可以繼續記下一筆。" });
        const f2 = await api("txn_form", null);
        form.accounts.splice(0, form.accounts.length, ...f2.accounts);
        form.notes = f2.notes; form.tags = f2.tags;
      } else close(true);
    } catch (e) {
      setMsg({ bad: true, text: e.message });
    } finally { setBusy(false); }
  }

  async function voidIt() {
    const reason = await askVoidReason(1);
    if (reason == null) return;
    try { await api("txn_void", [t.id], reason); } catch (e) { return setMsg({ bad: true, text: e.message }); }
    changed();
    toast("已作廢這筆紀錄（Ctrl+Z 可復原）");
    close(true);
  }

  // 快速記帳：點一下常記的項目，帶入類型、分類、帳戶、說明與上次的金額（金額會選取，直接打字就能改）
  function applyQuick(q) {
    setType(q.type); setCategory(q.category_id); setNote(q.note); setAmount(q.amount); setAmountKey((k) => k + 1);
    if (accs[q.account_id]) setAccount(q.account_id);
    setMsg({ text: `已帶入「${q.note}」，確認金額後按儲存。` });
    setTimeout(() => { const el = document.querySelector(".dialog .amount.big input"); if (el) { el.focus(); el.select(); } }, 60);
  }
  // 輸入以前記過的說明（例如「全聯採買」）時，自動帶入上次的分類與帳戶
  function onNote(v) {
    setNote(v);
    const h = form.hints && form.hints[v.trim()];
    if (!h || editing || h.type !== type || category) return;
    setCategory(h.category_id);
    if (accs[h.account_id]) setAccount(h.account_id);
    setMsg({ text: `已依上次「${v.trim()}」帶入分類與帳戶，可以再修改。` });
  }

  async function copyNew() {
    try { const p = await api("txn_copy", t.id); close(savedAny); openTxn({ prefill: p }); } catch (e) { setMsg({ bad: true, text: e.message }); }
  }

  // 把目前輸入的內容帶到複式分錄視窗
  function toJournal() {
    const acc = account ? `account:${account}` : "";
    const cat = category ? `category:${category}` : "";
    const a = amount || null;
    const prefill = type === "expense" ? [{ key: cat, debit: a }, {}, { key: acc, credit: a }]
      : type === "income" ? [{ key: acc, debit: a }, {}, { key: cat, credit: a }]
      : [{ key: toAccount ? `account:${toAccount}` : "", debit: a }, { key: acc, credit: a }];
    close(savedAny);
    openJournal({ prefill: prefill.map((p) => ({ key: "", ...p })), date, note, tags });
  }

  async function addFiles() {
    const paths = await api("pick_files", "選擇附件", "attach");
    if (!paths.length) return;
    if (t) {
      try { setSaved(await api("attach_add", t.id, paths)); changed(); } catch (e) { setMsg({ bad: true, text: e.message }); }
    } else setPending([...pending, ...paths.map((p) => ({ path: p, name: p.split(/[\\/]/).pop() }))]);
  }
  async function removeSaved(a) {
    if (!(await ask(`移除附件「${a.name}」？\n（檔案仍保留在「憑證附件」資料夾）`, { yes: "移除", danger: true }))) return;
    setSaved(await api("attach_remove", t.id, a.id));
    changed();
  }

  const title = t ? `編輯紀錄　${t.voucher}` : opts.prefill ? "複製一筆" : "記一筆";
  const footer = html`
    ${t && html`<${Btn} kind="danger" icon="trash" onClick=${voidIt} disabled=${locked}>作廢這筆</${Btn}>
      <${Btn} kind="link" icon="print" onClick=${() => printVoucher(t.id)}>列印傳票</${Btn}>
      <${Btn} kind="link" onClick=${() => openAudit(t.id)}>修改紀錄</${Btn}>
      ${!t.system && html`<${Btn} kind="link" icon="copy" onClick=${copyNew} title="以相同內容再記一筆，日期為今天">複製成新的一筆</${Btn}>`}`}
    ${!t && type !== "adjust" && html`<${Btn} kind="link" icon="split" onClick=${toJournal} title="一筆付款分攤到多個分類，或需要自行輸入借貸時使用">改用複式分錄（分割多個科目）</${Btn}>`}
    <div class="grow"></div>
    <${Btn} onClick=${() => close(savedAny)}>取消</${Btn}>
    ${!t && html`<${Btn} onClick=${() => save(true)} disabled=${busy}>儲存並再記一筆</${Btn}>`}
    <${Btn} kind="primary" icon="check" onClick=${() => save(false)} disabled=${busy || locked}>儲存</${Btn}>`;

  return html`<${Dialog} title=${title} icon=${ICON[type]} accent=${ACCENT[type]} width="44rem" onClose=${() => close(savedAny)} footer=${footer}>
    <form class="form" onSubmit=${(e) => { e.preventDefault(); save(false); }}>
      ${!editing && !opts.prefill && type !== "adjust" && form.quick && form.quick.length > 0 && html`<div class="quick">
          <span class="quick-lbl"><${Icon} name="restore" />常記</span>
          ${form.quick.map((q) => html`<button type="button" class=${"qchip k-" + q.type} onClick=${() => applyQuick(q)}
              title=${`${q.category}・${money(q.amount, c1)}（近半年記了 ${q.count} 次）`}>
            <span class="emo">${catEmoji(q.category, q.type)}</span>${q.note}<small class="num">${money(q.amount, c1)}</small></button>`)}</div>`}
      ${type === "adjust"
        ? html`<div class="section-title" style="color:var(--adjust)">餘額／市值調整</div>`
        : html`<${Segmented} cls="types" value=${type} onChange=${(k) => { setType(k); if (k !== type) setCategory(null); }}
            options=${[["expense", "支出", "minus", "expense"], ["income", "收入", "plus", "income"], ["transfer", "轉帳", "transfer", "transfer"]]} />`}
      ${locked && html`<div class="note warn"><${Icon} name="lock" />這筆傳票在已結帳的期間（${ymd(form.closed_until)} 以前），只能檢視。如需更正，請在收支明細按右鍵「迴轉」。</div>`}
      <${Field} label="日期"><div class="row"><${DateInput} value=${date} onChange=${setDate} />
        <${Btn} kind="link" onClick=${() => setDate(isoToday())}>今天</${Btn}><${Btn} kind="link" onClick=${() => setDate(isoToday(-1))}>昨天</${Btn}></div></${Field}>
      <${Field} label=${label}><${AmountInput} key=${amountKey} value=${amount} onChange=${setAmount} code=${c1} big autofocus
          allowNegative=${type === "adjust"} suffix=${cur(c1).name} /></${Field}>
      ${form.accounts.length === 0
        ? html`<div class="note warn">還沒有任何帳戶。請先到「帳戶管理」新增帳戶（例如現金、銀行存款）。</div>`
        : html`<${Field} label=${accLbl}><${Select} value=${account} onChange=${setAccount}
            options=${form.accounts.map((a) => ({ value: a.id, label: accLabel(a), group: a.kind === "asset" ? "資產" : "負債" }))} /></${Field}>`}
      ${type === "transfer" && html`<${Field} label="轉入帳戶"><${Select} value=${toAccount} onChange=${setToAccount}
          options=${toChoices.map((a) => ({ value: a.id, label: accLabel(a), group: a.kind === "asset" ? "資產" : "負債" }))} /></${Field}>`}
      ${fx && html`<${Field} label="轉入金額" hint=${amount && toAcc.rate ? `依目前匯率約 ${num(amount * acc.rate / toAcc.rate, toAcc.currency)}` : ""}>
          <${AmountInput} value=${toAmount} onChange=${setToAmount} code=${toAcc.currency} suffix=${cur(toAcc.currency).name} /></${Field}>`}
      ${(type === "income" || type === "expense") && html`<${Field} label="分類" top>
          ${cats.length ? html`<${Chips} items=${cats} value=${category} onChange=${setCategory} kind=${type} />`
            : html`<div class="muted">還沒有${type === "income" ? "收入" : "支出"}分類，請到「設定 → 收支分類」新增。</div>`}</${Field}>`}
      <${Field} label="說明"><${TextInput} value=${note} onInput=${onNote} suggestions=${form.notes} placeholder="例如：市場買菜、全聯採買（可留空）" /></${Field}>
      ${!(t && t.system) && html`<${Field} label="標籤" hint="把跨分類的紀錄歸在一起統計，例如一趟旅行；到「財務報表 → 標籤／專案」看合計。">
          <${TagInput} value=${tags} onChange=${setTags} suggestions=${form.tags} /></${Field}>`}
      <${Field} label="附件" top>
        <div class="attach">
          ${saved.map((a) => html`<div class="file"><${Icon} name="clip" /><a onClick=${() => api("open_path", a.path).catch((e) => errorBox(e.message))}>${a.name}</a>
            ${!a.exists && html`<span class="muted">（找不到檔案）</span>`}
            <button type="button" class="x" title="移除" onClick=${() => removeSaved(a)}><${Icon} name="close" /></button></div>`)}
          ${pending.map((p) => html`<div class="file pending"><${Icon} name="plus" />${p.name}<span class="muted">（儲存後加入）</span>
            <button type="button" class="x" title="移除" onClick=${() => setPending(pending.filter((x) => x !== p))}><${Icon} name="close" /></button></div>`)}
          <${Btn} kind="ghost" icon="clip" onClick=${addFiles}>新增附件</${Btn}>
          ${!saved.length && !pending.length && html`<span class="muted small">可附上收據、帳單照片或 PDF（選填）</span>`}
        </div></${Field}>
      ${type === "adjust" && html`<div class="hint">正數代表增加（例如股票上漲），負數代表減少（例如股票下跌）。</div>`}
      ${msg && html`<div class=${"msg " + (msg.bad ? "bad" : "ok")}><${Icon} name=${msg.bad ? "alert" : "check"} />${msg.text}</div>`}
      <button type="submit" hidden></button>
    </form>
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 傳票檢視（分錄、系統傳票）
function VoucherView({ v, close }) {
  const dr = v.lines.reduce((s, l) => s + l.debit, 0), cr = v.lines.reduce((s, l) => s + l.credit, 0);
  const system = v.source.startsWith("inv:");
  async function del() {
    const desc = await api("inv_voucher_events", [v.id]);
    if (!(await ask("這是「投資管理」自動產生的傳票。刪除後，產生它的投資交易也會一併刪除，系統會重算之後的成本與分錄：\n\n"
      + desc.join("\n") + "\n\n確定要刪除嗎？", { yes: "刪除", danger: true }))) return;
    try { const n = await api("inv_delete_vouchers", [v.id]); changed(); toast(`已刪除 ${n} 筆投資交易及其傳票`); close(true); }
    catch (e) { errorBox(e.message); }
  }
  return html`<${Dialog} title=${`傳票　${v.voucher}`} icon="book" width="52rem" onClose=${() => close()}
      footer=${html`${system && !v.void ? html`<${Btn} kind="danger" icon="trash" onClick=${del}>刪除（一併刪除投資交易）</${Btn}>` : null}
        <${Btn} kind="link" onClick=${() => openAudit(v.id)}>修改紀錄</${Btn}><div class="grow"></div>
        <${Btn} kind="primary" onClick=${() => close()}>關閉</${Btn}>`}>
    <div class="vhead">
      <div><label>日期</label><b>${ymd(v.date)}</b></div>
      <div><label>類型</label><b>${system ? "投資（系統產生）" : v.source.startsWith("close:") ? "年度結帳" : v.type_label}</b></div>
      <div class="grow"><label>摘要</label><b>${v.note || "—"}</b></div>
    </div>
    ${!!v.void && html`<div class="note bad"><${Icon} name="alert" />已作廢：${v.void_reason || "未填寫原因"}</div>`}
    ${system && html`<div class="note"><${Icon} name="info" />這張傳票由「投資管理」自動產生，內容由投資交易計算，不能直接修改。</div>`}
    <table class="list voucher">
      <thead><tr><th>科目代號</th><th>會計科目</th><th>摘要</th><th class="r">借方</th><th class="r">貸方</th></tr></thead>
      <tbody>${v.lines.map((l) => html`<tr><td class="num muted">${l.code}</td><td>${l.name}<span class="muted small">（${l.group}）</span></td>
        <td class="muted">${l.memo}${l.security && html`<span class="tag">${l.security}${l.shares ? ` ${num(l.shares, null, false, 0)} 股` : ""}</span>`}</td>
        <td class="r num">${l.debit ? num(l.debit) : ""}</td><td class="r num">${l.credit ? num(l.credit) : ""}</td></tr>`)}</tbody>
      <tfoot><tr><td></td><td><b>合計</b></td><td></td><td class="r num"><b>${num(dr)}</b></td><td class="r num"><b>${num(cr)}</b></td></tr></tfoot>
    </table>
    ${v.tags.length > 0 && html`<div class="row" style="margin-top:.6rem">${v.tags.map((g) => html`<span class="tag">#${g}</span>`)}</div>`}
    ${v.attachments.length > 0 && html`<div class="attach" style="margin-top:.6rem">${v.attachments.map((a) => html`<div class="file"><${Icon} name="clip" />
      <a onClick=${() => api("open_path", a.path).catch((e) => errorBox(e.message))}>${a.name}</a></div>`)}</div>`}
  </${Dialog}>`;
}

// ------------------------------------------------------------------ 作廢原因
const REASONS = ["輸入錯誤", "重複輸入", "交易取消", "金額錯誤，將重新輸入", "其他"];
export const askVoidReason = (count = 1) => openModal((close) => html`<${VoidDlg} count=${count} close=${close} />`);
function VoidDlg({ count, close }) {
      const [r, setR] = useState(REASONS[0]);
      return html`<${Dialog} title="作廢傳票" icon="trash" accent="var(--expense)" width="32rem" onClose=${() => close(null)}
          footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}>
            <${Btn} kind="danger-solid" icon="trash" onClick=${() => close(r.trim() || "作廢")}>作廢</${Btn}>`}>
        <p><b>確定要作廢${count === 1 ? "這" : ` 這 ${count} `}張傳票嗎？</b></p>
        <div class="hint">作廢後不再計入任何帳戶與報表，但會保留在帳上並留下修改紀錄，可隨時「取消作廢」。</div>
        <${Field} label="作廢原因"><${TextInput} value=${r} onInput=${setR} suggestions=${REASONS} /></${Field}>
        <div class="row wrap">${REASONS.map((x) => html`<button type="button" class=${"pillbtn" + (x === r ? " on" : "")} onClick=${() => setR(x)}>${x}</button>`)}</div>
      </${Dialog}>`;
}

// ------------------------------------------------------------------ 加標籤
export const pickTag = (count, suggestions) => openModal((close) => html`<${TagDlg} count=${count} suggestions=${suggestions} close=${close} />`);
function TagDlg({ count, suggestions, close }) {
      const [tag, setTag] = useState("");
      return html`<${Dialog} title="加上標籤／專案" icon="tag" width="32rem" onClose=${() => close(null)}
          footer=${html`<div class="grow"></div><${Btn} onClick=${() => close(null)}>取消</${Btn}>
            <${Btn} kind="primary" icon="tag" disabled=${!tag.trim()} onClick=${() => close(tag.trim())}>加上標籤</${Btn}>`}>
        <p>為選取的 <b>${count}</b> 筆紀錄加上同一個標籤（原有的標籤保留）。</p>
        <form onSubmit=${(e) => { e.preventDefault(); tag.trim() && close(tag.trim()); }}>
          <${Field} label="標籤"><${TextInput} value=${tag} onInput=${setTag} suggestions=${suggestions} placeholder="例如：日本旅遊" autofocus /></${Field}></form>
        ${suggestions.length > 0 && html`<div class="row wrap">${suggestions.slice(0, 12).map((x) => html`<button type="button" class=${"pillbtn" + (x === tag ? " on" : "")} onClick=${() => setTag(x)}>#${x}</button>`)}</div>`}
      </${Dialog}>`;
}

// ------------------------------------------------------------------ 修改紀錄
const ACTION_CLS = { 作廢: "b-expense", 刪除: "b-expense", 修改: "b-adjust", 迴轉: "b-adjust", 取消作廢: "b-income", 新增: "b-journal", 復原: "b-transfer" };
export const openAudit = (tid = null) => openModal((close) => html`<${AuditDlg} tid=${tid} close=${close} />`);
function AuditDlg({ tid, close }) {
      const [kw, setKw] = useState("");
      const [rows, setRows] = useState(null);
      useEffect(() => { api("audit", tid, kw.trim()).then(setRows); }, [kw]);
      return html`<${Dialog} title=${tid ? `修改紀錄　V${String(tid).padStart(6, "0")}` : "修改紀錄（稽核軌跡）"} icon="eye" width="64rem" cls="listdlg" onClose=${() => close()}
          footer=${html`<span class="hint">修改紀錄由系統自動保存，無法刪除或修改，可作為帳務稽核之依據。</span><div class="grow"></div><${Btn} kind="primary" onClick=${() => close()}>關閉</${Btn}>`}>
        ${!tid && html`<div class="row" style="margin-bottom:.7rem"><${TextInput} icon="search" value=${kw} onInput=${setKw} placeholder="搜尋傳票號碼、動作或內容…" /></div>`}
        ${rows == null ? html`<div class="muted">讀取中…</div>` : html`<${DataTable} rows=${rows} maxHeight="60vh" empty="沒有修改紀錄"
          columns=${[{ key: "at", title: "時間", render: (r) => r.at, nowrap: true, width: "11rem" },
                     { key: "action", title: "動作", align: "c", render: (r) => html`<span class=${"type " + (ACTION_CLS[r.action] || "b-transfer")}>${r.action}</span>` },
                     { key: "voucher", title: "傳票號碼", align: "c", render: (r) => r.voucher, nowrap: true },
                     { key: "text", title: "內容", render: (r) => r.text }]} />`}
      </${Dialog}>`;
}
