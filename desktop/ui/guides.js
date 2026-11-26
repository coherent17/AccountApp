// 操作導覽的內容。t 是要打亮的地方（CSS 選擇器，或 [選擇器, 文字]），optional 表示不一定有（找不到就跳過），all 表示把符合的全部框起來。
// page：這一頁的導覽；dialog＋open：視窗的導覽；go：這一步先換到哪一頁；before：先做的動作（只切換分頁，不改資料）。
import { openTxn } from "./dialogs/txn.js";
import { openJournal } from "./dialogs/journal.js";
import { openReconcile, openRecurring, openSearch } from "./dialogs/more.js";
import { openPrices, openTrade } from "./dialogs/invest.js";
import { openChart } from "./dialogs/chart.js";
import { openFeedback, openForecast, openHealth, openMonthClose, openReminders, openYearAssist } from "./dialogs/tools.js";

const tab = (label) => () => { const b = [...document.querySelectorAll(".tabs button")].find((x) => x.textContent.includes(label)); if (b) b.click(); };
const nav = (label) => [".side .nav", label];
const act = (label) => [".head .actions .btn", label];
const foot = (label) => [".dfoot .btn", label];
const field = (label) => [".field > label", label, "up"];        // 框住整個欄位，不會被說明文字裡的同名字樣誤認

export const NEWS_VERSION = "3.10";          // 3.10.x 都顯示（版本號前兩段相同）          // 「已更新到」視窗在這一版會多一個「帶我看看新功能」
export const GROUPS = [["news", "這一版的新功能"], ["flow", "一步一步怎麼做"], ["page", "認識每一頁"], ["dialog", "常用視窗"]];

export const GUIDES = {
  // ================================================================ 這一版的新功能
  news: { group: "news", title: "3.10.1 版的新功能", icon: "gift", desc: "行備註、自訂比較期間", steps: [
    { go: "reports", before: tab("分類帳"), t: [".page-fill thead th", "行備註"], title: "分類帳顯示行備註", text: "原本的「對方科目」改為傳票上這一行的**行備註**；列印與匯出 Excel 也一樣。" },
    { before: tab("日記帳"), t: [".page-fill thead th", "行備註"], title: "日記帳多了行備註", text: "每個科目右邊列出它在傳票上的行備註；上方的搜尋也找得到行備註。" },
    { before: tab("收支損益表"), t: [".page-fill > .row .lbl", "比較", "up"], title: "自訂比較期間", text: "「比較」選**自訂比較期間**，就能自己選比較的期間；資產負債表則是選比較日。列印時也可以用同一組日期。收支損益表的「筆數」欄已拿掉。" },
    { t: ".side [data-g=help]", title: "忘記了隨時再看", text: "所有導覽都在「操作導覽」，也可以按 [[F1]]。" },
  ] },

  // ================================================================ 一步一步怎麼做
  flow_day: { group: "flow", title: "每天怎麼記帳", icon: "edit", desc: "記一筆、複式分錄、記錯了怎麼辦", steps: [
    { t: ".side [data-g=new]", title: "最快的方法：記一筆", text: "在任何一頁都能按這裡，或按 [[Ctrl+N]]。適合一般的收入、支出與轉帳。" },
    { go: "transactions", t: act("複式分錄"), title: "要自己輸入借貸時", text: "一筆付款分到多個科目、買賣股票、房貸本息，用**複式分錄**。借貸平衡才能儲存。" },
    { t: ".table-card", title: "記好的傳票在這裡", text: "按兩下開啟修改；按右鍵可以複製、迴轉、作廢、加標籤。" },
    { t: ".side [data-g=undo]", title: "記錯了也不用擔心", text: "剛才的動作按 [[Ctrl+Z]] 就能復原。作廢的傳票會保留在帳上，並留下修改紀錄。" },
  ] },
  flow_month: { group: "flow", title: "每個月怎麼收帳", icon: "calendar", desc: "定期交易、銀行對帳、市價評價、月結", steps: [
    { go: "dashboard", t: ".soon", title: "先看提醒", text: "到期的定期交易、繳款與月結會列在這裡，照著按鈕做就可以。" },
    { go: "accounts", t: act("更多功能"), title: "銀行對帳", text: "「更多功能 → 銀行對帳」：拿存摺逐筆核對；也能匯入網路銀行的明細，自動勾選。" },
    { go: "investments", t: act("市價評價"), title: "月底市價評價", text: "輸入日期與市價，未實現損益才會更新。可以從 Excel 整欄貼上價格。" },
    { go: "reports", t: act("月報"), title: "看一頁月報", text: "一個月的收支、預算、淨資產與投資，一頁看完，可列印或存成 PDF。" },
    { go: "dashboard", t: ".soon h3 button", title: "月結小幫手帶您做完", text: "在「小幫手 → 月結小幫手」，上面這些步驟會一項一項打勾，進度會記住。" },
  ] },
  flow_stock: { group: "flow", title: "買賣股票到評價", icon: "chart", desc: "投資帳戶、標的、買賣、股利、評價、報酬率", steps: [
    { go: "accounts", t: act("新增帳戶"), title: "一、先有投資科目", text: "類別選「短期投資」或「長期投資」，期初餘額填 0。已經有的就不用再建。" },
    { go: "investments", t: act("標的設定"), title: "二、建立標的", text: "輸入代號、名稱與類型；手續費率和證交稅率會依類型帶入，可以改成您的折扣。" },
    { t: act("買進"), title: "三、登錄買賣", text: "按「買進」「賣出」，分錄會自動產生；也可以在**複式分錄**選投資標的、填股數與單價，兩種方式都會計入持股。" },
    { t: act("股利"), title: "四、現金股利與配股", text: "現金股利會帶入二代健保補充保費，可以修改。" },
    { t: act("市價評價"), title: "五、評價", text: "買賣不會自動評價；輸入市價按「產生評價分錄」，帳面價值才會調整為**預估淨售價**。" },
    { before: tab("報酬分析"), t: ".tabs button.on", title: "六、看報酬率", text: "總報酬率包含已實現、股利與未實現損益；持有滿一年會再算年化報酬率。" },
  ] },
  flow_check: { group: "flow", title: "報表的數字怎麼查", icon: "search", desc: "從試算表點到分類帳，再點到傳票", steps: [
    { go: "reports", before: tab("試算表"), t: ".table-card", title: "從報表開始", text: "在試算表、資產負債表或收支損益表，**點一下會計科目**。" },
    { before: tab("分類帳"), t: ".ledger-pick", title: "就會開到分類帳", text: "期間與報表相同，期末餘額就是報表上的數字。也可以直接在這裡輸入代號或名稱。" },
    { t: ".table-card", title: "再按兩下看傳票", text: "每一列都能按兩下開啟原來的傳票。看完按「← 回到試算表」，會停在剛才的位置。" },
    { t: [".page-fill .btn", "Excel"], title: "只印這一個科目", text: "這裡的「列印」與「Excel」只會輸出目前這個科目。" },
  ] },
  flow_year: { group: "flow", title: "年底怎麼結帳", icon: "lock", desc: "年底評價、年度報告、年度結帳", steps: [
    { go: "dashboard", t: ".soon h3 button", title: "用年度結帳小幫手", text: "在「小幫手 → 年度結帳小幫手」；12 月 15 日起總覽也會提醒。一步一步做，可以分幾天完成。" },
    { go: "reports", t: act("年度財務報告"), title: "年度財務報告", text: "封面、四大報表、財務比率、投資績效一次產生，可勾選要放哪些內容。" },
    { before: tab("報稅彙總"), t: ".table-card, .stmt", title: "報稅彙總", text: "依「設定 → 收支分類」的稅務歸類整理，五月報稅時可以參考。" },
    { go: "settings", before: tab("結帳"), t: ".main .card", title: "結帳與解除", text: "結帳後，該日以前的傳票會鎖定。要更正時可以在這裡解除；結帳前會先自動備份。" },
  ] },
  flow_safe: { group: "flow", title: "資料怎麼保護", icon: "c_shield", desc: "自動備份、第二份備份、健康檢查、還原", steps: [
    { go: "settings", before: tab("資料管理與備份"), t: field("資料位置"), title: "資料都在自己的電腦", text: "每天第一次開啟會自動備份，保留 30 份。" },
    { t: field("第二份備份"), title: "建議設定第二份備份", text: "選隨身碟或 OneDrive 資料夾，電腦硬碟故障時也救得回來。" },
    { t: field("備份與還原"), title: "手動備份與還原", text: "「從備份檔還原」之前，會先自動保存目前的帳本。" },
    { t: [".field .btn", "資料健康檢查"], title: "資料健康檢查", text: "確認檔案完整、借貸平衡、投資帳與持股一致、備份正常，有問題會說明怎麼處理。" },
  ] },

  // ================================================================ 認識每一頁
  screen: { group: "page", title: "認識畫面", icon: "monitor", desc: "選單、快速功能、字體與外觀、結束程式", steps: [
    { t: ".side .nav:not([data-g])", all: true, title: "六個主要頁面", text: "按一下切換，或按 [[Ctrl+1]] 到 [[Ctrl+6]]。" },
    { t: ".side .nav[data-g]", all: true, title: "快速功能", text: "記一筆 [[Ctrl+N]]、搜尋 [[Ctrl+F]]、復原 [[Ctrl+Z]]，在任何一頁都能用。操作導覽是 [[F1]]。" },
    { t: ".side-toggle", title: "收合選單", text: "只留圖示，表格會更寬。按 [[Ctrl+B]] 也可以。" },
    { t: ".side .prefs", optional: true, title: "外觀與字體", text: "淺色／深色、標準／大／特大，切換立即生效。" },
    { t: ".userbox", title: "意見回饋與結束", text: "對話框圖示可以寫下想法、產生 PDF；⏻ 是結束程式，帳本會自動儲存並備份。" },
  ] },
  dashboard: { group: "page", page: "dashboard", title: "總覽", icon: "home", desc: "淨資產、本月收支、提醒與最近的紀錄", steps: [
    { t: ".hero2", title: "淨資產", text: "資產總計減負債總計，以及近 12 個月的走勢。右邊是本月結餘與儲蓄率。" },
    { t: ".kgrid .stat", all: true, title: "資產、負債與本月收支", text: "收入、支出旁的百分比是和上個月比。" },
    { t: ".soon", title: "提醒與近期行事曆", text: "定存到期、保費、定期交易都在這裡。**「小幫手」**裡有月結、年度結帳、現金流預測與健康檢查。" },
    { t: ".recent", title: "最近的紀錄", text: "按一下就能開啟傳票。" },
    { t: ".insights-row", title: "本月洞察與支出排行", text: "往下捲，還有財務健康指標、圖表與預算。" },
  ] },
  transactions: { group: "page", page: "transactions", title: "收支明細", icon: "list", desc: "日記帳：新增、篩選、修改、作廢", steps: [
    { t: ".head .actions", title: "新增紀錄", text: "記支出、記收入、轉帳，或用複式分錄輸入多行借貸。" },
    { t: ".filters .pchips", title: "選期間", text: "常用期間按一下就好；右邊的日期也可以直接打，例如 115/11/5、1151105 或 11/5。" },
    { t: ".filters .frow:last-child", title: "篩選與搜尋", text: "類型、帳戶、分類、標籤可以一起用；輸入文字會找說明、分類、帳戶與標籤。" },
    { t: ".table-card", title: "每一筆傳票", text: "**按兩下**修改；**按右鍵**複製、迴轉、作廢、加標籤。[[Ctrl]] 或 [[Shift]] 可以多選，按標題可以排序。" },
    { t: ".card.foot", title: "合計", text: "目前篩選結果的收入、支出與結餘。" },
    { t: act("更多功能"), title: "更多功能", text: "定期交易、匯入 Excel、匯出報表、修改紀錄與會計科目表。" },
  ] },
  accounts: { group: "page", page: "accounts", title: "帳戶管理", icon: "wallet", desc: "資產與負債科目、對帳、更新餘額", steps: [
    { t: ".grid.kpis", title: "淨資產、資產、負債", text: "下面兩個表的合計。" },
    { t: ".main .tablewrap", title: "資產與負債科目", text: "**按兩下**修改帳戶；**按右鍵**可以看分類帳、銀行對帳、更新餘額或封存。" },
    { t: act("會計科目表"), title: "會計科目表", text: "所有科目與代號都在這裡，可以新增科目、自訂代號。" },
    { t: act("更新餘額"), title: "更新餘額／市值", text: "保單、外幣這類會變動的資產，輸入目前實際金額，差額會自動記錄。股票請用「市價評價」。" },
    { t: act("更多功能"), title: "更多功能", text: "銀行對帳、更新匯率、現金流預測。" },
  ] },
  investments: { group: "page", page: "investments", title: "投資管理", icon: "chart", desc: "持股、買賣、股利、市價評價、報酬率", steps: [
    { t: ".kpis5", title: "投資總覽", text: "帳面價值、成本、未實現損益，以及今年的已實現損益與股利。" },
    { t: act("買進"), title: "買進、賣出、股利", text: "輸入股數與單價，手續費與稅自動計算，分錄自動產生。" },
    { t: act("市價評價"), title: "市價評價", text: "只有在這裡輸入市價才會評價；可以從 Excel 貼上。" },
    { t: ".tabs", title: "四個分頁", text: "持股明細、交易紀錄、已實現損益、報酬分析。輸入錯誤的交易可以在**交易紀錄**刪除。" },
    { t: ".hold-bar", optional: true, title: "看某一天的持股", text: "改日期，就能看那一天的持股與成本。" },
    { t: act("標的設定"), title: "標的設定", text: "修改代號、名稱、手續費率與證交稅率。" },
  ] },
  reports: { group: "page", page: "reports", title: "財務報表", icon: "report", desc: "十種報表、期間、比較、列印與匯出", steps: [
    { t: ".filters .pchips", title: "報表期間", text: "選一次，所有報表都用同一個期間。" },
    { t: ".tabs", title: "十種報表", text: "四大報表與收支分析、帳簿（日記帳、分類帳、試算表）、報稅彙總，以細線分組。" },
    { before: tab("資產負債表"), t: [".page-fill > .row .lbl", "比較", "up"], optional: true, title: "比較兩期", text: "與上一期、去年同期，或**自訂比較期間**比較，會多出增減金額與百分比。" },
    { t: ".table-card", title: "點科目看分類帳", text: "**點一下科目**會開啟同一期間的分類帳，再按兩下開啟傳票。" },
    { t: act("列印"), title: "列印與 PDF", text: "勾選要印的報表，會先預覽；印表機選「另存為 PDF」就能存檔。" },
    { t: act("匯出 Excel"), title: "匯出 Excel", text: "合計都是公式，可以自己選要哪些工作表。" },
    { t: act("年度財務報告"), title: "月報與年度財務報告", text: "一頁的月報，或整年度的完整報告。" },
  ] },
  settings: { group: "page", page: "settings", title: "設定", icon: "settings", desc: "外觀、分類與預算、結帳、備份、更新", steps: [
    { before: tab("個人與外觀"), t: ".tabs", title: "五個分頁", text: "設定依用途分開，按一下切換。" },
    { t: field("操作導覽"), title: "操作導覽", text: "所有的導覽都可以從這裡再看一次。" },
    { before: tab("收支分類"), t: ".main .card", title: "收支分類與預算", text: "按兩下修改；按右鍵設定每月預算、稅務歸類、排序或隱藏。" },
    { before: tab("結帳"), t: ".main .card", title: "結帳", text: "對帳完成後可以鎖定以前的期間；年度結帳也在這裡。" },
    { before: tab("資料管理與備份"), t: field("第二份備份"), title: "第二份備份", text: "建議設定隨身碟或 OneDrive，多一層保障。" },
    { before: tab("網路與更新"), t: field("版本更新"), title: "版本更新", text: "有新版本時會提示，按一下就能更新，更新前會自動備份。" },
  ] },

  // ================================================================ 常用視窗
  txn: { group: "dialog", dialog: true, open: () => openTxn({ type: "expense" }), title: "記一筆", icon: "edit", desc: "常記項目、算式金額、標籤、附件", steps: [
    { t: ".quick", optional: true, title: "常記的項目", text: "按一下就帶入分類、帳戶、說明與上次的金額，改一下金額即可。" },
    { t: ".seg.types", optional: true, title: "支出、收入、轉帳", text: "轉帳是自己帳戶之間移動，例如領現金、繳信用卡。" },
    { t: ".amount.big", title: "金額可以打算式", text: "例如 120+35*2，會直接算好。" },
    { t: field("分類"), title: "選分類", text: "輸入以前記過的說明，分類與帳戶會自動帶入。" },
    { t: field("標籤"), title: "標籤", text: "把一趟旅行、一次修繕的花費歸在一起，到「財務報表 → 標籤／專案」看合計。" },
    { t: field("附件"), title: "附件", text: "收據、帳單照片或 PDF 可以附在傳票上。" },
    { t: foot("改用複式分錄"), optional: true, title: "要分攤到多個科目", text: "目前輸入的內容會帶到複式分錄。" },
  ] },
  journal: { group: "dialog", dialog: true, open: () => openJournal(), title: "複式分錄", icon: "book", desc: "借貸、範本、投資標的、自動平衡", steps: [
    { t: ".quick.jq", optional: true, title: "常用分錄", text: "按一下帶入以前的科目與金額。" },
    { t: [".jtop .field > label", "範本", "up"], optional: true, title: "範本", text: "內建常用的範本，也可以把自己的分錄「存成範本」。" },
    { t: [".jtop .field > label", "摘要", "up"], title: "摘要", text: "輸入以前用過的摘要（月份不同也可以），會提示上一張分錄。" },
    { t: ".jtable .combo", title: "會計科目", text: "輸入**代號或名稱**搜尋，[[↑]] [[↓]] 選擇、[[Enter]] 確定。" },
    { t: ".jtable tbody tr:first-child td:nth-child(3), .jtable tbody tr:first-child td:nth-child(4)", all: true, title: "借方與貸方", text: "每一行填借方或貸方其中一邊，可以打算式。" },
    { t: ".jtable thead th:nth-child(5)", title: "投資標的與外幣", text: "選到投資科目會出現標的、股數與單價；外幣科目會出現原幣與匯率，金額自動換算。" },
    { t: [".jtools .btn", "自動平衡"], optional: true, title: "自動平衡差額", text: "把借貸差額填入最後一行空白的金額。右邊會顯示是否平衡。" },
    { t: foot("設為定期"), optional: true, title: "設為定期", text: "每月、每季或每年固定的分錄，到期時提醒您入帳。" },
  ] },
  trade: { group: "dialog", dialog: true, open: () => openTrade("buy"), title: "買進／賣出", icon: "coins", desc: "股數、單價、手續費、交割帳戶", steps: [
    { t: field("投資標的"), title: "選標的", text: "下面會顯示目前持股與平均成本。" },
    { t: field("股數"), optional: true, title: "股數與成交價", text: "手續費與證交稅依標的費率自動計算，無條件捨去到元。" },
    { t: field("手續費"), optional: true, title: "可以改成實際金額", text: "與對帳單不同時直接改，就不會再自動計算。" },
    { t: field("交割帳戶"), optional: true, title: "交割帳戶", text: "扣款或入帳的銀行帳戶。" },
    { t: ".calcbar", title: "先看結果再儲存", text: "買進顯示應付金額；賣出顯示實收與預估已實現損益。" },
  ] },
  prices: { group: "dialog", dialog: true, open: () => openPrices(), title: "市價評價", icon: "refresh", desc: "輸入市價、從 Excel 貼上、產生分錄", steps: [
    { t: ".date", title: "評價日期", text: "通常是月底或年底。同一天再評價一次，會取代先前的市價。" },
    { t: ".tablewrap", optional: true, title: "輸入市價", text: "留空表示這一檔不評價。" },
    { t: [".dbody .btn", "貼上價格"], title: "整欄貼上", text: "在 Excel 複製「代號」與「價格」兩欄，一次貼上；會先讓您看對應結果。" },
    { t: foot("產生評價分錄"), title: "產生評價分錄", text: "按下去才會入帳：帳面價值調整為預估淨售價，同一天的評價合併成一張傳票。" },
  ] },
  recon: { group: "dialog", dialog: true, open: () => openReconcile(), title: "銀行對帳", icon: "check", desc: "存摺核對、自動勾選、未達帳項", steps: [
    { t: ".two-fields", title: "對帳單日期與餘額", text: "照存摺或對帳單輸入。" },
    { t: ".tablewrap", title: "逐筆勾選", text: "存摺上出現的就打勾；沒勾的就是未達帳項。" },
    { t: foot("匯入銀行明細"), title: "自動勾選", text: "選網路銀行下載的 Excel 或 CSV，金額相同、日期差三天內的會自動勾選。" },
    { t: foot("完成對帳"), title: "差額為 0 就完成", text: "完成後這些傳票會標記為已核銷。" },
  ] },
  recurring: { group: "dialog", dialog: true, open: () => openRecurring(), title: "定期交易", icon: "restore", desc: "退休金、水電、保費與定期分錄", steps: [
    { t: ".tablewrap", title: "固定的收支", text: "退休金、水電、保費、房貸都可以設定，到期時會提醒。" },
    { t: foot("新增"), title: "新增", text: "選每月、每季或每年的哪一天；類型可以是支出、收入、轉帳或分錄。" },
    { t: foot("檢查到期"), title: "檢查到期項目", text: "列出到期還沒入帳的，確認後才會產生傳票。" },
  ] },
  chart: { group: "dialog", dialog: true, open: () => openChart(), title: "會計科目表", icon: "layers", desc: "科目、代號、新增與封存", steps: [
    { t: ".tablewrap", title: "全部科目", text: "資產 1、負債 2、權益 3、收入 4、費用 5、業外損益 7。按兩下修改。" },
    { t: foot("新增會計科目"), title: "新增科目", text: "代號會自動建議，也可以自訂。" },
    { t: foot("封存"), title: "封存", text: "不再使用的科目可以封存：記帳時不會出現，過去的資料都還在。" },
  ] },
  search: { group: "dialog", dialog: true, open: () => openSearch(window.__go), title: "全域搜尋", icon: "search", desc: "找傳票、科目、標的與導覽", steps: [
    { t: "input", title: "打什麼都可以", text: "說明、金額、**V000123** 傳票號碼、**114/3/5** 日期、科目代號。用空白分開可以同時找多個條件。" },
    { t: ".dbody", title: "按兩下開啟", text: "會直接開到傳票、分類帳、交易紀錄或定期交易。" },
  ] },
  month: { group: "dialog", dialog: true, open: () => openMonthClose(), title: "月結小幫手", icon: "calendar", desc: "每月收帳的六個步驟", steps: [
    { t: ".mc-head", title: "進度", text: "右邊可以換月份。進度會記住，可以分幾天做。" },
    { t: ".mc-steps", title: "一步一步", text: "能自動確認的會自己打勾，其他按「標記完成」。" },
    { t: foot("月結"), title: "完成", text: "最後會有一頁月報可以列印。" },
  ] },
  year: { group: "dialog", dialog: true, open: () => openYearAssist(), title: "年度結帳小幫手", icon: "lock", desc: "年底到隔年初的結帳步驟", steps: [
    { t: ".mc-head", title: "選年度", text: "年度結束（隔年 1 月 1 日）之後才能結帳，前面的步驟可以先做。" },
    { t: ".mc-steps", title: "一步一步", text: "定期交易、對帳、年底評價、健康檢查、年度報告，最後結帳。" },
  ] },
  forecast: { group: "dialog", dialog: true, open: () => openForecast(), title: "現金流預測", icon: "trend_up", desc: "推算各帳戶未來的餘額", steps: [
    { t: ".fc-bar", title: "看幾個月、低水位", text: "預計低於低水位時，總覽會提醒您。" },
    { t: ".fc-top", optional: true, title: "各帳戶的預計餘額", text: "按一下卡片只看那個帳戶。" },
    { t: ".tablewrap", optional: true, title: "每一筆預計的收支", text: "依定期交易，以及有金額和帳戶的提醒推算；定存到期只列出、不計入。" },
  ] },
  reminders: { group: "dialog", dialog: true, open: () => openReminders(), title: "到期提醒中心", icon: "bell", desc: "保費、繳款、除息日提醒", steps: [
    { t: ".dbody", title: "接下來 90 天", text: "自己設的提醒、定存到期、定期交易與報稅季排成一列。" },
    { t: foot("新增"), title: "新增提醒", text: "可以一次、每月或每年，並設定提前幾天提醒。填了金額與帳戶就會算進現金流預測。" },
  ] },
  health: { group: "dialog", dialog: true, open: () => openHealth(), title: "資料健康檢查", icon: "pulse", desc: "借貸平衡、備份、對帳是否正常", steps: [
    { t: ".dbody", title: "一次檢查全部", text: "檔案完整、借貸平衡、投資帳與持股一致、備份、對帳與評價。有黃色或紅色時，會說明怎麼處理。" },
  ] },
  feedback: { group: "dialog", dialog: true, open: () => openFeedback(), title: "意見回饋", icon: "chat", desc: "累積想法，產生 PDF 用 LINE 傳送", steps: [
    { t: "textarea", title: "寫下問題或想法", text: "會附上剛才的畫面（可以不附）。" },
    { t: foot("加入清單"), title: "可以累積好幾則", text: "加入清單後繼續使用程式，想到再加。" },
    { t: foot("PDF"), title: "產生 PDF", text: "完成後已複製好，在 LINE 按 [[Ctrl+V]] 貼上就能傳送。不會上傳到網路。" },
  ] },
};
