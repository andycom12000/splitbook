# HomeBook — 家庭拆帳帳本 Design Brief

> 由 `/impeccable shape` 產出並經使用者確認（2026-07-12）。
> 實作時：以 `/impeccable craft` 接手本 brief，先生成 DESIGN.md，再依「工程對應」小節動工。
> 策略 context 見 repo root `PRODUCT.md`（register: product）。

## 1. Feature Summary

把 splitbook（旅遊拆帳）重塑為 4~5 人家庭日常共用的帳本：新增帳目與拆帳、付款/轉帳/月結算、共用購物清單（買完打勾即轉帳目）、定期項目（房租/水電瓦斯/網路，到期提醒＋一鍵入帳）。領域核心（分錄帳本、守恆不變量、分攤規則、快照對帳）完整沿用，重新設計的是 IA、視覺與互動流程。

## 2. Primary User Action

**三步內記完一筆帳。** 全站圍繞「降低記帳摩擦」設計：quick-add、清單打勾轉帳目、定期一鍵入帳，都是同一個動作的三種入口。

## 3. Design Direction

- **色彩策略：Restrained（暖紙變體）**。暖奶油紙色為底（OKLCH 暖色調 tinted neutrals，hue 約 75–90）、柿子橘單一 accent ≤10%（主按鈕、當前選取、到期提示）；另有 4~5 個色弱安全的**成員識別色**，僅用於身分標記（頭像圓點＋名字，不單靠色彩）。反類別直覺：不用「綠色＝錢」也不用金融 navy。
- **場景句**：晚上九點半，媽媽窩在客廳暖黃檯燈下用手機補記全聯收據；妹妹在超市日光燈下打勾剛買到的牛奶——兩個場景都是亮環境 → **淺色暖紙主題**（現有深色 Fira 風格不延用；深色版列為非目標）。
- **Anchors**：Zaim（日系家計簿的親切與記帳速度）、無印良品（暖紙質感與克制）、Notion（清爽的結構密度）。
- **字體**：LINE Seed Sans TC（圓潤但正式、免費自架）＋ tabular numerals 呈現所有金額；單一字族，scale 1.2。

## 4. Scope

- **Fidelity**：production-ready
- **Breadth**：整個 app（5 個主要 surface＋onboarding）
- **Interactivity**：shipped quality；維持 FastAPI + Jinja2 SSR，漸進增強（原生 `<dialog>`/`<details>`＋少量 vanilla JS 做 bottom sheet 與清單打勾），**不引入前端框架**
- **Time intent**：polish until it ships

## 5. Layout Strategy

**IA：5 個分頁**（mobile 底部 tab bar、desktop 頂部導覽）：

```
總覽(這個月) ｜ 帳目 ｜ 清單 ｜ 定期 ｜ 結算
```

- **總覽**是每日落點，資訊按「今天需要我做什麼」排序：① 待確認的定期項目卡（有到期才出現，最高優先）→ ② 一句話月摘要（「7 月全家花了 $23,410，你目前應收 $1,250」，散文式而非 hero-metric 大數字模板）→ ③ 要買的（清單前 4 項）→ ④ 最近帳目。mobile 右下 FAB「＋記一筆」。
- **層級節奏**：暖紙底上用留白與字級分區，不做卡片海；成員識別色點是全站的視覺錨。
- Desktop：內容欄 max-width 56–64rem，總覽雙欄（左：待辦類，右：摘要與最近帳目）。

## 6. Key States

| Surface | 狀態 |
|---|---|
| Onboarding | 首次進入：建家庭 → 加成員（配識別色）→（可跳過）加第一個定期項目 |
| 總覽 | 無到期（待確認區隱藏）；有逾期（卡片標「逾期 N 天」，語氣溫和）；月初空月 |
| 帳目 | 空月教學態（「這個月還沒有帳，＋記一筆開始」）；LedgerImbalance 紅色警示（誠實原則） |
| 清單 | 空清單教學態；全部買完（克制的一行慶祝）；已買區近 7 天含帳目連結 |
| 定期 | 無範本教學態（附常見範例：房租、電費）；「每期填金額」項目到期時金額欄空待填 |
| 結算 | 全結清；快照過期警告（沿用）；部分付款 ⏳／付清 ✅ |

## 7. Interaction Model

- **quick-add（三步）**：金額（大數字鍵盤優先）→ 名稱＋類別 chip（餐食/日用/交通/居住/醫療/教育/娛樂/其他）→ 付款人預設「我」、拆帳預設「全家均分」；權重/指定金額摺疊在「進階拆帳」內。
- **清單打勾**：勾選 → bottom sheet「買到了！」：實際金額（預填預估）、付款人預設我、拆帳預設全家 → 送出即成帳目並移入已買。多選數項→「一起結帳」合成一筆（明細寫入備註）。
- **定期確認**：到期卡「確認入帳」→ 開 quick-add 預填（固定金額直接帶入、每期填的留空）→ 入帳並推進下次到期；「跳過本期」同樣推進。週期支援每月 N 日／**每兩月**（台灣水電）／每年。
- **每個動作一句話**（Discord 前瞻）：「記 250 晚餐 我付」「加 牛奶 到清單」「電費 1,240 入帳」——UI flow 與未來 bot 指令一一對應。
- Motion：150–250ms、ease-out、只表達狀態（卡片完成淡出、打勾移區）。

## 8. Content Requirements

- 全站台灣家庭用語：「記一筆」「要買的」「該繳的」「月結」「已結清」
- 定期卡文案：「房租 $25,000・3 天後」「電費帳單來了嗎？這期多少：____」
- 錯誤訊息沿用誠實原則（「帳本不平衡：…」照實顯示）
- 動態範圍：帳目 0~200 筆/月；清單 0~30 項；定期 0~10 項；成員固定 4~5
- 無圖像資產需求：identity 靠成員色點＋字首頭像（CSS 產生）

## 9. Recommended References（craft 時載入）

`interaction-design.md`（表單密集）、`spatial-design.md`（總覽層級）、product register 的 component states 清單。

## 10. Open Questions

無阻斷項。已代決的預設：類別集合如上（可日後編輯）；成員識別色預設配置、可於成員設定改；深色主題列為非目標；Discord bot 本期不實作、只保留動作語意對齊。

---

## 工程對應（供實作參考，不屬 brief 本體）

- **domain 層零改動**：`split.py`/`ledger.py`/`reconcile.py` 原樣沿用。
- **schema 新增**：`shopping_items`（name, note, estimate, added_by, assigned_to, bought_at, entry_id 連結）、`recurring_templates`（name, category, amount 可 NULL=每期填, split 規則序列化, payer_default, cycle: monthly_day/bimonthly/yearly, next_due, active）；entries 加 `template_id` 來源欄位（皆為 additive migration）。
- **月結**：沿用 snapshots，快照命名依月份。
- **頁面**：沿用 thin-routes 模式（表單解析 → repo/domain → 模板），新增 總覽/清單/定期 三頁，帳目與結算頁改版。
- **視覺**：全新 light warm theme 取代現有 style.css 深色主題；LINE Seed Sans TC 自架。
