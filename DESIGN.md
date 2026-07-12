# Design

HomeBook（4~5 人家庭拆帳帳本）的視覺 token 契約。register: product。
來源：`docs/superpowers/specs/2026-07-12-homebook-design-brief.md`（已確認）。

## 色彩策略

Restrained（暖紙變體）：暖奶油紙中性色為底、柿子橘單一 accent（視覺占比 ≤10%），
另設 5 個色弱安全的成員識別色，僅用於身分標記（永遠搭配名字或字首，不單靠顏色）。
不用「綠色＝錢」、不用金融 navy。淺色暖紙為唯一主題；深色版是非目標。

### 中性色（暖紙，hue 80，chroma 0.008–0.014）

```css
--paper:        oklch(97.5% 0.010 80);  /* 頁面底 */
--paper-raised: oklch(99.2% 0.006 80);  /* 卡片、表單面 */
--paper-sunken: oklch(94.5% 0.013 80);  /* 導覽列、chip 底、次要面板 */
--ink:          oklch(30% 0.018 60);    /* 正文（對 --paper ≥ 7:1） */
--ink-muted:    oklch(47% 0.020 65);    /* 次要文字（對 --paper ≥ 4.5:1） */
--line:         oklch(88% 0.014 80);    /* 邊框、分隔線 */
--line-strong:  oklch(80% 0.016 80);    /* 表單控件邊框（≥3:1） */
```

### Accent（柿子橘，hue 45）

```css
--accent:        oklch(58% 0.155 45);   /* 主按鈕底、FAB；白字 ≥4.5:1 */
--accent-strong: oklch(50% 0.150 45);   /* hover/active */
--accent-text:   oklch(51% 0.150 45);   /* 紙底上的連結/選取文字 */
--accent-soft:   oklch(94% 0.035 50);   /* 當前 tab 底、到期卡淡底 */
```

用途白名單：主要動作、當前選取、到期提示、focus ring。不做裝飾。

### 成員識別色（Okabe-Ito 系、避開 accent 橘）

```css
--member-1: oklch(55% 0.115 250);  /* 藍 */
--member-2: oklch(56% 0.115 165);  /* 綠 */
--member-3: oklch(70% 0.125 85);   /* 琥珀 */
--member-4: oklch(58% 0.115 340);  /* 紫紅 */
--member-5: oklch(65% 0.095 220);  /* 天藍 */
```

呈現：色點或字首頭像（CSS 產生），旁必附名字。存於 members.color（token 名稱字串 `member-1`…）。

### 語意色

```css
--ok:      oklch(53% 0.115 155);  /* 已結清、付清 */
--warn:    oklch(62% 0.125 75);   /* 快照過期、逾期（語氣溫和） */
--danger:  oklch(52% 0.175 25);   /* LedgerImbalance、錯誤（誠實原則，照實顯示） */
--ok-soft:     oklch(94% 0.030 155);
--warn-soft:   oklch(94% 0.035 80);
--danger-soft: oklch(95% 0.025 25);
```

## 字體

```css
--font: "LINE Seed Sans TC", "Noto Sans TC", "PingFang TC",
        "Microsoft JhengHei", system-ui, sans-serif;
```

- 自架 woff2、`font-display: swap`；只 preload Regular。
- 單一字族；weight 400 / 700（LINE Seed 另有 Th/XBd，不用）。
- **所有金額一律 `font-variant-numeric: tabular-nums`**（`.num` 類）。
- 固定 rem 級距，比例 1.2：

```css
--text-xs:   0.8125rem;  /* 註記、時間戳 */
--text-sm:   0.875rem;   /* 次要 UI、meta */
--text-base: 1rem;       /* 正文（16px 下限，長輩友善） */
--text-lg:   1.2rem;     /* 小節標題、列表金額 */
--text-xl:   1.44rem;    /* 頁標題、卡片金額 */
--text-2xl:  1.728rem;   /* quick-add 金額輸入、月摘要數字 */
```

行高：正文 1.6；標題 1.25；`text-wrap: balance` 用於標題。

## 間距 / 圓角 / 陰影

4pt 基底：`--sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-6: 24px; --sp-8: 32px; --sp-12: 48px`。
分區靠留白與字級，不做卡片海；卡片只給可操作物（到期卡、結算線、買到了 sheet）。

```css
--r-sm: 8px; --r-md: 12px; --r-full: 999px;
--shadow-sm: 0 1px 2px oklch(30% 0.02 60 / 0.07);
--shadow-md: 0 4px 16px oklch(30% 0.02 60 / 0.10);  /* sheet、FAB */
```

z-scale：dropdown 100 → sticky(tab bar) 200 → sheet-backdrop 300 → sheet 400 → toast 500。

## Motion

150–250ms、`cubic-bezier(0.16, 1, 0.3, 1)`（ease-out-expo）。只表達狀態：
卡片完成淡出、清單打勾移區、sheet 升起。無進場編排。`prefers-reduced-motion` 全部關閉。

## 版型

- Mobile（<768px）：底部 tab bar（5 tab，56px 高 + safe-area）、右下 FAB「＋記一筆」。
- Desktop（≥768px）：頂部導覽（同 5 tab），內容欄 max-width 60rem；總覽雙欄（左待辦、右摘要）。
- 觸控目標 ≥44px；focus-visible ring `2px solid var(--accent)` offset 2px。

## 元件狀態詞彙

- 按鈕：primary（accent 底白字）/ secondary（線框）/ ghost；八態齊備（default/hover/focus/active/disabled/loading/error/success）。
- 類別 chip：餐食/日用/交通/居住/醫療/教育/娛樂/其他；radio 語意、選取態 accent-soft 底。
- 成員 pill：色點 + 名字；頭像 = 字首圓形（CSS）。
- 到期卡：--warn-soft 底、標題 + 金額 +「確認入帳／跳過本期」；逾期顯示「逾期 N 天」（不催繳語氣）。
- 空態要教學（「這個月還沒有帳，＋記一筆開始」），不是「沒有資料」。
- 錯誤警示：--danger-soft 底 + --danger 字，全寬置頂，照實顯示訊息。

## 禁令（本專案特別提醒）

側邊色條（border-left accent）、漸層字、hero-metric 大數字模板、同構卡片海、
modal 優先（先用原生 `<dialog>`/`<details>`/bottom sheet）、em dash 文案。
