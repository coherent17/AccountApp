// 收支分類的小圖示：依分類名稱的關鍵字挑選（她自己新增或改名的分類也找得到合適的圖示），與介面圖示同一套線條。
// 每一項是 [關鍵字, 圖示名稱（icons.js）, 色調（style.css 的 --tone-*）]。
import { html } from "./core.js";
import { ICONS } from "../icons.js";

const RULES = [
  [/餐|飲|食|吃|早午|晚餐|午餐/, "c_food", "amber"], [/日常|用品|生活|超市|雜貨/, "c_basket", "teal"], [/交通|油|車|捷運|公車|計程/, "c_bus", "blue"],
  [/水電|電費|水費|瓦斯|居家/, "c_bulb", "amber"], [/房貸利息|利息支出/, "bank", "slate"], [/房租|房貸|租屋|管理費/, "home", "violet"], [/通訊|網路|手機|電話/, "c_phone", "blue"],
  [/醫療|保健|看病|藥/, "c_med", "rose"], [/健保/, "c_med", "teal"], [/保險|保費/, "c_shield", "blue"], [/服飾|美容|衣|美髮/, "c_shirt", "violet"], [/娛樂|休閒|電影/, "c_play", "violet"],
  [/旅遊|旅行|出國/, "c_plane", "blue"], [/教育|學習|書|課/, "c_cap", "violet"], [/人情|交際|禮/, "gift", "rose"], [/孝親|家用|家人|孫/, "c_family", "rose"],
  [/稅|規費|罰/, "c_receipt", "slate"], [/捐|公益/, "heart", "rose"], [/寵物/, "c_paw", "amber"], [/運動|健身/, "c_run", "teal"],
  [/薪資|薪水|工資/, "c_bag", "teal"], [/退休|年金/, "c_leaf", "teal"], [/股利|股息/, "trend_up", "teal"], [/利息/, "coins", "amber"], [/租金/, "c_building", "violet"],
  [/獎金|獎/, "c_medal", "amber"], [/紅包/, "c_envelope", "rose"], [/退款|退費/, "undo", "slate"],
];

function pick(name, kind) {
  for (const r of RULES) if (r[0].test(name || "")) return [r[1], r[2]];
  return kind === "income" ? ["dollar", "teal"] : kind === "expense" ? ["tag", "slate"] : null;
}

/** 分類圖示；boxed 為圓角底色方塊。沒有對應（例如轉帳）時不顯示。 */
export function CatIcon({ name, kind, boxed }) {
  const p = pick(name, kind);
  if (!p) return null;
  return html`<span class=${"cat-ic" + (boxed ? " boxed" : "")} style=${`--t:var(--tone-${p[1]})`}><svg class="ic" viewBox="0 0 24 24"
    dangerouslySetInnerHTML=${{ __html: ICONS[p[0]] || "" }}></svg></span>`;
}
