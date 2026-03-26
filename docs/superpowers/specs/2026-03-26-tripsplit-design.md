# TripSplit — 40 人出遊拆帳系統設計文件

## 概述

為 40 人出遊團建立一個拆帳管理系統，由主辦人單人操作，主要在手機上使用。系統從 Notion 讀取人員 Master Data，在另一個 Notion DB 記錄帳目，由後端計算拆帳後將結果寫回 Master Data。

## 需求摘要

- **使用者**：僅主辦人一人操作，不需登入/權限系統
- **團體規模**：40 人
- **帳目規模**：最多 15 筆
- **分攤方式**：依標籤群組均分（同一標籤群組內平均分攤）
- **參與者子集**：透過 Master Data 上的標籤定義（如「全程」「酒水」）
- **代墊處理**：某人先付共同費用，參與者分攤還他
- **結算結果**：寫回 Notion Master Data（欄位 + 留言/描述區的帳目明細）
- **收款**：主辦人手動處理，系統不自動產生收款連結
- **一次性使用**：不需考慮複用，不需 over-engineer

## 架構

```
[手機瀏覽器]
    │
    ▼
[FastAPI + Jinja2]  ← 單一 Python 專案
    │
    ├─ /           → 人員總覽頁
    ├─ /expenses   → 帳目管理頁
    ├─ /settlement → 結算預覽頁
    │
    └─ Notion API
         ├─ DB1: 人員 Master Data（讀 + 結算後寫回）
         └─ DB2: 帳目紀錄（CRUD）
```

### 技術選型

| 層級 | 技術 | 理由 |
|------|------|------|
| 後端框架 | FastAPI | 使用者熟悉 Python，async 支援好 |
| 模板引擎 | Jinja2 | FastAPI 原生支援，SSR 不需前後端分離 |
| 前端增強 | htmx | 局部更新體驗接近 SPA，零 JS 學習成本 |
| CSS | Tailwind CSS (CDN) | Mobile-first，快速開發，不需 build step |
| Notion SDK | notion-client | 官方 Python SDK |
| 部署 | DigitalOcean Droplet | 使用者現有資源 |
| Web Server | Nginx + uvicorn | 反向代理 + ASGI server |

## Notion 資料模型

### DB1：人員 Master Data（既有，需新增欄位）

| 欄位 | 類型 | 來源 | 說明 |
|------|------|------|------|
| 名字 | Title | 既有 | |
| 繳費狀態 | Select | 既有 | 未繳/已繳/部分繳 |
| 分房 | Text/Select | 既有 | 房間編號 |
| 參與標籤 | Multi-select | **新增** | 如「全程」「酒水」，定義哪些帳目要分攤 |
| 應付總額 | Number | **新增，後端寫入** | 結算計算後的總金額 |
| 已付/代墊金額 | Number | **新增，後端寫入** | 此人代墊的總金額 |
| 淨餘額 | Number | **新增，後端寫入** | 正=被欠，負=欠款 |
| 結算指示 | Rich Text | **新增，後端寫入** | 如「轉 $4,660 給 王小明」 |
| 帳目明細 | Rich Text | **新增，後端寫入** | 每筆費用的拆分明細 |

### DB2：帳目紀錄（新建）

| 欄位 | 類型 | 說明 |
|------|------|------|
| 項目名稱 | Title | 如「民宿費」「第一天晚餐」 |
| 類別 | Select | 民宿/餐費/保險/酒水/雜支 |
| 總金額 | Number | 這筆支出的總額 |
| 付款人 | Relation → DB1 | 誰先付的錢 |
| 參與標籤 | Multi-select | 哪些標籤的人要分攤 |
| 日期 | Date | 消費日期 |
| 備註 | Text | 補充說明 |

## 拆帳引擎

### 關鍵規則

- **多標籤語意**：帳目的參與標籤取**聯集（union）**。例如帳目標記「全程」+「酒水」= 擁有「全程」或「酒水」任一標籤的所有人。
- **四捨五入策略**：每人分攤額 = `floor(總金額 / N)`，餘數 `總金額 - floor * N` 歸付款人吸收（付款人少收回這個零頭）。避免累積誤差導致餘額不平衡。
- **付款人也是參與者**：付款人通常也在參與者列表中，淨餘額 = 代墊總額 - 應分攤額，自動正確計算。
- **付款人為必填**：新增帳目時付款人為必填欄位，表單強制驗證。
- **零參與者防護**：若帳目的標籤匹配不到任何人，結算時跳過該筆並在結果中警告。
- **繳費狀態**：DB1 的「繳費狀態」欄位由主辦人手動管理（收到轉帳後手動改為已繳），系統不自動更新此欄位。

### 計算流程

```
1. 讀取 DB2 所有帳目
2. 對每筆帳目：
   a. 讀取帳目的「參與標籤」
   b. 查 DB1 中有任一該標籤的所有人（聯集）→ 得到參與者列表（N 人）
   c. 若 N = 0，跳過此筆並記錄警告
   d. 每人應分攤 = floor(總金額 / N)，餘數歸付款人
   e. 付款人記為 +總金額（他先墊了）
   f. 每位參與者記為 -分攤金額（他們要付這些錢）
3. 彙總每人淨餘額 = 所有代墊金額 - 所有應付金額
4. Greedy 演算法最小化轉帳次數
5. 產生結算指示（A 轉 $X 給 B）
6. 寫回 DB1：應付總額、已付金額、淨餘額、結算指示、帳目明細
```

### Greedy 最小化轉帳演算法

```python
def simplify_debts(balances: dict[str, int]) -> list[dict]:
    """所有金額皆為整數 TWD（floor 後無小數）"""
    debtors = []   # 淨餘額 < 0（欠錢的人）
    creditors = [] # 淨餘額 > 0（被欠的人）

    for person, balance in balances.items():
        if balance < 0:
            debtors.append([person, -balance])
        elif balance > 0:
            creditors.append([person, balance])

    debtors.sort(key=lambda x: -x[1])
    creditors.sort(key=lambda x: -x[1])

    transactions = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1])
        transactions.append({
            "from": debtors[i][0],
            "to": creditors[j][0],
            "amount": amount
        })
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1

    return transactions
```

## 頁面設計

### 共通元素

- **底部 Tab Bar**：人員 / 帳目 / 結算（3 個 tab）
- **設計風格**：Dark Mode（#0F172A 背景），Fira Sans / Fira Code 字型
- **Mobile-first**：375px 基準，觸控目標 >= 44px

### 頁面 1：人員總覽 `/`

- Summary Banner：總人數、帳目數、總費用、繳費進度條
- 快速操作按鈕：同步 Notion / 執行結算
- 人員依狀態分組：「需付款」→「應收回」→「已結清」
- 每人顯示：名字、房間、標籤、淨餘額、轉帳對象
- 點擊展開：帳目明細

### 頁面 2：帳目管理 `/expenses`

- 帳目列表，按日期排序
- 每筆：名稱、類別 icon、總金額、付款人、參與標籤、每人分攤額
- 新增帳目：底部彈出表單（htmx modal）
- 編輯/刪除功能

### 頁面 3：結算預覽 `/settlement`

- 結算前：提示 + 觸發按鈕
- 結算後：每筆轉帳指示（A → B，$金額）
- 「預覽」模式：`POST /api/settle` 計算結果存入 server-side 快取（以 settlement_id 為 key，TTL 30 分鐘，過期需重新計算），前端顯示預覽
- 「寫回 Notion」按鈕：`POST /api/settle/confirm/{settlement_id}` 使用快取中的計算結果（不重新計算）批次更新 DB1，若 settlement_id 已過期則回傳錯誤提示重新結算
- 寫回進度：`GET /api/settle/progress/{settlement_id}` SSE 端點，串流寫回進度（htmx sse extension 接收，即時顯示如「寫入 15/40...」）

## API 設計

### 頁面路由

| Method | Path | 說明 |
|--------|------|------|
| GET | `/` | 人員總覽頁面 |
| GET | `/expenses` | 帳目管理頁面 |
| GET | `/settlement` | 結算預覽頁面 |

### API 路由

| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/sync` | 從 Notion 同步資料到快取 |
| POST | `/api/expenses` | 新增帳目（寫入 DB2） |
| PUT | `/api/expenses/{id}` | 修改帳目 |
| DELETE | `/api/expenses/{id}` | 刪除帳目 |
| POST | `/api/settle` | 執行拆帳計算，回傳 settlement_id + 預覽結果 |
| POST | `/api/settle/confirm/{settlement_id}` | 確認結算，使用快取結果寫回 DB1 |
| GET | `/api/settle/progress/{settlement_id}` | SSE 端點，串流寫回進度 |

### htmx 片段路由

| Method | Path | 說明 |
|--------|------|------|
| GET | `/htmx/members` | 人員列表片段（篩選後局部更新） |
| GET | `/htmx/expense-form` | 新增/編輯帳目表單 |
| GET | `/htmx/settlement` | 結算結果片段 |

## 專案結構

```
tripsplit/
├── main.py                  # FastAPI app 入口
├── config.py                # 設定（Notion token、DB ID）
├── requirements.txt
│
├── routers/
│   ├── pages.py             # 頁面路由
│   └── api.py               # API 路由
│
├── services/
│   ├── notion.py            # Notion API 封裝
│   ├── settlement.py        # 拆帳引擎
│   └── cache.py             # 記憶體快取（TTL 60s）
│
├── templates/
│   ├── base.html            # 共用 layout
│   ├── members.html         # 人員總覽
│   ├── expenses.html        # 帳目管理
│   ├── settlement.html      # 結算預覽
│   └── partials/            # htmx 片段
│       ├── member_list.html
│       ├── expense_form.html
│       └── settlement_result.html
│
└── static/
    └── style.css            # 自訂樣式
```

## 部署

```
DigitalOcean Droplet
├── Nginx（:80/:443，反向代理 + Let's Encrypt SSL）
└── uvicorn main:app（:8000，systemd 管理）
```

### 環境變數（`.env`）

```
NOTION_TOKEN=secret_xxx
NOTION_MEMBERS_DB_ID=xxx
NOTION_EXPENSES_DB_ID=xxx
```

## Notion API 限制與應對

| 限制 | 應對 |
|------|------|
| 3 req/sec | 批次處理 + 間隔 350ms 發送 |
| 每次查詢最多 100 筆 | cursor-based pagination（但 40 人不會超過） |
| Relation 欄位需用 page ID | 啟動時建 name → ID 對照表快取 |
| 完整結算流程約 42 次 API call | 讀取 DB1(1次) + DB2(1次) + 寫回 40 人(40次) = 42 次，以 350ms 間隔約需 15 秒，前端用 SSE 顯示即時進度 |

## 錯誤處理

| 情境 | 處理方式 |
|------|---------|
| Notion API token 失效 | 頁面顯示錯誤提示，引導檢查 .env 設定 |
| 寫回 DB1 部分失敗（rate limit） | 自動重試 3 次（指數退避），仍失敗則記錄已完成/未完成的人員，前端顯示哪些人寫入失敗，提供「重試未完成」按鈕 |
| 帳目標籤匹配不到任何人 | 結算時跳過該筆，結果頁面顯示警告 |
| 帳目缺少付款人 | 表單驗證阻擋，不允許送出 |

## 空狀態設計

| 頁面 | 空狀態 |
|------|--------|
| 人員總覽（無人員） | 提示「尚未從 Notion 同步資料」+ 同步按鈕 |
| 帳目管理（無帳目） | 提示「尚未新增帳目」+ 新增按鈕 |
| 結算預覽（未結算） | 提示「尚未執行結算」+ 觸發結算按鈕 |

## 設計決策記錄

| 決策 | 選擇 | 理由 |
|------|------|------|
| 前後端分離 vs SSR | SSR (Jinja2) | 一次性專案，單一專案更簡單 |
| 前端框架 | htmx + Tailwind | 零 JS 學習成本，Mobile-first |
| 拆帳引擎 | 自建 Greedy | 50 行 Python，不需外部依賴 |
| 資料存儲 | 全 Notion | 使用者已有資料在 Notion，不引入新系統 |
| 導航 | 底部 Tab Bar + Segmented Control | Mobile-first，符合手機操作習慣 |
| 快取 | 記憶體快取 TTL 60s | 減少 Notion API 呼叫次數，「同步 Notion」按鈕會主動清除快取重新拉取 |
| 同步按鈕 | 單向 pull（Notion → 本地快取） | 不會反向推送，避免意外覆蓋 Notion 資料 |
