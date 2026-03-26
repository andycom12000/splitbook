# TripSplit — 40 人出遊拆帳系統設計文件

## 概述

為 40 人出遊團建立一個拆帳管理系統，由主辦人單人操作，主要在手機上使用。系統從 Notion 讀取人員 Master Data，在另一個 Notion DB 記錄帳目，由後端計算拆帳後將結果寫回 Master Data。

## 需求摘要

- **使用者**：僅主辦人一人操作，不需登入/權限系統（部署時以 Nginx basic auth 做最低限度保護）
- **團體規模**：40 人
- **帳目規模**：最多 15 筆
- **幣別**：TWD，所有金額為正整數
- **分攤方式**：依標籤群組均分（同一標籤群組內平均分攤）
- **參與者子集**：透過 Master Data 上的標籤定義（如「全程」「酒水」）
- **代墊處理**：某人先付共同費用，參與者分攤還他
- **結算結果**：寫回 Notion Master Data（欄位 + 留言/描述區的帳目明細）
- **收款**：主辦人手動處理，系統不自動產生收款連結
- **繳費狀態**：由主辦人手動管理，系統不自動更新
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
    └─ Notion API（每次頁面載入直接讀取，不做快取）
         ├─ DB1: 人員 Master Data（讀 + 結算後寫回）
         └─ DB2: 帳目紀錄（CRUD）
```

### 技術選型

| 層級 | 技術 | 理由 |
|------|------|------|
| 後端框架 | FastAPI | 使用者熟悉 Python，async 支援好 |
| 模板引擎 | Jinja2 | SSR，單一專案不需前後端分離 |
| 前端增強 | htmx | 局部更新體驗接近 SPA，零 JS 學習成本 |
| CSS | Tailwind CSS (CDN) | Mobile-first，不需 build step |
| Notion SDK | notion-client | 官方 Python SDK |
| 部署 | DigitalOcean Droplet | Nginx + uvicorn，使用者現有資源 |

## Notion 資料模型

### DB1：人員 Master Data（既有，需新增欄位）

| 欄位 | 類型 | 來源 | 說明 |
|------|------|------|------|
| 名字 | Title | 既有 | |
| 繳費狀態 | Select | 既有 | 未繳/已繳/部分繳（手動管理） |
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
| 總金額 | Number | 正整數，這筆支出的總額 |
| 付款人 | Relation → DB1 | 限單選（Notion 設定 limit 1），誰先付的錢，**必填** |
| 參與標籤 | Multi-select | 哪些標籤的人要分攤（聯集語意） |
| 日期 | Date | 消費日期 |
| 備註 | Text | 補充說明 |

## 拆帳引擎

### 關鍵規則

- **多標籤語意**：帳目的參與標籤取**聯集（union）**。例如帳目標記「全程」+「酒水」= 擁有任一標籤的所有人。
- **四捨五入策略**：每人分攤額 = `floor(總金額 / N)`，餘數歸付款人吸收。
- **付款人也是參與者**：淨餘額 = 代墊總額 - 應分攤額，自動正確計算。
- **零參與者防護**：標籤匹配不到任何人時跳過該筆並警告。
- **總金額驗證**：必須為正整數，表單驗證阻擋。

### 計算流程

```
1. 讀取 DB2 所有帳目（單次查詢，不需分頁，15 筆 << 100 上限）
2. 讀取 DB1 所有人員（單次查詢，40 人 << 100 上限）
3. 對每筆帳目：
   a. 取參與標籤 → 篩選 DB1 中有任一標籤的人（聯集）→ N 人
   b. 若 N = 0，跳過並記錄警告
   c. 每人分攤 = floor(總金額 / N)，餘數歸付款人
   d. 付款人 +總金額，每位參與者 -分攤額
4. 彙總每人淨餘額
5. Greedy 演算法最小化轉帳次數
6. 產生結算指示
```

### Greedy 最小化轉帳演算法

```python
def simplify_debts(balances: dict[str, int]) -> list[dict]:
    """所有金額皆為整數 TWD"""
    debtors = []   # 欠錢的人
    creditors = [] # 被欠的人

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
- 快速操作：執行結算按鈕
- 人員依狀態分組：「需付款」→「應收回」→「已結清」
- 每人顯示：名字、房間、標籤、淨餘額、轉帳對象
- 點擊展開：帳目明細

### 頁面 2：帳目管理 `/expenses`

- 帳目列表，按日期排序
- 每筆：名稱、類別 icon、總金額、付款人、參與標籤、每人分攤額
- 新增帳目：底部彈出表單（htmx modal），付款人為下拉選單（從 DB1 讀取）
- 編輯：`GET /htmx/expense-form?id={expense_id}` 載入預填表單
- 刪除：確認對話框後刪除

### 頁面 3：結算預覽 `/settlement`

- 結算前：提示 + 觸發按鈕
- 結算後：每筆轉帳指示（A → B，$金額）
- 兩步流程：
  1. `POST /api/settle` → 即時計算並回傳預覽結果（頁面顯示）
  2. 確認後 `POST /api/settle/write` → 重新計算並寫回 DB1（計算極快，重算無成本）
- 寫回期間：顯示 loading spinner + 「寫入中，約需 15 秒...」提示

## API 設計

### 頁面路由（SSR，直接從 Notion 讀取資料渲染）

| Method | Path | 說明 |
|--------|------|------|
| GET | `/` | 人員總覽（讀 DB1） |
| GET | `/expenses` | 帳目管理（讀 DB2 + DB1 付款人名稱） |
| GET | `/settlement` | 結算預覽 |

### API 路由

| Method | Path | 說明 |
|--------|------|------|
| POST | `/api/expenses` | 新增帳目（寫入 DB2），必填：名稱、總金額（正整數）、付款人、參與標籤 |
| PUT | `/api/expenses/{id}` | 修改帳目 |
| DELETE | `/api/expenses/{id}` | 刪除帳目 |
| POST | `/api/settle` | 計算拆帳結果，回傳預覽 HTML |
| POST | `/api/settle/write` | 重新計算 + 寫回 DB1（同步，完成後回傳結果） |

### htmx 片段路由

| Method | Path | 說明 |
|--------|------|------|
| GET | `/htmx/members?filter={status}` | 人員列表片段（篩選後局部更新） |
| GET | `/htmx/expense-form` | 新增帳目表單 |
| GET | `/htmx/expense-form?id={id}` | 編輯帳目表單（預填資料） |

## 專案結構

```
tripsplit/
├── main.py                  # FastAPI app 入口
├── config.py                # 設定（Notion token、DB ID）
├── requirements.txt
│
├── routers/
│   ├── pages.py             # 頁面路由（SSR）
│   └── api.py               # API 路由
│
├── services/
│   ├── notion.py            # Notion API 封裝（讀寫 DB1、DB2）
│   └── settlement.py        # 拆帳引擎
│
├── templates/
│   ├── base.html            # 共用 layout（header、bottom tab bar、Tailwind CDN）
│   ├── members.html         # 人員總覽
│   ├── expenses.html        # 帳目管理
│   ├── settlement.html      # 結算預覽
│   └── partials/            # htmx 片段
│       ├── member_list.html
│       └── expense_form.html
│
└── static/
    └── style.css            # 自訂樣式
```

## 部署

```
DigitalOcean Droplet
├── Nginx（:80/:443）
│   ├── Let's Encrypt SSL
│   ├── Basic Auth（帳密保護，防止未授權存取）
│   └── 反向代理 → uvicorn :8000
└── uvicorn main:app（systemd 管理）
```

### 環境變數（`.env`）

```
NOTION_TOKEN=secret_xxx
NOTION_MEMBERS_DB_ID=xxx
NOTION_EXPENSES_DB_ID=xxx
```

## Notion API 注意事項

| 項目 | 說明 |
|------|------|
| Rate limit | 3 req/sec，寫回時間隔 350ms 發送 |
| 查詢上限 | 100 筆/次，40 人 + 15 帳目均不會超過，不需分頁 |
| Relation 欄位 | 寫入時需用 page ID，啟動時建 name → ID 對照表 |
| 寫回耗時 | 40 人 × 350ms ≈ 15 秒，前端顯示 loading 提示 |

## 錯誤處理

| 情境 | 處理方式 |
|------|---------|
| Notion API token 失效 | 頁面顯示錯誤提示，引導檢查 .env 設定 |
| 寫回部分失敗（rate limit） | 單筆自動重試 3 次（指數退避），仍失敗則完成其餘後顯示失敗清單 |
| 帳目標籤匹配不到任何人 | 結算時跳過，結果頁面顯示警告 |
| 帳目缺少付款人或總金額 | 表單前端驗證阻擋 |
| 總金額非正整數 | 表單前端驗證阻擋 |

## 空狀態設計

| 頁面 | 空狀態 |
|------|--------|
| 人員總覽（無人員） | 提示「Notion 資料庫中尚無人員資料」 |
| 帳目管理（無帳目） | 提示「尚未新增帳目」+ 新增按鈕 |
| 結算預覽（未結算） | 提示「點擊下方按鈕執行結算」+ 結算按鈕 |
