# SplitBook（一般化拆帳軟體）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 tripsplit 的架構缺陷重構為一般化拆帳軟體 SplitBook：分錄式帳本（守恆不變量）、SQLite 儲存、可插拔分攤規則、結算快照與單一對帳語意、5 人內成員身分（PIN 登入）與多帳本。

**Architecture:** 全新套件 `splitbook/`（不修改 `tripsplit/`）。三層：`domain/`（純函數帳本核心，無 I/O）、`storage/`（SQLite repository，分錄不可變於寫入時固化分攤）、`web/`（FastAPI + Jinja2 薄路由層）。付款（結算轉帳）本身就是帳本分錄，因此餘額永遠自洽；結算快照凍結轉帳方案，對帳 = 快照方案 vs 快照後的結算轉帳，只有一份語意。

**Tech Stack:** Python 3.11+、FastAPI、Jinja2、python-multipart、sqlite3（stdlib，無 ORM）、pytest、httpx（TestClient 用）。

## Global Constraints

- 所有金額為**整數 TWD**（`int`），不使用 float 儲存金額。
- **守恆不變量**：任何時點 Σnet = 0；每筆支出的分攤總和 = 支出總額。違反即 raise `LedgerImbalance`，不得無聲吞掉。
- 分錄採**軟刪除**（`deleted_at`），保留審計軌跡並支援快照過期偵測。
- **不修改 `tripsplit/` 目錄**下任何檔案。
- 依賴僅限：`fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `pytest`, `httpx`。不引入 ORM、不引入 Notion SDK。
- 測試一律從 **repo root** 執行：`python -m pytest splitbook/tests -v`。
- import 一律用絕對路徑：`from splitbook.domain.split import split_equal`。
- 環境變數：`SPLITBOOK_DB`（預設 `splitbook.db`）、`SPLITBOOK_SECRET`（預設 `dev-secret-change-me`）。
- Commit 訊息用 conventional commits（`feat:`/`test:`/`docs:`），結尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## 領域詞彙（所有程式碼與 UI 文案一致使用）

| 中文 | 程式名稱 | 說明 |
|------|---------|------|
| 帳本 | Group | 一次旅程/一個分帳群組，所有資料的容器 |
| 成員 | Member | 帳本內的人，≤5 人，可設 PIN 登入 |
| 分錄 | Entry | 帳本內一筆紀錄，kind = `expense`（支出）或 `transfer`（轉帳） |
| 分攤 | Allocation | 支出在寫入時固化的每人分攤額（不隨主檔變動） |
| 分攤規則 | split policy | `equal`（均分）/ `weights`（權重）/ `exact`（指定金額） |
| 轉帳類型 | transfer_kind | `prepay`（預付/代墊還款）/ `settlement`（結算轉帳） |
| 結算快照 | Snapshot | 凍結某時點的轉帳方案（誰轉給誰多少），付款對準它 |
| 對帳 | reconcile | 快照方案 vs 實際結算轉帳的比對，支援部分付款 |
| 淨額 | net | `advanced + sent - received - share`，正 = 應收回，負 = 應付 |

## 檔案結構

```
splitbook/
├── __init__.py
├── requirements.txt
├── domain/
│   ├── __init__.py
│   ├── split.py          # 分攤規則（純函數）
│   ├── ledger.py         # Entry/Balance 模型、compute_balances、simplify_debts
│   └── reconcile.py      # 快照對帳（唯一一份對帳語意）
├── storage/
│   ├── __init__.py
│   ├── db.py             # 連線工廠 + schema
│   └── repo.py           # Repo：groups/members/entries/snapshots
├── web/
│   ├── __init__.py
│   ├── auth.py           # PIN 雜湊 + signed cookie token
│   ├── app.py            # create_app 工廠
│   ├── routes.py         # 全部路由（薄：解析表單 → repo/domain → 模板）
│   ├── templates/        # base/setup/login/home/expenses/transfers/settlement
│   └── static/style.css
└── tests/
    ├── __init__.py
    ├── test_split.py
    ├── test_ledger.py
    ├── test_reconcile.py
    ├── test_repo.py
    ├── test_auth.py
    └── test_web.py
```

執行順序：Task 1→2（domain 核心）→ 3→4→5（storage）→ 6（對帳）→ 7（auth）→ 8→11（web）→ 12（收尾）。Task 1、3、7 彼此獨立可並行。

---

### Task 1: 分攤規則模組 `domain/split.py`

**Files:**
- Create: `splitbook/__init__.py`（空檔）
- Create: `splitbook/domain/__init__.py`（空檔）
- Create: `splitbook/tests/__init__.py`（空檔）
- Create: `splitbook/domain/split.py`
- Test: `splitbook/tests/test_split.py`

**Interfaces:**
- Consumes: 無（純函數，stdlib only）
- Produces:
  - `class SplitError(ValueError)`
  - `split_equal(amount: int, participant_ids: list[int], payer_id: int | None = None) -> dict[int, int]`
  - `split_weights(amount: int, weights: dict[int, int]) -> dict[int, int]`
  - `split_exact(amount: int, amounts: dict[int, int]) -> dict[int, int]`
  - 三者回傳值保證：`sum(result.values()) == amount`

**尾差規則（必須照此實作，這是對 tripsplit 缺陷 5 的修正）：**
- `split_equal`：每人 `amount // n`（floor），餘數每人 +1，從「排序後成員名單中付款人的**下一位**」開始輪流分配；付款人不在參與者中則從名單第一位開始。
- `split_weights`：整數最大餘數法——基額 `(amount*w)//W`，餘數依 `(amount*w) % W` 由大到小分配，同分依成員 id 小者優先。全程整數運算，不用 float。

- [ ] **Step 1: 寫失敗測試**

```python
# splitbook/tests/test_split.py
import pytest
from splitbook.domain.split import SplitError, split_equal, split_weights, split_exact


def test_equal_exact_division():
    assert split_equal(300, [1, 2, 3]) == {1: 100, 2: 100, 3: 100}


def test_equal_remainder_starts_after_payer():
    # 100 / 3 = 33 餘 1；付款人是 1，餘數從下一位（2）開始分
    assert split_equal(100, [1, 2, 3], payer_id=1) == {1: 33, 2: 34, 3: 33}
    # 付款人是 3（排序後最後一位），餘數繞回第一位
    assert split_equal(100, [1, 2, 3], payer_id=3) == {1: 34, 2: 33, 3: 33}


def test_equal_remainder_two_extra():
    # 200 / 3 = 66 餘 2；付款人 1 → 2 和 3 各 +1
    assert split_equal(200, [1, 2, 3], payer_id=1) == {1: 66, 2: 67, 3: 67}


def test_equal_payer_not_participant():
    # 付款人不參與 → 從名單第一位開始
    assert split_equal(100, [2, 3, 4], payer_id=9) == {2: 34, 3: 33, 4: 33}


def test_equal_negative_amount_refund():
    # 退款：-100 / 3，總和必須仍為 -100
    result = split_equal(-100, [1, 2, 3], payer_id=1)
    assert sum(result.values()) == -100


def test_equal_conservation_property():
    # 守恆性質：任意金額與人數，總和恆等於 amount
    for amount in [1, 7, 99, 100, 101, 12345, -37]:
        for n in range(1, 6):
            ids = list(range(1, n + 1))
            assert sum(split_equal(amount, ids, payer_id=1).values()) == amount


def test_equal_rejects_empty_and_duplicates():
    with pytest.raises(SplitError):
        split_equal(100, [])
    with pytest.raises(SplitError):
        split_equal(100, [1, 1, 2])


def test_weights_basic():
    # 100 依 2:1:1 → 50/25/25
    assert split_weights(100, {1: 2, 2: 1, 3: 1}) == {1: 50, 2: 25, 3: 25}


def test_weights_largest_remainder():
    # 100 依 1:1:1 → 各 33.33...，餘 1 給小數部分最大者；全部同分 → id 最小者
    assert split_weights(100, {1: 1, 2: 1, 3: 1}) == {1: 34, 2: 33, 3: 33}


def test_weights_conservation():
    for amount in [1, 100, 999, 12345]:
        result = split_weights(amount, {1: 3, 2: 2, 3: 5, 4: 1})
        assert sum(result.values()) == amount


def test_weights_rejects_nonpositive():
    with pytest.raises(SplitError):
        split_weights(100, {1: 0, 2: 1})
    with pytest.raises(SplitError):
        split_weights(100, {})


def test_exact_valid():
    assert split_exact(100, {1: 60, 2: 40}) == {1: 60, 2: 40}


def test_exact_sum_mismatch_rejected():
    with pytest.raises(SplitError):
        split_exact(100, {1: 60, 2: 50})
    with pytest.raises(SplitError):
        split_exact(100, {})
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_split.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'splitbook.domain.split'`）

- [ ] **Step 3: 實作**

```python
# splitbook/domain/split.py
"""分攤規則：所有函數保證 sum(result.values()) == amount（守恆）。"""


class SplitError(ValueError):
    """分攤規則的輸入無效。"""


def split_equal(
    amount: int, participant_ids: list[int], payer_id: int | None = None
) -> dict[int, int]:
    """均分。餘數每人 +1，從排序後名單中付款人的下一位開始輪流分配。"""
    if not participant_ids:
        raise SplitError("至少需要一位參與者")
    if len(set(participant_ids)) != len(participant_ids):
        raise SplitError("參與者重複")
    ids = sorted(participant_ids)
    n = len(ids)
    base = amount // n  # floor division，負數金額（退款）同樣成立
    remainder = amount - base * n  # 0 <= remainder < n
    start = (ids.index(payer_id) + 1) % n if payer_id in ids else 0
    result = {pid: base for pid in ids}
    for k in range(remainder):
        result[ids[(start + k) % n]] += 1
    return result


def split_weights(amount: int, weights: dict[int, int]) -> dict[int, int]:
    """依權重分攤，整數最大餘數法（不經過 float）。"""
    if not weights:
        raise SplitError("至少需要一位參與者")
    if any(w <= 0 for w in weights.values()):
        raise SplitError("權重必須為正整數")
    total_w = sum(weights.values())
    result = {pid: (amount * w) // total_w for pid, w in weights.items()}
    remainder = amount - sum(result.values())
    order = sorted(weights, key=lambda pid: (-((amount * weights[pid]) % total_w), pid))
    for k in range(remainder):
        result[order[k]] += 1
    return result


def split_exact(amount: int, amounts: dict[int, int]) -> dict[int, int]:
    """指定每人金額，總和必須等於總額。"""
    if not amounts:
        raise SplitError("至少需要一位參與者")
    total = sum(amounts.values())
    if total != amount:
        raise SplitError(f"分攤總和 {total} 不等於總金額 {amount}")
    return dict(amounts)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_split.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/
git commit -m "feat(splitbook): add split policies with explainable remainder rules"
```

### Task 2: 帳本核心 `domain/ledger.py`

**Files:**
- Create: `splitbook/domain/ledger.py`
- Test: `splitbook/tests/test_ledger.py`

**Interfaces:**
- Consumes: 無（純函數）
- Produces:
  - `class LedgerImbalance(Exception)` — 帳不平衡時 raise，永不無聲吞掉
  - `@dataclass(frozen=True) Entry`: 欄位 `id: int, kind: str, name: str, amount: int, payer_id: int, allocations: dict[int, int] (預設空), payee_id: int | None = None, transfer_kind: str = "", category: str = "", date: str = "", note: str = "", created_by: int | None = None, snapshot_id: int | None = None`
  - `@dataclass Balance`: 欄位 `advanced: int = 0, share: int = 0, sent: int = 0, received: int = 0`；property `net = advanced + sent - received - share`
  - `@dataclass(frozen=True) SettlementLine`: 欄位 `from_id: int, to_id: int, amount: int`
  - `compute_balances(member_ids: set[int], entries: list[Entry]) -> dict[int, Balance]`
  - `simplify_debts(nets: dict[int, int]) -> list[SettlementLine]`

**會計規則（修正 tripsplit 缺陷 1）：** 支出的付款人或分攤對象不在成員名單中 → raise `LedgerImbalance`（tripsplit 是無聲跳過導致 Σnet ≠ 0）。分攤總和 ≠ 支出總額 → raise。最後防線：Σnet ≠ 0 → raise。

- [ ] **Step 1: 寫失敗測試**

```python
# splitbook/tests/test_ledger.py
import pytest
from splitbook.domain.ledger import (
    Balance, Entry, LedgerImbalance, SettlementLine,
    compute_balances, simplify_debts,
)


def exp(id, name, amount, payer_id, allocations):
    return Entry(id=id, kind="expense", name=name, amount=amount,
                 payer_id=payer_id, allocations=allocations)


def txf(id, amount, from_id, to_id, transfer_kind="prepay"):
    return Entry(id=id, kind="transfer", name="轉帳", amount=amount,
                 payer_id=from_id, payee_id=to_id, transfer_kind=transfer_kind)


def test_single_expense_balances():
    b = compute_balances({1, 2, 3}, [exp(1, "民宿", 300, 1, {1: 100, 2: 100, 3: 100})])
    assert b[1].advanced == 300 and b[1].share == 100 and b[1].net == 200
    assert b[2].net == -100 and b[3].net == -100
    assert sum(x.net for x in b.values()) == 0


def test_transfer_reduces_debt():
    entries = [
        exp(1, "民宿", 6000, 1, {1: 3000, 2: 3000}),
        txf(2, 2300, from_id=2, to_id=1),
    ]
    b = compute_balances({1, 2}, entries)
    assert b[1].net == 700 and b[2].net == -700


def test_settlement_transfer_also_counts():
    # 結算轉帳就是分錄：付清後 Σnet 歸零、雙方歸零
    entries = [
        exp(1, "餐", 100, 1, {1: 50, 2: 50}),
        txf(2, 50, from_id=2, to_id=1, transfer_kind="settlement"),
    ]
    b = compute_balances({1, 2}, entries)
    assert b[1].net == 0 and b[2].net == 0


def test_unknown_payer_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({2, 3}, [exp(1, "民宿", 300, 1, {2: 150, 3: 150})])


def test_unknown_allocation_member_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({1, 2}, [exp(1, "民宿", 300, 1, {1: 150, 9: 150})])


def test_allocation_sum_mismatch_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({1, 2}, [exp(1, "民宿", 300, 1, {1: 150, 2: 100})])


def test_transfer_unknown_member_raises():
    with pytest.raises(LedgerImbalance):
        compute_balances({1}, [txf(1, 100, from_id=1, to_id=9)])


def test_simplify_debts_basic():
    assert simplify_debts({1: -100, 2: 100}) == [SettlementLine(1, 2, 100)]


def test_simplify_debts_three_people():
    assert simplify_debts({1: -200, 2: 120, 3: 80}) == [
        SettlementLine(1, 2, 120),
        SettlementLine(1, 3, 80),
    ]


def test_simplify_debts_zero_excluded():
    assert simplify_debts({1: -100, 2: 100, 3: 0}) == [SettlementLine(1, 2, 100)]
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_ledger.py -v`
Expected: FAIL（module not found）

- [ ] **Step 3: 實作**

```python
# splitbook/domain/ledger.py
"""帳本核心：餘額計算與轉帳最小化。守恆不變量在此強制執行。"""
from dataclasses import dataclass, field


class LedgerImbalance(Exception):
    """帳本不平衡：分攤總和錯誤、成員不明、或 Σnet != 0。"""


@dataclass(frozen=True)
class Entry:
    id: int
    kind: str                 # 'expense' | 'transfer'
    name: str
    amount: int
    payer_id: int             # expense=付款人；transfer=轉出方
    allocations: dict[int, int] = field(default_factory=dict)  # expense 專用
    payee_id: int | None = None       # transfer 專用
    transfer_kind: str = ""           # 'prepay' | 'settlement'
    category: str = ""
    date: str = ""
    note: str = ""
    created_by: int | None = None
    snapshot_id: int | None = None    # settlement 轉帳對準的快照


@dataclass
class Balance:
    advanced: int = 0    # 代墊（支出付款總額）
    share: int = 0       # 應分攤總額
    sent: int = 0        # 轉出總額
    received: int = 0    # 轉入總額

    @property
    def net(self) -> int:
        return self.advanced + self.sent - self.received - self.share


@dataclass(frozen=True)
class SettlementLine:
    from_id: int
    to_id: int
    amount: int


def compute_balances(member_ids: set[int], entries: list[Entry]) -> dict[int, Balance]:
    balances = {mid: Balance() for mid in member_ids}
    for e in entries:
        if e.kind == "expense":
            if e.payer_id not in balances:
                raise LedgerImbalance(f"分錄「{e.name}」的付款人 {e.payer_id} 不在成員名單中")
            unknown = set(e.allocations) - member_ids
            if unknown:
                raise LedgerImbalance(f"分錄「{e.name}」的分攤對象 {unknown} 不在成員名單中")
            alloc_sum = sum(e.allocations.values())
            if alloc_sum != e.amount:
                raise LedgerImbalance(
                    f"分錄「{e.name}」分攤總和 {alloc_sum} != 總金額 {e.amount}")
            balances[e.payer_id].advanced += e.amount
            for mid, a in e.allocations.items():
                balances[mid].share += a
        elif e.kind == "transfer":
            if e.payer_id not in balances or e.payee_id not in balances:
                raise LedgerImbalance(f"轉帳分錄 {e.id} 的成員不在名單中")
            balances[e.payer_id].sent += e.amount
            balances[e.payee_id].received += e.amount
        else:
            raise LedgerImbalance(f"未知的分錄類型 {e.kind!r}")
    total = sum(b.net for b in balances.values())
    if total != 0:
        raise LedgerImbalance(f"帳本不平衡：Σnet = {total}")
    return balances


def simplify_debts(nets: dict[int, int]) -> list[SettlementLine]:
    """Greedy 最小化轉帳次數。輸入為每人淨額（正=應收回，負=應付）。"""
    debtors = sorted(
        ([mid, -n] for mid, n in nets.items() if n < 0), key=lambda x: -x[1])
    creditors = sorted(
        ([mid, n] for mid, n in nets.items() if n > 0), key=lambda x: -x[1])
    lines: list[SettlementLine] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1])
        lines.append(SettlementLine(debtors[i][0], creditors[j][0], amount))
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return lines
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_ledger.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/domain/ledger.py splitbook/tests/test_ledger.py
git commit -m "feat(splitbook): add ledger core with conservation invariants"
```

---

### Task 3: SQLite schema 與連線 `storage/db.py`

**Files:**
- Create: `splitbook/storage/__init__.py`（空檔）
- Create: `splitbook/storage/db.py`
- Test: `splitbook/tests/test_repo.py`（本 task 先放 schema 測試）

**Interfaces:**
- Consumes: 無
- Produces:
  - `connect(path: str) -> sqlite3.Connection`（`:memory:` 可用於測試；`row_factory = sqlite3.Row`、`PRAGMA foreign_keys = ON`）
  - `init_db(conn: sqlite3.Connection) -> None`（idempotent，`CREATE TABLE IF NOT EXISTS`）

**Schema 設計要點：** `entries.rev` 是帳本內單調遞增的修訂序號（insert/update/soft-delete 都會取號），快照存 `through_rev`，過期偵測 = 是否存在非結算分錄 `rev > through_rev`。這取代不可靠的 timestamp 比較。

- [ ] **Step 1: 寫失敗測試**

```python
# splitbook/tests/test_repo.py
import pytest
from splitbook.storage.db import connect, init_db


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    yield c
    c.close()


def test_schema_tables_exist(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {"groups", "members", "entries", "allocations",
            "snapshots", "snapshot_lines"} <= names


def test_foreign_keys_enforced(conn):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO members (group_id, name) VALUES (999, 'x')")


def test_init_db_idempotent(conn):
    init_db(conn)  # 不應 raise
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_repo.py -v`
Expected: FAIL（module not found）

- [ ] **Step 3: 實作**

```python
# splitbook/storage/db.py
"""SQLite 連線工廠與 schema。"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    name TEXT NOT NULL,
    pin_hash TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (group_id, name)
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    rev INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('expense', 'transfer')),
    name TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount != 0),
    payer_id INTEGER NOT NULL REFERENCES members(id),
    payee_id INTEGER REFERENCES members(id),
    transfer_kind TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL DEFAULT (date('now', 'localtime')),
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER REFERENCES members(id),
    snapshot_id INTEGER REFERENCES snapshots(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS allocations (
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id),
    amount INTEGER NOT NULL,
    PRIMARY KEY (entry_id, member_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id),
    through_rev INTEGER NOT NULL,
    created_by INTEGER REFERENCES members(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS snapshot_lines (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    from_member INTEGER NOT NULL REFERENCES members(id),
    to_member INTEGER NOT NULL REFERENCES members(id),
    amount INTEGER NOT NULL CHECK (amount > 0),
    PRIMARY KEY (snapshot_id, from_member, to_member)
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_repo.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/storage/ splitbook/tests/test_repo.py
git commit -m "feat(splitbook): add sqlite schema with revision tracking"
```

### Task 4: Repository — 帳本/成員/分錄 `storage/repo.py`

**Files:**
- Create: `splitbook/storage/repo.py`
- Test: `splitbook/tests/test_repo.py`（追加）

**Interfaces:**
- Consumes: `splitbook.storage.db.connect/init_db`、`splitbook.domain.ledger.Entry`
- Produces（class `Repo`，建構子 `Repo(conn: sqlite3.Connection)`）：
  - `create_group(name: str) -> int`；`list_groups() -> list[sqlite3.Row]`；`get_group(group_id: int) -> sqlite3.Row | None`
  - `add_member(group_id: int, name: str) -> int`；`list_members(group_id: int, include_inactive: bool = False) -> list[sqlite3.Row]`；`get_member(member_id: int) -> sqlite3.Row | None`
  - `set_pin_hash(member_id: int, pin_hash: str) -> None`；`set_member_active(member_id: int, active: bool) -> None`
  - `record_expense(group_id, name, amount, payer_id, allocations: dict[int, int], category="", date="", note="", created_by=None) -> int`
  - `record_transfer(group_id, amount, from_id, to_id, transfer_kind, name="轉帳", date="", note="", created_by=None, snapshot_id=None) -> int`
  - `update_expense(entry_id, name, amount, payer_id, allocations, category="", date="", note="") -> None`
  - `soft_delete_entry(entry_id: int) -> None`
  - `list_entries(group_id: int) -> list[Entry]`（排除已刪除，依 id 排序）
  - `get_entry(entry_id: int) -> Entry | None`

**規則：** `record_expense`/`update_expense` 在寫入前驗證 `sum(allocations) == amount`，不符 raise `ValueError`（分攤在寫入時固化 —— 修正 tripsplit 缺陷 2）。所有寫入操作在同一交易內取得新 `rev`（`MAX(rev)+1`）。

- [ ] **Step 1: 寫失敗測試（追加到 test_repo.py）**

```python
# 追加到 splitbook/tests/test_repo.py
from splitbook.storage.repo import Repo


@pytest.fixture
def repo(conn):
    return Repo(conn)


@pytest.fixture
def group(repo):
    gid = repo.create_group("沖繩行")
    a = repo.add_member(gid, "小明")
    b = repo.add_member(gid, "小華")
    c = repo.add_member(gid, "小美")
    return {"gid": gid, "a": a, "b": b, "c": c}


def test_group_and_members(repo, group):
    assert repo.get_group(group["gid"])["name"] == "沖繩行"
    members = repo.list_members(group["gid"])
    assert [m["name"] for m in members] == ["小明", "小華", "小美"]


def test_record_expense_freezes_allocations(repo, group):
    g = group
    eid = repo.record_expense(
        g["gid"], "民宿", 300, g["a"],
        {g["a"]: 100, g["b"]: 100, g["c"]: 100}, category="住宿")
    entries = repo.list_entries(g["gid"])
    assert len(entries) == 1
    e = entries[0]
    assert e.kind == "expense" and e.amount == 300
    assert e.allocations == {g["a"]: 100, g["b"]: 100, g["c"]: 100}
    assert e.id == eid


def test_record_expense_rejects_bad_allocation_sum(repo, group):
    g = group
    with pytest.raises(ValueError):
        repo.record_expense(g["gid"], "民宿", 300, g["a"],
                            {g["a"]: 100, g["b"]: 100})


def test_update_expense_replaces_allocations(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "餐費", 300, g["a"],
                              {g["a"]: 150, g["b"]: 150})
    repo.update_expense(eid, "餐費(改)", 200, g["b"],
                        {g["b"]: 100, g["c"]: 100})
    e = repo.get_entry(eid)
    assert e.name == "餐費(改)" and e.amount == 200 and e.payer_id == g["b"]
    assert e.allocations == {g["b"]: 100, g["c"]: 100}


def test_soft_delete_hides_entry(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "餐費", 100, g["a"], {g["a"]: 100})
    repo.soft_delete_entry(eid)
    assert repo.list_entries(g["gid"]) == []
    # 底層資料仍在（審計軌跡）
    row = repo.conn.execute(
        "SELECT deleted_at FROM entries WHERE id = ?", (eid,)).fetchone()
    assert row["deleted_at"] is not None


def test_rev_increments_on_every_write(repo, group):
    g = group
    e1 = repo.record_expense(g["gid"], "a", 100, g["a"], {g["a"]: 100})
    e2 = repo.record_transfer(g["gid"], 50, g["b"], g["a"], "prepay")
    revs = [r["rev"] for r in repo.conn.execute(
        "SELECT rev FROM entries ORDER BY id").fetchall()]
    assert revs == [1, 2]
    repo.soft_delete_entry(e1)
    row = repo.conn.execute(
        "SELECT rev FROM entries WHERE id = ?", (e1,)).fetchone()
    assert row["rev"] == 3


def test_transfer_roundtrip(repo, group):
    g = group
    repo.record_transfer(g["gid"], 2300, g["b"], g["a"], "prepay", note="先繳")
    e = repo.list_entries(g["gid"])[0]
    assert e.kind == "transfer" and e.payer_id == g["b"] and e.payee_id == g["a"]
    assert e.transfer_kind == "prepay" and e.amount == 2300
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_repo.py -v`
Expected: 新測試 FAIL（`ImportError`）

- [ ] **Step 3: 實作**

```python
# splitbook/storage/repo.py
"""Repository：所有 SQLite 存取集中於此。寫入時固化分攤、單調 rev 序號。"""
import sqlite3
from dataclasses import dataclass

from splitbook.domain.ledger import Entry, SettlementLine


@dataclass(frozen=True)
class Snapshot:
    id: int
    group_id: int
    through_rev: int
    created_by: int | None
    created_at: str
    lines: list[SettlementLine]


class Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -- groups -------------------------------------------------------
    def create_group(self, name: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO groups (name) VALUES (?)", (name,))
        return cur.lastrowid

    def list_groups(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM groups ORDER BY id").fetchall()

    def get_group(self, group_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()

    # -- members ------------------------------------------------------
    def add_member(self, group_id: int, name: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO members (group_id, name) VALUES (?, ?)",
                (group_id, name))
        return cur.lastrowid

    def list_members(self, group_id: int,
                     include_inactive: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM members WHERE group_id = ?"
        if not include_inactive:
            sql += " AND active = 1"
        return self.conn.execute(sql + " ORDER BY id", (group_id,)).fetchall()

    def get_member(self, member_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)).fetchone()

    def set_pin_hash(self, member_id: int, pin_hash: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE members SET pin_hash = ? WHERE id = ?",
                (pin_hash, member_id))

    def set_member_active(self, member_id: int, active: bool) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE members SET active = ? WHERE id = ?",
                (1 if active else 0, member_id))

    # -- entries ------------------------------------------------------
    def _next_rev(self, group_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(rev), 0) + 1 AS r FROM entries WHERE group_id = ?",
            (group_id,)).fetchone()
        return row["r"]

    def record_expense(self, group_id: int, name: str, amount: int,
                       payer_id: int, allocations: dict[int, int],
                       category: str = "", date: str = "", note: str = "",
                       created_by: int | None = None) -> int:
        if sum(allocations.values()) != amount:
            raise ValueError(
                f"分攤總和 {sum(allocations.values())} 不等於總金額 {amount}")
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO entries
                   (group_id, rev, kind, name, amount, payer_id, category,
                    date, note, created_by)
                   VALUES (?, ?, 'expense', ?, ?, ?, ?,
                           COALESCE(?, date('now', 'localtime')), ?, ?)""",
                (group_id, self._next_rev(group_id), name, amount, payer_id,
                 category, date or None, note, created_by))
            eid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO allocations (entry_id, member_id, amount) VALUES (?, ?, ?)",
                [(eid, mid, a) for mid, a in allocations.items()])
        return eid

    def record_transfer(self, group_id: int, amount: int, from_id: int,
                        to_id: int, transfer_kind: str, name: str = "轉帳",
                        date: str = "", note: str = "",
                        created_by: int | None = None,
                        snapshot_id: int | None = None) -> int:
        if amount <= 0:
            raise ValueError("轉帳金額必須為正整數")
        if from_id == to_id:
            raise ValueError("轉出方與轉入方不可相同")
        with self.conn:
            cur = self.conn.execute(
                """INSERT INTO entries
                   (group_id, rev, kind, name, amount, payer_id, payee_id,
                    transfer_kind, date, note, created_by, snapshot_id)
                   VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?,
                           COALESCE(?, date('now', 'localtime')), ?, ?, ?)""",
                (group_id, self._next_rev(group_id), name, amount, from_id,
                 to_id, transfer_kind, date or None, note, created_by,
                 snapshot_id))
        return cur.lastrowid

    def update_expense(self, entry_id: int, name: str, amount: int,
                       payer_id: int, allocations: dict[int, int],
                       category: str = "", date: str = "",
                       note: str = "") -> None:
        if sum(allocations.values()) != amount:
            raise ValueError(
                f"分攤總和 {sum(allocations.values())} 不等於總金額 {amount}")
        row = self.conn.execute(
            "SELECT group_id, kind, deleted_at FROM entries WHERE id = ?",
            (entry_id,)).fetchone()
        if row is None or row["kind"] != "expense" or row["deleted_at"]:
            raise ValueError(f"找不到可編輯的支出分錄 {entry_id}")
        with self.conn:
            self.conn.execute(
                """UPDATE entries SET rev = ?, name = ?, amount = ?,
                   payer_id = ?, category = ?, note = ?,
                   date = COALESCE(?, date)
                   WHERE id = ?""",
                (self._next_rev(row["group_id"]), name, amount, payer_id,
                 category, note, date or None, entry_id))
            self.conn.execute(
                "DELETE FROM allocations WHERE entry_id = ?", (entry_id,))
            self.conn.executemany(
                "INSERT INTO allocations (entry_id, member_id, amount) VALUES (?, ?, ?)",
                [(entry_id, mid, a) for mid, a in allocations.items()])

    def soft_delete_entry(self, entry_id: int) -> None:
        row = self.conn.execute(
            "SELECT group_id, deleted_at FROM entries WHERE id = ?",
            (entry_id,)).fetchone()
        if row is None or row["deleted_at"]:
            raise ValueError(f"找不到分錄 {entry_id}")
        with self.conn:
            self.conn.execute(
                """UPDATE entries SET rev = ?,
                   deleted_at = datetime('now', 'localtime')
                   WHERE id = ?""",
                (self._next_rev(row["group_id"]), entry_id))

    def _rows_to_entries(self, rows: list[sqlite3.Row]) -> list[Entry]:
        expense_ids = [r["id"] for r in rows if r["kind"] == "expense"]
        alloc_map: dict[int, dict[int, int]] = {eid: {} for eid in expense_ids}
        if expense_ids:
            ph = ",".join("?" * len(expense_ids))
            for a in self.conn.execute(
                    f"SELECT * FROM allocations WHERE entry_id IN ({ph})",
                    expense_ids):
                alloc_map[a["entry_id"]][a["member_id"]] = a["amount"]
        return [Entry(
            id=r["id"], kind=r["kind"], name=r["name"], amount=r["amount"],
            payer_id=r["payer_id"], payee_id=r["payee_id"],
            allocations=alloc_map.get(r["id"], {}),
            transfer_kind=r["transfer_kind"], category=r["category"],
            date=r["date"], note=r["note"], created_by=r["created_by"],
            snapshot_id=r["snapshot_id"]) for r in rows]

    def list_entries(self, group_id: int) -> list[Entry]:
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE group_id = ? AND deleted_at IS NULL "
            "ORDER BY id", (group_id,)).fetchall()
        return self._rows_to_entries(rows)

    def get_entry(self, entry_id: int) -> Entry | None:
        row = self.conn.execute(
            "SELECT * FROM entries WHERE id = ? AND deleted_at IS NULL",
            (entry_id,)).fetchone()
        if row is None:
            return None
        return self._rows_to_entries([row])[0]
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_repo.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/storage/repo.py splitbook/tests/test_repo.py
git commit -m "feat(splitbook): add repository with frozen allocations and soft delete"
```

### Task 5: Repository — 結算快照與付款 `storage/repo.py`（追加）

**Files:**
- Modify: `splitbook/storage/repo.py`（在 `Repo` class 內追加方法；`Snapshot` dataclass 已在 Task 4 定義）
- Test: `splitbook/tests/test_repo.py`（追加）

**Interfaces:**
- Consumes: Task 4 的 `Repo`、`Snapshot`、`SettlementLine`
- Produces（追加到 `Repo`）：
  - `create_snapshot(group_id: int, lines: list[SettlementLine], created_by: int | None = None) -> int` — `through_rev` 自動取該帳本目前 `MAX(rev)`
  - `latest_snapshot(group_id: int) -> Snapshot | None`（含 lines）
  - `snapshot_is_stale(snapshot: Snapshot) -> bool` — 存在**非結算轉帳**分錄 `rev > through_rev` 即過期（新增/編輯/刪除都會取新 rev，所以全部偵測得到；結算轉帳本身不使快照過期）
  - `payments_for_snapshot(snapshot_id: int) -> list[Entry]`（未刪除的 settlement 轉帳）

- [ ] **Step 1: 寫失敗測試（追加到 test_repo.py）**

```python
# 追加到 splitbook/tests/test_repo.py
from splitbook.domain.ledger import SettlementLine


def test_snapshot_lifecycle(repo, group):
    g = group
    repo.record_expense(g["gid"], "民宿", 300, g["a"],
                        {g["a"]: 100, g["b"]: 100, g["c"]: 100})
    lines = [SettlementLine(g["b"], g["a"], 100),
             SettlementLine(g["c"], g["a"], 100)]
    sid = repo.create_snapshot(g["gid"], lines, created_by=g["a"])
    snap = repo.latest_snapshot(g["gid"])
    assert snap.id == sid and snap.created_by == g["a"]
    assert set(snap.lines) == set(lines)
    assert repo.snapshot_is_stale(snap) is False


def test_snapshot_stale_after_expense_change(repo, group):
    g = group
    eid = repo.record_expense(g["gid"], "民宿", 300, g["a"],
                              {g["a"]: 100, g["b"]: 100, g["c"]: 100})
    sid = repo.create_snapshot(g["gid"], [SettlementLine(g["b"], g["a"], 100)])
    snap = repo.latest_snapshot(g["gid"])
    repo.soft_delete_entry(eid)  # 快照後修改帳目 → 過期
    assert repo.snapshot_is_stale(snap) is True


def test_settlement_payment_does_not_stale_snapshot(repo, group):
    g = group
    repo.record_expense(g["gid"], "民宿", 200, g["a"],
                        {g["a"]: 100, g["b"]: 100})
    sid = repo.create_snapshot(g["gid"], [SettlementLine(g["b"], g["a"], 100)])
    snap = repo.latest_snapshot(g["gid"])
    repo.record_transfer(g["gid"], 100, g["b"], g["a"], "settlement",
                         snapshot_id=sid)
    assert repo.snapshot_is_stale(snap) is False
    payments = repo.payments_for_snapshot(sid)
    assert len(payments) == 1 and payments[0].amount == 100


def test_latest_snapshot_returns_newest(repo, group):
    g = group
    repo.record_expense(g["gid"], "x", 100, g["a"], {g["a"]: 100})
    s1 = repo.create_snapshot(g["gid"], [])
    s2 = repo.create_snapshot(g["gid"], [])
    assert repo.latest_snapshot(g["gid"]).id == s2


def test_latest_snapshot_none_when_empty(repo, group):
    assert repo.latest_snapshot(group["gid"]) is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_repo.py -v`
Expected: 新測試 FAIL（`AttributeError: 'Repo' object has no attribute 'create_snapshot'`）

- [ ] **Step 3: 實作（追加到 Repo class 尾端）**

```python
    # -- snapshots ----------------------------------------------------
    def create_snapshot(self, group_id: int, lines: list[SettlementLine],
                        created_by: int | None = None) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(rev), 0) AS r FROM entries WHERE group_id = ?",
            (group_id,)).fetchone()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO snapshots (group_id, through_rev, created_by) "
                "VALUES (?, ?, ?)",
                (group_id, row["r"], created_by))
            sid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO snapshot_lines "
                "(snapshot_id, from_member, to_member, amount) "
                "VALUES (?, ?, ?, ?)",
                [(sid, l.from_id, l.to_id, l.amount) for l in lines])
        return sid

    def latest_snapshot(self, group_id: int) -> Snapshot | None:
        row = self.conn.execute(
            "SELECT * FROM snapshots WHERE group_id = ? "
            "ORDER BY id DESC LIMIT 1", (group_id,)).fetchone()
        if row is None:
            return None
        lines = [SettlementLine(r["from_member"], r["to_member"], r["amount"])
                 for r in self.conn.execute(
                     "SELECT * FROM snapshot_lines WHERE snapshot_id = ?",
                     (row["id"],))]
        return Snapshot(id=row["id"], group_id=row["group_id"],
                        through_rev=row["through_rev"],
                        created_by=row["created_by"],
                        created_at=row["created_at"], lines=lines)

    def snapshot_is_stale(self, snapshot: Snapshot) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM entries WHERE group_id = ? AND rev > ? "
            "AND NOT (kind = 'transfer' AND transfer_kind = 'settlement') "
            "LIMIT 1",
            (snapshot.group_id, snapshot.through_rev)).fetchone()
        return row is not None

    def payments_for_snapshot(self, snapshot_id: int) -> list[Entry]:
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE snapshot_id = ? "
            "AND transfer_kind = 'settlement' AND deleted_at IS NULL "
            "ORDER BY id", (snapshot_id,)).fetchall()
        return self._rows_to_entries(rows)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_repo.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/storage/repo.py splitbook/tests/test_repo.py
git commit -m "feat(splitbook): add settlement snapshots with rev-based staleness"
```

---

### Task 6: 對帳模組 `domain/reconcile.py`

**Files:**
- Create: `splitbook/domain/reconcile.py`
- Test: `splitbook/tests/test_reconcile.py`

**Interfaces:**
- Consumes: `splitbook.domain.ledger.Entry, SettlementLine`
- Produces:
  - `@dataclass LineProgress`: `from_id: int, to_id: int, planned: int, paid: int`；property `remaining = max(0, planned - paid)`；property `status -> str`（`'unpaid' | 'partial' | 'paid' | 'overpaid'`）
  - `@dataclass CollectorProgress`: `to_id: int, expected: int, received: int, lines: list[LineProgress]`
  - `reconcile(lines: list[SettlementLine], payments: list[Entry]) -> tuple[list[LineProgress], list[Entry]]` — 付款以 `(payer_id, payee_id)` **累加**比對（支援部分付款與分次付款），對不到任何 line 的付款回傳在第二個 list（unplanned）
  - `by_collector(progress: list[LineProgress]) -> list[CollectorProgress]`（依 expected 降冪）

**這是全系統唯一一份對帳語意**（修正 tripsplit 缺陷 3：三套互相矛盾的比對邏輯）。

- [ ] **Step 1: 寫失敗測試**

```python
# splitbook/tests/test_reconcile.py
from splitbook.domain.ledger import Entry, SettlementLine
from splitbook.domain.reconcile import reconcile, by_collector


def pay(id, amount, from_id, to_id):
    return Entry(id=id, kind="transfer", name="結算轉帳", amount=amount,
                 payer_id=from_id, payee_id=to_id, transfer_kind="settlement")


def test_exact_payment_marks_paid():
    lines = [SettlementLine(2, 1, 500)]
    progress, unplanned = reconcile(lines, [pay(1, 500, 2, 1)])
    assert progress[0].status == "paid" and progress[0].remaining == 0
    assert unplanned == []


def test_partial_and_split_payments_accumulate():
    # 分兩筆付 300 + 100，計 400/500 → partial（tripsplit 的精確比對做不到）
    lines = [SettlementLine(2, 1, 500)]
    progress, _ = reconcile(lines, [pay(1, 300, 2, 1), pay(2, 100, 2, 1)])
    assert progress[0].paid == 400
    assert progress[0].status == "partial" and progress[0].remaining == 100


def test_overpayment_flagged():
    lines = [SettlementLine(2, 1, 500)]
    progress, _ = reconcile(lines, [pay(1, 600, 2, 1)])
    assert progress[0].status == "overpaid" and progress[0].remaining == 0


def test_unplanned_payment_reported():
    lines = [SettlementLine(2, 1, 500)]
    p = pay(1, 100, 3, 1)  # 方案中沒有 3→1 這條線
    progress, unplanned = reconcile(lines, [p])
    assert unplanned == [p]
    assert progress[0].status == "unpaid"


def test_by_collector_aggregates():
    lines = [SettlementLine(2, 1, 500), SettlementLine(3, 1, 300),
             SettlementLine(3, 4, 50)]
    progress, _ = reconcile(lines, [pay(1, 500, 2, 1)])
    collectors = by_collector(progress)
    assert collectors[0].to_id == 1
    assert collectors[0].expected == 800 and collectors[0].received == 500
    assert collectors[1].to_id == 4 and collectors[1].expected == 50
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_reconcile.py -v`
Expected: FAIL（module not found）

- [ ] **Step 3: 實作**

```python
# splitbook/domain/reconcile.py
"""對帳：快照方案 vs 實際結算轉帳。全系統唯一一份比對語意。"""
from dataclasses import dataclass, field

from splitbook.domain.ledger import Entry, SettlementLine


@dataclass
class LineProgress:
    from_id: int
    to_id: int
    planned: int
    paid: int

    @property
    def remaining(self) -> int:
        return max(0, self.planned - self.paid)

    @property
    def status(self) -> str:
        if self.paid == 0:
            return "unpaid"
        if self.paid < self.planned:
            return "partial"
        if self.paid == self.planned:
            return "paid"
        return "overpaid"


@dataclass
class CollectorProgress:
    to_id: int
    expected: int = 0
    received: int = 0
    lines: list[LineProgress] = field(default_factory=list)


def reconcile(lines: list[SettlementLine],
              payments: list[Entry]) -> tuple[list[LineProgress], list[Entry]]:
    paid_map: dict[tuple[int, int], int] = {}
    for p in payments:
        key = (p.payer_id, p.payee_id)
        paid_map[key] = paid_map.get(key, 0) + p.amount
    line_keys = {(l.from_id, l.to_id) for l in lines}
    progress = [
        LineProgress(l.from_id, l.to_id, l.amount,
                     paid_map.get((l.from_id, l.to_id), 0))
        for l in lines
    ]
    unplanned = [p for p in payments
                 if (p.payer_id, p.payee_id) not in line_keys]
    return progress, unplanned


def by_collector(progress: list[LineProgress]) -> list[CollectorProgress]:
    collectors: dict[int, CollectorProgress] = {}
    for lp in progress:
        c = collectors.setdefault(lp.to_id, CollectorProgress(to_id=lp.to_id))
        c.expected += lp.planned
        c.received += min(lp.paid, lp.planned)
        c.lines.append(lp)
    return sorted(collectors.values(), key=lambda c: -c.expected)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_reconcile.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/domain/reconcile.py splitbook/tests/test_reconcile.py
git commit -m "feat(splitbook): add single-semantics reconciliation with partial payments"
```

### Task 7: 身分驗證原語 `web/auth.py`

**Files:**
- Create: `splitbook/web/__init__.py`（空檔）
- Create: `splitbook/web/auth.py`
- Test: `splitbook/tests/test_auth.py`

**Interfaces:**
- Consumes: stdlib（`hashlib`, `hmac`, `os`, `time`）
- Produces:
  - `hash_pin(pin: str) -> str`（PBKDF2-SHA256，格式 `"{salt_hex}${dk_hex}"`）
  - `verify_pin(pin: str, stored: str) -> bool`
  - `make_token(group_id: int, member_id: int, secret: str, now: int | None = None, ttl: int = 2592000) -> str`（格式 `"gid.mid.exp.sig"`，HMAC-SHA256）
  - `parse_token(token: str, secret: str, now: int | None = None) -> tuple[int, int] | None`（簽章錯誤或過期回 `None`）

- [ ] **Step 1: 寫失敗測試**

```python
# splitbook/tests/test_auth.py
from splitbook.web.auth import hash_pin, verify_pin, make_token, parse_token


def test_pin_roundtrip():
    stored = hash_pin("1234")
    assert verify_pin("1234", stored) is True
    assert verify_pin("9999", stored) is False


def test_pin_hashes_are_salted():
    assert hash_pin("1234") != hash_pin("1234")


def test_verify_pin_bad_format_returns_false():
    assert verify_pin("1234", "garbage") is False


def test_token_roundtrip():
    t = make_token(3, 7, "secret", now=1000)
    assert parse_token(t, "secret", now=1000) == (3, 7)


def test_token_rejects_tamper_and_wrong_secret():
    t = make_token(3, 7, "secret", now=1000)
    assert parse_token(t + "x", "secret", now=1000) is None
    assert parse_token(t, "other", now=1000) is None
    assert parse_token("a.b.c", "secret") is None


def test_token_expires():
    t = make_token(3, 7, "secret", now=1000, ttl=60)
    assert parse_token(t, "secret", now=1061) is None
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_auth.py -v`
Expected: FAIL（module not found）

- [ ] **Step 3: 實作**

```python
# splitbook/web/auth.py
"""PIN 雜湊與 signed cookie token（stdlib only，5 人小工具等級）。"""
import hashlib
import hmac
import os
import time


def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return f"{salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 100_000)
    return hmac.compare_digest(dk.hex(), dk_hex)


def _sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(group_id: int, member_id: int, secret: str,
               now: int | None = None, ttl: int = 2592000) -> str:
    now = int(time.time()) if now is None else now
    payload = f"{group_id}.{member_id}.{now + ttl}"
    return f"{payload}.{_sign(payload, secret)}"


def parse_token(token: str, secret: str,
                now: int | None = None) -> tuple[int, int] | None:
    now = int(time.time()) if now is None else now
    parts = token.split(".")
    if len(parts) != 4:
        return None
    payload = ".".join(parts[:3])
    if not hmac.compare_digest(_sign(payload, secret), parts[3]):
        return None
    try:
        gid, mid, exp = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if exp < now:
        return None
    return gid, mid
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_auth.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/web/ splitbook/tests/test_auth.py
git commit -m "feat(splitbook): add PIN hashing and signed session tokens"
```

---

### Task 8: App 工廠、初始設定與登入流程

**Files:**
- Create: `splitbook/requirements.txt`
- Create: `splitbook/web/app.py`
- Create: `splitbook/web/routes.py`
- Create: `splitbook/web/templates/base.html`
- Create: `splitbook/web/templates/setup.html`
- Create: `splitbook/web/templates/login.html`
- Create: `splitbook/web/templates/home.html`
- Create: `splitbook/web/static/style.css`（先放空檔，Task 12 補樣式）
- Create: `splitbook/main.py`
- Test: `splitbook/tests/test_web.py`

**Interfaces:**
- Consumes: Task 4/5 `Repo`、Task 2 `compute_balances`、Task 7 auth 全部函數
- Produces:
  - `splitbook.web.app.create_app(db_path: str | None = None, secret: str | None = None) -> FastAPI`（測試傳 `":memory:"`；`app.state.repo`、`app.state.secret`）
  - `splitbook.web.routes.router`（APIRouter，含 `/setup`, `/login`, `/logout`, `/`）
  - `splitbook.web.routes.current(request) -> tuple[Repo, int, sqlite3.Row] | None` — 後續 task 的所有路由用它取（repo, group_id, member）；回 `None` 表示未登入
  - session cookie 名稱：`"session"`，httponly

**登入規則：** 成員第一次登入時 `pin_hash` 為 NULL → 本次輸入的 PIN（≥4 碼）直接設為他的 PIN；之後登入需驗證。錯誤顯示在 login 頁 `error` 變數。

- [ ] **Step 1: 寫失敗測試**

```python
# splitbook/tests/test_web.py
import pytest
from fastapi.testclient import TestClient
from splitbook.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=":memory:", secret="test-secret")
    return TestClient(app)


def _setup_group(client, members=("小明", "小華", "小美")):
    data = {"group_name": "沖繩行"}
    for i, name in enumerate(members, 1):
        data[f"member{i}"] = name
    return client.post("/setup", data=data, follow_redirects=False)


def _login(client, member_id=1, pin="1234"):
    return client.post("/login", data={"member_id": member_id, "pin": pin},
                       follow_redirects=False)


def test_root_redirects_to_setup_when_no_groups(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"


def test_setup_creates_group_and_members(client):
    r = _setup_group(client)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    page = client.get("/login")
    assert "沖繩行" in page.text and "小明" in page.text


def test_first_login_sets_pin_then_requires_it(client):
    _setup_group(client)
    r = _login(client, member_id=1, pin="1234")
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert "session" in r.cookies
    # 登出後用錯 PIN 再登入 → 失敗留在 login 頁
    client.post("/logout")
    r2 = client.post("/login", data={"member_id": 1, "pin": "9999"})
    assert "PIN 錯誤" in r2.text


def test_short_pin_rejected_on_first_login(client):
    _setup_group(client)
    r = client.post("/login", data={"member_id": 1, "pin": "12"})
    assert "至少 4 碼" in r.text


def test_home_requires_login(client):
    _setup_group(client)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_home_shows_members_and_balances(client):
    _setup_group(client)
    _login(client)
    r = client.get("/")
    assert r.status_code == 200
    for name in ("小明", "小華", "小美"):
        assert name in r.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: FAIL（module not found）

- [ ] **Step 3: 實作**

```
# splitbook/requirements.txt
fastapi
uvicorn[standard]
jinja2
python-multipart
pytest
httpx
```

```python
# splitbook/web/app.py
"""App 工廠。"""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from splitbook.storage.db import connect, init_db
from splitbook.storage.repo import Repo

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))


def create_app(db_path: str | None = None, secret: str | None = None) -> FastAPI:
    from splitbook.web.routes import router

    db_path = db_path or os.environ.get("SPLITBOOK_DB", "splitbook.db")
    secret = secret or os.environ.get("SPLITBOOK_SECRET", "dev-secret-change-me")

    conn = connect(db_path)
    init_db(conn)

    app = FastAPI(title="SplitBook")
    app.state.repo = Repo(conn)
    app.state.secret = secret
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")),
              name="static")
    app.include_router(router)
    return app
```

```python
# splitbook/main.py
"""uvicorn 入口：uvicorn splitbook.main:app（從 repo root 執行）"""
from splitbook.web.app import create_app

app = create_app()
```

```python
# splitbook/web/routes.py
"""全部路由。薄層：解析表單 → repo/domain → 模板。"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from splitbook.domain.ledger import compute_balances
from splitbook.web.app import templates
from splitbook.web.auth import hash_pin, make_token, parse_token, verify_pin

router = APIRouter()


def current(request: Request):
    """回傳 (repo, group_id, member_row)；未登入回 None。"""
    repo = request.app.state.repo
    token = request.cookies.get("session", "")
    parsed = parse_token(token, request.app.state.secret)
    if parsed is None:
        return None
    gid, mid = parsed
    member = repo.get_member(mid)
    if member is None or member["group_id"] != gid or not member["active"]:
        return None
    return repo, gid, member


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


# -- setup ------------------------------------------------------------
@router.get("/setup")
def setup_page(request: Request):
    return templates.TemplateResponse(
        "setup.html", {"request": request})


@router.post("/setup")
def setup_submit(request: Request, group_name: str = Form(...),
                 member1: str = Form(""), member2: str = Form(""),
                 member3: str = Form(""), member4: str = Form(""),
                 member5: str = Form("")):
    repo = request.app.state.repo
    names = [n.strip() for n in
             (member1, member2, member3, member4, member5) if n.strip()]
    if not group_name.strip() or not names:
        return templates.TemplateResponse("setup.html", {
            "request": request, "error": "請填寫帳本名稱與至少一位成員"})
    gid = repo.create_group(group_name.strip())
    for n in names:
        repo.add_member(gid, n)
    return _redirect("/login")


# -- login ------------------------------------------------------------
def _login_context(request, repo, error=""):
    groups = []
    for g in repo.list_groups():
        groups.append({"group": g, "members": repo.list_members(g["id"])})
    return {"request": request, "groups": groups, "error": error}


@router.get("/login")
def login_page(request: Request):
    repo = request.app.state.repo
    return templates.TemplateResponse(
        "login.html", _login_context(request, repo))


@router.post("/login")
def login_submit(request: Request, member_id: int = Form(...),
                 pin: str = Form("")):
    repo = request.app.state.repo
    member = repo.get_member(member_id)
    if member is None or not member["active"]:
        return templates.TemplateResponse(
            "login.html", _login_context(request, repo, "找不到成員"))
    if member["pin_hash"] is None:
        if len(pin) < 4:
            return templates.TemplateResponse(
                "login.html",
                _login_context(request, repo, "第一次登入請設定 PIN（至少 4 碼）"))
        repo.set_pin_hash(member_id, hash_pin(pin))
    elif not verify_pin(pin, member["pin_hash"]):
        return templates.TemplateResponse(
            "login.html", _login_context(request, repo, "PIN 錯誤"))
    token = make_token(member["group_id"], member_id,
                       request.app.state.secret)
    resp = _redirect("/")
    resp.set_cookie("session", token, httponly=True, max_age=2592000)
    return resp


@router.post("/logout")
def logout():
    resp = _redirect("/login")
    resp.delete_cookie("session")
    return resp


# -- home（成員與餘額）--------------------------------------------------
@router.get("/")
def home(request: Request):
    repo = request.app.state.repo
    if not repo.list_groups():
        return _redirect("/setup")
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    members = repo.list_members(gid)
    entries = repo.list_entries(gid)
    error = ""
    balances = {}
    try:
        balances = compute_balances({m["id"] for m in members}, entries)
    except Exception as e:
        error = str(e)
    total_expense = sum(e.amount for e in entries if e.kind == "expense")
    return templates.TemplateResponse("home.html", {
        "request": request, "me": me, "members": members,
        "balances": balances, "error": error,
        "group": repo.get_group(gid), "total_expense": total_expense,
        "active_tab": "home",
    })
```

```html
<!-- splitbook/web/templates/base.html -->
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}SplitBook{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header class="topbar">
    <span class="brand">SplitBook</span>
    {% if me is defined and me %}
      <nav>
        <a href="/" class="{{ 'on' if active_tab == 'home' }}">成員</a>
        <a href="/expenses" class="{{ 'on' if active_tab == 'expenses' }}">帳目</a>
        <a href="/transfers" class="{{ 'on' if active_tab == 'transfers' }}">轉帳</a>
        <a href="/settlement" class="{{ 'on' if active_tab == 'settlement' }}">結算</a>
      </nav>
      <form method="post" action="/logout" class="inline">
        <button class="ghost">{{ me['name'] }}・登出</button>
      </form>
    {% endif %}
  </header>
  <main>
    {% if error is defined and error %}<div class="alert">{{ error }}</div>{% endif %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

```html
<!-- splitbook/web/templates/setup.html -->
{% extends "base.html" %}
{% block title %}建立帳本 — SplitBook{% endblock %}
{% block content %}
<h1>建立新帳本</h1>
<form method="post" action="/setup" class="card">
  <label>帳本名稱 <input name="group_name" required></label>
  <p>成員（最多 5 位）</p>
  {% for i in range(1, 6) %}
    <input name="member{{ i }}" placeholder="成員 {{ i }}">
  {% endfor %}
  <button type="submit">建立</button>
</form>
{% endblock %}
```

```html
<!-- splitbook/web/templates/login.html -->
{% extends "base.html" %}
{% block title %}登入 — SplitBook{% endblock %}
{% block content %}
<h1>選擇你的身分</h1>
<form method="post" action="/login" class="card">
  {% for g in groups %}
    <fieldset>
      <legend>{{ g.group['name'] }}</legend>
      {% for m in g.members %}
        <label class="radio">
          <input type="radio" name="member_id" value="{{ m['id'] }}" required>
          {{ m['name'] }}{% if m['pin_hash'] is none %}（尚未設定 PIN）{% endif %}
        </label>
      {% endfor %}
    </fieldset>
  {% endfor %}
  <label>PIN <input name="pin" type="password" inputmode="numeric"
         placeholder="第一次登入即設定 PIN"></label>
  <button type="submit">登入</button>
</form>
<p><a href="/setup">＋ 建立新帳本</a></p>
{% endblock %}
```

```html
<!-- splitbook/web/templates/home.html -->
{% extends "base.html" %}
{% block title %}{{ group['name'] }} — SplitBook{% endblock %}
{% block content %}
<h1>{{ group['name'] }}</h1>
<p class="muted">總支出 ${{ "{:,}".format(total_expense) }}</p>
<div class="cards">
  {% for m in members %}
    {% set b = balances.get(m['id']) %}
    <div class="card">
      <h2>{{ m['name'] }}{% if m['id'] == me['id'] %}（我）{% endif %}</h2>
      {% if b %}
        <p>代墊 ${{ "{:,}".format(b.advanced) }}／應分攤 ${{ "{:,}".format(b.share) }}</p>
        <p>已轉出 ${{ "{:,}".format(b.sent) }}／已收到 ${{ "{:,}".format(b.received) }}</p>
        <p class="net {{ 'pos' if b.net > 0 else 'neg' if b.net < 0 else '' }}">
          淨額 ${{ "{:,}".format(b.net) }}
          {% if b.net > 0 %}（應收回）{% elif b.net < 0 %}（應付）{% else %}（已結清）{% endif %}
        </p>
      {% endif %}
    </div>
  {% endfor %}
</div>
{% endblock %}
```

（`splitbook/web/static/style.css` 本 task 先建立空檔，樣式在 Task 12 補。）

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/
git commit -m "feat(splitbook): add app factory, setup and PIN login flow"
```

### Task 9: 帳目頁（支出 CRUD 與分攤表單）

**Files:**
- Modify: `splitbook/web/routes.py`（追加）
- Create: `splitbook/web/templates/expenses.html`
- Test: `splitbook/tests/test_web.py`（追加）

**Interfaces:**
- Consumes: Task 8 `current()`、Task 1 split 函數、Task 4 repo 方法
- Produces:
  - `GET /expenses`（`?edit={id}` 預填編輯表單）、`POST /expenses`、`POST /expenses/{eid}/update`、`POST /expenses/{eid}/delete`
  - `parse_split(form, member_ids: list[int], amount: int, payer_id: int) -> dict[int, int]`（routes.py 內的表單轉接器）
- 表單欄位協定：`split_kind` = `equal|weights|exact`；每位成員對應 `p_{mid}`（均分參與勾選，全不勾 = 全員）、`w_{mid}`（權重）、`x_{mid}`（指定金額）

- [ ] **Step 1: 寫失敗測試（追加到 test_web.py）**

```python
def _logged_in_client():
    app = create_app(db_path=":memory:", secret="test-secret")
    c = TestClient(app)
    _setup_group(c)
    _login(c, member_id=1, pin="1234")
    return c


def test_create_equal_expense_defaults_to_all(client=None):
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 300, "payer_id": 1,
        "split_kind": "equal"}, follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/expenses")
    assert "民宿" in page.text
    home = c.get("/")
    assert "$200" in home.text  # 小明 net = 300 - 100


def test_create_weighted_expense():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "包車", "category": "交通", "amount": 100, "payer_id": 1,
        "split_kind": "weights", "w_1": 2, "w_2": 1, "w_3": 1})
    page = c.get("/expenses")
    assert "包車" in page.text


def test_exact_split_mismatch_shows_error():
    c = _logged_in_client()
    r = c.post("/expenses", data={
        "name": "門票", "category": "票券", "amount": 100, "payer_id": 1,
        "split_kind": "exact", "x_1": 60, "x_2": 50})
    assert "不等於總金額" in r.text


def test_update_and_delete_expense():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "餐費", "category": "餐費", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    c.post("/expenses/1/update", data={
        "name": "晚餐", "category": "餐費", "amount": 600, "payer_id": 2,
        "split_kind": "equal"})
    page = c.get("/expenses")
    assert "晚餐" in page.text and "餐費(舊)" not in page.text
    c.post("/expenses/1/delete")
    page = c.get("/expenses")
    assert "晚餐" not in page.text


def test_expense_requires_login():
    app = create_app(db_path=":memory:", secret="test-secret")
    c = TestClient(app)
    _setup_group(c)
    r = c.get("/expenses", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: 新測試 FAIL（404）

- [ ] **Step 3: 實作（追加到 routes.py）**

```python
# 追加 import
from splitbook.domain.split import (
    SplitError, split_equal, split_exact, split_weights)

CATEGORIES = ["住宿", "餐費", "交通", "票券", "雜支"]


def parse_split(form, member_ids: list[int], amount: int,
                payer_id: int) -> dict[int, int]:
    kind = form.get("split_kind", "equal")
    if kind == "equal":
        participants = [mid for mid in member_ids if form.get(f"p_{mid}")]
        if not participants:
            participants = list(member_ids)
        return split_equal(amount, participants, payer_id=payer_id)
    if kind == "weights":
        weights = {mid: int(form.get(f"w_{mid}") or 0) for mid in member_ids}
        return split_weights(amount, {k: v for k, v in weights.items() if v > 0})
    if kind == "exact":
        amounts = {mid: int(form.get(f"x_{mid}") or 0) for mid in member_ids}
        return split_exact(amount, {k: v for k, v in amounts.items() if v != 0})
    raise SplitError(f"未知的分攤規則 {kind!r}")


def _expenses_context(request, repo, gid, me, error=""):
    members = repo.list_members(gid)
    names = {m["id"]: m["name"] for m in members}
    expenses = [e for e in repo.list_entries(gid) if e.kind == "expense"]
    expenses.sort(key=lambda e: (e.date, e.id), reverse=True)
    edit_id = request.query_params.get("edit")
    editing = repo.get_entry(int(edit_id)) if edit_id else None
    return {"request": request, "me": me, "members": members, "names": names,
            "expenses": expenses, "editing": editing, "error": error,
            "categories": CATEGORIES, "active_tab": "expenses"}


@router.get("/expenses")
def expenses_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    return templates.TemplateResponse(
        "expenses.html", _expenses_context(request, repo, gid, me))


async def _handle_expense_form(request, entry_id: int | None):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    form = await request.form()
    try:
        amount = int(form["amount"])
        payer_id = int(form["payer_id"])
        member_ids = [m["id"] for m in repo.list_members(gid)]
        alloc = parse_split(form, member_ids, amount, payer_id)
        kwargs = dict(
            name=form["name"], amount=amount, payer_id=payer_id,
            allocations=alloc, category=form.get("category", ""),
            date=form.get("date", ""), note=form.get("note", ""))
        if entry_id is None:
            repo.record_expense(gid, created_by=me["id"], **kwargs)
        else:
            repo.update_expense(entry_id, **kwargs)
    except (SplitError, ValueError, KeyError) as e:
        return templates.TemplateResponse(
            "expenses.html",
            _expenses_context(request, repo, gid, me, error=str(e)))
    return _redirect("/expenses")


@router.post("/expenses")
async def create_expense_route(request: Request):
    return await _handle_expense_form(request, None)


@router.post("/expenses/{eid}/update")
async def update_expense_route(request: Request, eid: int):
    return await _handle_expense_form(request, eid)


@router.post("/expenses/{eid}/delete")
def delete_expense_route(request: Request, eid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    repo.soft_delete_entry(eid)
    return _redirect("/expenses")
```

```html
<!-- splitbook/web/templates/expenses.html -->
{% extends "base.html" %}
{% block title %}帳目 — SplitBook{% endblock %}
{% block content %}
<h1>帳目</h1>

<form method="post"
      action="{{ '/expenses/' ~ editing.id ~ '/update' if editing else '/expenses' }}"
      class="card">
  <h2>{{ "編輯支出" if editing else "新增支出" }}</h2>
  <label>項目 <input name="name" required
         value="{{ editing.name if editing }}"></label>
  <label>類別
    <input name="category" list="cats"
           value="{{ editing.category if editing }}">
    <datalist id="cats">
      {% for c in categories %}<option value="{{ c }}">{% endfor %}
    </datalist>
  </label>
  <label>總金額 <input name="amount" type="number" required
         value="{{ editing.amount if editing }}"></label>
  <label>付款人
    <select name="payer_id">
      {% for m in members %}
        <option value="{{ m['id'] }}"
          {{ 'selected' if editing and editing.payer_id == m['id'] }}>
          {{ m['name'] }}</option>
      {% endfor %}
    </select>
  </label>
  <label>日期 <input name="date" type="date"
         value="{{ editing.date if editing }}"></label>
  <label>備註 <input name="note" value="{{ editing.note if editing }}"></label>

  <fieldset>
    <legend>分攤方式</legend>
    <label class="radio"><input type="radio" name="split_kind" value="equal" checked> 均分</label>
    <label class="radio"><input type="radio" name="split_kind" value="weights"> 依權重</label>
    <label class="radio"><input type="radio" name="split_kind" value="exact"> 指定金額</label>
    <table class="split-table">
      <tr><th>成員</th><th>參與(均分)</th><th>權重</th><th>金額(指定)</th></tr>
      {% for m in members %}
      <tr>
        <td>{{ m['name'] }}</td>
        <td><input type="checkbox" name="p_{{ m['id'] }}"></td>
        <td><input type="number" name="w_{{ m['id'] }}" min="0" class="short"></td>
        <td><input type="number" name="x_{{ m['id'] }}" class="short"></td>
      </tr>
      {% endfor %}
    </table>
    <p class="muted">均分不勾選任何人 = 全員參與。餘數從付款人的下一位開始每人 +1。</p>
  </fieldset>
  <button type="submit">{{ "更新" if editing else "新增" }}</button>
  {% if editing %}<a href="/expenses">取消編輯</a>{% endif %}
</form>

<table class="list">
  <tr><th>日期</th><th>項目</th><th>類別</th><th>金額</th><th>付款人</th><th>分攤</th><th></th></tr>
  {% for e in expenses %}
  <tr>
    <td>{{ e.date }}</td>
    <td>{{ e.name }}</td>
    <td>{{ e.category }}</td>
    <td>${{ "{:,}".format(e.amount) }}</td>
    <td>{{ names.get(e.payer_id, "?") }}</td>
    <td class="muted">
      {% for mid, a in e.allocations.items() %}
        {{ names.get(mid, "?") }} ${{ "{:,}".format(a) }}{{ "、" if not loop.last }}
      {% endfor %}
    </td>
    <td>
      <a href="/expenses?edit={{ e.id }}">編輯</a>
      <form method="post" action="/expenses/{{ e.id }}/delete" class="inline"
            onsubmit="return confirm('確定刪除？')">
        <button class="ghost">刪除</button>
      </form>
    </td>
  </tr>
  {% else %}
  <tr><td colspan="7" class="muted">尚未有帳目</td></tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/web/ splitbook/tests/test_web.py
git commit -m "feat(splitbook): add expense CRUD with pluggable split policies"
```

---

### Task 10: 轉帳頁（預付/代墊還款）

**Files:**
- Modify: `splitbook/web/routes.py`（追加）
- Create: `splitbook/web/templates/transfers.html`
- Test: `splitbook/tests/test_web.py`（追加）

**Interfaces:**
- Consumes: Task 8 `current()`、Task 4 `record_transfer`/`soft_delete_entry`
- Produces: `GET /transfers`、`POST /transfers`（建立 `prepay` 轉帳）、`POST /transfers/{eid}/delete`

- [ ] **Step 1: 寫失敗測試（追加到 test_web.py）**

```python
def test_record_prepay_transfer_affects_balances():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 3000, "payer_id": 1,
        "split_kind": "equal"})
    r = c.post("/transfers", data={
        "from_id": 2, "to_id": 1, "amount": 500, "note": "先繳"},
        follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/transfers")
    assert "先繳" in page.text
    # 小華 net：-1000 + 500 = -500
    home = c.get("/")
    assert "$-500" in home.text or "-500" in home.text


def test_self_transfer_rejected():
    c = _logged_in_client()
    r = c.post("/transfers", data={"from_id": 1, "to_id": 1, "amount": 100})
    assert "不可相同" in r.text


def test_delete_transfer():
    c = _logged_in_client()
    c.post("/transfers", data={"from_id": 2, "to_id": 1, "amount": 500})
    c.post("/transfers/1/delete")
    page = c.get("/transfers")
    assert "尚未有轉帳" in page.text
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: 新測試 FAIL（404）

- [ ] **Step 3: 實作（追加到 routes.py）**

```python
def _transfers_context(request, repo, gid, me, error=""):
    members = repo.list_members(gid)
    names = {m["id"]: m["name"] for m in members}
    transfers = [e for e in repo.list_entries(gid) if e.kind == "transfer"]
    transfers.sort(key=lambda e: e.id, reverse=True)
    return {"request": request, "me": me, "members": members, "names": names,
            "transfers": transfers, "error": error, "active_tab": "transfers"}


@router.get("/transfers")
def transfers_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    return templates.TemplateResponse(
        "transfers.html", _transfers_context(request, repo, gid, me))


@router.post("/transfers")
def create_transfer_route(request: Request, from_id: int = Form(...),
                          to_id: int = Form(...), amount: int = Form(...),
                          note: str = Form("")):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    try:
        repo.record_transfer(gid, amount, from_id, to_id, "prepay",
                             name="預付款", note=note, created_by=me["id"])
    except ValueError as e:
        return templates.TemplateResponse(
            "transfers.html",
            _transfers_context(request, repo, gid, me, error=str(e)))
    return _redirect("/transfers")


@router.post("/transfers/{eid}/delete")
def delete_transfer_route(request: Request, eid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    repo.soft_delete_entry(eid)
    return _redirect("/transfers")
```

```html
<!-- splitbook/web/templates/transfers.html -->
{% extends "base.html" %}
{% block title %}轉帳 — SplitBook{% endblock %}
{% block content %}
<h1>成員間轉帳</h1>
<form method="post" action="/transfers" class="card">
  <h2>記一筆轉帳（預付款/還款）</h2>
  <label>轉出
    <select name="from_id">
      {% for m in members %}<option value="{{ m['id'] }}">{{ m['name'] }}</option>{% endfor %}
    </select>
  </label>
  <label>轉入
    <select name="to_id">
      {% for m in members %}<option value="{{ m['id'] }}">{{ m['name'] }}</option>{% endfor %}
    </select>
  </label>
  <label>金額 <input name="amount" type="number" min="1" required></label>
  <label>備註 <input name="note"></label>
  <button type="submit">記錄</button>
</form>

<table class="list">
  <tr><th>日期</th><th>轉出</th><th>轉入</th><th>金額</th><th>類型</th><th>備註</th><th></th></tr>
  {% for t in transfers %}
  <tr>
    <td>{{ t.date }}</td>
    <td>{{ names.get(t.payer_id, "?") }}</td>
    <td>{{ names.get(t.payee_id, "?") }}</td>
    <td>${{ "{:,}".format(t.amount) }}</td>
    <td>{{ "結算轉帳" if t.transfer_kind == "settlement" else "預付款" }}</td>
    <td class="muted">{{ t.note }}</td>
    <td>
      <form method="post" action="/transfers/{{ t.id }}/delete" class="inline"
            onsubmit="return confirm('確定刪除？')">
        <button class="ghost">刪除</button>
      </form>
    </td>
  </tr>
  {% else %}
  <tr><td colspan="7" class="muted">尚未有轉帳</td></tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/web/ splitbook/tests/test_web.py
git commit -m "feat(splitbook): add member transfers page"
```

### Task 11: 結算頁（方案、快照、付款追蹤、過期警告）

**Files:**
- Modify: `splitbook/web/routes.py`（追加）
- Create: `splitbook/web/templates/settlement.html`
- Test: `splitbook/tests/test_web.py`（追加）

**Interfaces:**
- Consumes: Task 2 `compute_balances`/`simplify_debts`、Task 5 快照方法、Task 6 `reconcile`/`by_collector`
- Produces:
  - `GET /settlement` — 上半：目前餘額算出的即時方案；下半：最新快照的付款進度（若有），快照過期時顯示警告
  - `POST /settlement/snapshot` — 以目前方案建立快照
  - `POST /settlement/pay`（Form: `from_id`, `to_id`, `amount`, `snapshot_id`）— 記錄結算轉帳
  - `POST /payments/{eid}/undo` — 軟刪除付款

- [ ] **Step 1: 寫失敗測試（追加到 test_web.py）**

```python
def test_settlement_flow_with_partial_payment_and_stale():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "民宿", "category": "住宿", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    # 即時方案：小華→小明 $100、小美→小明 $100
    page = c.get("/settlement")
    assert "小華" in page.text and "$100" in page.text

    # 建立快照
    r = c.post("/settlement/snapshot", follow_redirects=False)
    assert r.status_code == 303
    page = c.get("/settlement")
    assert "付款進度" in page.text

    # 部分付款 60/100 → partial
    c.post("/settlement/pay", data={
        "from_id": 2, "to_id": 1, "amount": 60, "snapshot_id": 1})
    page = c.get("/settlement")
    assert "已付 $60" in page.text

    # 快照後修改帳目 → 過期警告
    c.post("/expenses", data={
        "name": "追加", "category": "雜支", "amount": 90, "payer_id": 2,
        "split_kind": "equal"})
    page = c.get("/settlement")
    assert "已過期" in page.text


def test_undo_payment():
    c = _logged_in_client()
    c.post("/expenses", data={
        "name": "餐", "category": "餐費", "amount": 300, "payer_id": 1,
        "split_kind": "equal"})
    c.post("/settlement/snapshot")
    c.post("/settlement/pay", data={
        "from_id": 2, "to_id": 1, "amount": 100, "snapshot_id": 1})
    # 找出付款分錄 id（expense=1 之後的下一筆 transfer）
    page = c.get("/settlement")
    assert "已付 $100" in page.text
    c.post("/payments/2/undo")
    page = c.get("/settlement")
    assert "已付 $100" not in page.text


def test_snapshot_requires_login():
    app = create_app(db_path=":memory:", secret="test-secret")
    c = TestClient(app)
    _setup_group(c)
    r = c.post("/settlement/snapshot", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: 新測試 FAIL（404）

- [ ] **Step 3: 實作（追加到 routes.py）**

```python
# 追加 import
from splitbook.domain.ledger import simplify_debts
from splitbook.domain.reconcile import by_collector, reconcile


def _live_plan(repo, gid):
    members = repo.list_members(gid)
    entries = repo.list_entries(gid)
    balances = compute_balances({m["id"] for m in members}, entries)
    return simplify_debts({mid: b.net for mid, b in balances.items()})


@router.get("/settlement")
def settlement_page(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    members = repo.list_members(gid, include_inactive=True)
    names = {m["id"]: m["name"] for m in members}
    error = ""
    plan = []
    try:
        plan = _live_plan(repo, gid)
    except Exception as e:
        error = str(e)
    snap = repo.latest_snapshot(gid)
    snapshot_view = None
    if snap is not None:
        payments = repo.payments_for_snapshot(snap.id)
        progress, unplanned = reconcile(snap.lines, payments)
        snapshot_view = {
            "snap": snap,
            "stale": repo.snapshot_is_stale(snap),
            "collectors": by_collector(progress),
            "unplanned": unplanned,
            "payments": payments,
        }
    return templates.TemplateResponse("settlement.html", {
        "request": request, "me": me, "names": names, "plan": plan,
        "snapshot": snapshot_view, "error": error,
        "active_tab": "settlement",
    })


@router.post("/settlement/snapshot")
def create_snapshot_route(request: Request):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    repo.create_snapshot(gid, _live_plan(repo, gid), created_by=me["id"])
    return _redirect("/settlement")


@router.post("/settlement/pay")
def record_payment_route(request: Request, from_id: int = Form(...),
                         to_id: int = Form(...), amount: int = Form(...),
                         snapshot_id: int = Form(...)):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    repo.record_transfer(gid, amount, from_id, to_id, "settlement",
                         name="結算轉帳", created_by=me["id"],
                         snapshot_id=snapshot_id)
    return _redirect("/settlement")


@router.post("/payments/{eid}/undo")
def undo_payment_route(request: Request, eid: int):
    session = current(request)
    if session is None:
        return _redirect("/login")
    repo, gid, me = session
    repo.soft_delete_entry(eid)
    return _redirect("/settlement")
```

```html
<!-- splitbook/web/templates/settlement.html -->
{% extends "base.html" %}
{% block title %}結算 — SplitBook{% endblock %}
{% block content %}
<h1>結算</h1>

<section class="card">
  <h2>目前方案（即時計算）</h2>
  {% if plan %}
    <ul>
      {% for line in plan %}
        <li>{{ names.get(line.from_id, "?") }} → {{ names.get(line.to_id, "?") }}
            <strong>${{ "{:,}".format(line.amount) }}</strong></li>
      {% endfor %}
    </ul>
    <form method="post" action="/settlement/snapshot">
      <button type="submit">凍結此方案（建立快照）</button>
    </form>
  {% else %}
    <p class="muted">目前已結清，沒有需要的轉帳。</p>
  {% endif %}
</section>

{% if snapshot %}
<section class="card">
  <h2>付款進度（快照 #{{ snapshot.snap.id }}・{{ snapshot.snap.created_at }}）</h2>
  {% if snapshot.stale %}
    <div class="alert">此快照已過期：快照後帳目有異動。請確認後重新凍結方案。</div>
  {% endif %}
  {% for col in snapshot.collectors %}
    <h3>{{ names.get(col.to_id, "?") }} 應收 ${{ "{:,}".format(col.expected) }}
        ／已收 ${{ "{:,}".format(col.received) }}</h3>
    <ul>
      {% for lp in col.lines %}
      <li>
        {{ names.get(lp.from_id, "?") }} → {{ names.get(lp.to_id, "?") }}
        ${{ "{:,}".format(lp.planned) }}
        {% if lp.status == "paid" %}✅ 已付清
        {% elif lp.status == "overpaid" %}⚠️ 已付 ${{ "{:,}".format(lp.paid) }}（超額）
        {% elif lp.status == "partial" %}⏳ 已付 ${{ "{:,}".format(lp.paid) }}，
            差 ${{ "{:,}".format(lp.remaining) }}
        {% else %}未付
        {% endif %}
        {% if lp.remaining > 0 %}
        <form method="post" action="/settlement/pay" class="inline">
          <input type="hidden" name="from_id" value="{{ lp.from_id }}">
          <input type="hidden" name="to_id" value="{{ lp.to_id }}">
          <input type="hidden" name="snapshot_id" value="{{ snapshot.snap.id }}">
          <input type="number" name="amount" value="{{ lp.remaining }}"
                 min="1" class="short">
          <button type="submit">記錄付款</button>
        </form>
        {% endif %}
      </li>
      {% endfor %}
    </ul>
  {% endfor %}
  {% if snapshot.payments %}
    <h3>已記錄的付款</h3>
    <ul>
      {% for p in snapshot.payments %}
      <li>{{ p.date }} {{ names.get(p.payer_id, "?") }} →
          {{ names.get(p.payee_id, "?") }} ${{ "{:,}".format(p.amount) }}
        <form method="post" action="/payments/{{ p.id }}/undo" class="inline">
          <button class="ghost">撤銷</button>
        </form>
      </li>
      {% endfor %}
    </ul>
  {% endif %}
  {% if snapshot.unplanned %}
    <div class="alert">有 {{ snapshot.unplanned | length }} 筆付款不在方案內，請檢查。</div>
  {% endif %}
</section>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: 執行測試確認通過**

Run: `python -m pytest splitbook/tests/test_web.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add splitbook/web/ splitbook/tests/test_web.py
git commit -m "feat(splitbook): add settlement page with snapshots and payment tracking"
```

---

### Task 12: 樣式、文件與收尾

**Files:**
- Modify: `splitbook/web/static/style.css`（補完整樣式）
- Create: `splitbook/README.md`
- Create: `CONTEXT.md`（repo root，領域詞彙表）
- Modify: `.gitignore`（追加 `splitbook.db`、`*.db`）

**Interfaces:**
- Consumes: 全部前置 task
- Produces: 可執行的完整應用 + 文件

- [ ] **Step 1: 補樣式**

```css
/* splitbook/web/static/style.css */
:root {
  --bg: #0f172a; --panel: #1e293b; --line: #334155;
  --text: #e2e8f0; --muted: #94a3b8;
  --pos: #4ade80; --neg: #f87171; --accent: #38bdf8;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "Fira Sans", "Noto Sans TC", system-ui, sans-serif;
}
.topbar {
  display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
  padding: .75rem 1rem; background: var(--panel);
  border-bottom: 1px solid var(--line);
}
.brand { font-weight: 700; color: var(--accent); }
.topbar nav { display: flex; gap: .75rem; flex: 1; }
.topbar a { color: var(--muted); text-decoration: none; padding: .25rem .5rem; }
.topbar a.on { color: var(--text); border-bottom: 2px solid var(--accent); }
main { max-width: 56rem; margin: 0 auto; padding: 1rem; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; } h3 { font-size: 1rem; }
.card {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: .5rem; padding: 1rem; margin-bottom: 1rem;
}
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: .75rem; }
label { display: block; margin: .5rem 0; }
input, select {
  background: var(--bg); color: var(--text); border: 1px solid var(--line);
  border-radius: .25rem; padding: .4rem; width: 100%; max-width: 20rem;
}
input.short { width: 6rem; }
.radio { display: inline-flex; align-items: center; gap: .3rem; margin-right: 1rem; }
.radio input { width: auto; }
button {
  background: var(--accent); color: #082f49; border: 0; border-radius: .25rem;
  padding: .5rem 1rem; font-weight: 600; cursor: pointer; margin-top: .5rem;
}
button.ghost { background: transparent; color: var(--muted); border: 1px solid var(--line); }
.inline { display: inline; }
.alert {
  background: #7f1d1d; border: 1px solid #b91c1c; color: #fecaca;
  padding: .5rem .75rem; border-radius: .25rem; margin-bottom: 1rem;
}
.muted { color: var(--muted); }
.net.pos { color: var(--pos); } .net.neg { color: var(--neg); }
table.list, table.split-table { width: 100%; border-collapse: collapse; }
table.list th, table.list td, table.split-table th, table.split-table td {
  text-align: left; padding: .4rem .5rem; border-bottom: 1px solid var(--line);
}
fieldset { border: 1px solid var(--line); border-radius: .25rem; margin: .5rem 0; }
ul { padding-left: 1.2rem; } li { margin: .3rem 0; }
```

- [ ] **Step 2: 寫 README 與 CONTEXT.md**

```markdown
<!-- splitbook/README.md -->
# SplitBook — 小團體拆帳

5 人以內互記帳務的拆帳工具。分錄式帳本（Σnet 恆為 0）、
分攤在寫入時固化、結算快照 + 部分付款對帳。

## 啟動

```bash
pip install -r splitbook/requirements.txt
# repo root:
uvicorn splitbook.main:app --reload
```

環境變數：`SPLITBOOK_DB`（預設 splitbook.db）、`SPLITBOOK_SECRET`（正式部署必改）。

## 測試

```bash
python -m pytest splitbook/tests -v
```

## 概念

見 repo root 的 `CONTEXT.md`。
```

`CONTEXT.md`（repo root）：把本計畫開頭的「領域詞彙」表格照抄，並加一段規則摘要：
- 守恆不變量：Σnet = 0，分攤總和 = 支出總額，違反 raise `LedgerImbalance`
- 尾差規則：均分餘數從付款人下一位輪流 +1；權重用整數最大餘數法
- 付款即分錄：結算轉帳直接入帳，餘額自洽；快照僅用於追蹤付款進度
- 過期規則：快照後任何非結算分錄的新增/編輯/刪除（rev > through_rev）即過期

- [ ] **Step 3: .gitignore 追加**

```
splitbook.db
*.db
```

- [ ] **Step 4: 全套測試 + 手動煙霧測試**

Run: `python -m pytest splitbook/tests -v`
Expected: 全部 PASS

Run: `python -c "from splitbook.web.app import create_app; create_app(db_path=':memory:')"`
Expected: 無錯誤（app 可建構）

- [ ] **Step 5: Commit**

```bash
git add splitbook/ CONTEXT.md .gitignore
git commit -m "feat(splitbook): add styling, README and domain glossary"
```

---

## Self-Review 紀錄

1. **Spec 覆蓋**：候選 1（Task 2 帳本核心 + Task 4 寫入時固化）、候選 2（Task 1 分攤規則 + Task 9 表單接線）、候選 3（Task 3/4/5 SQLite repository；Notion adapter 明列為非目標）、候選 4（Task 5 快照 + Task 6 對帳 + Task 11 UI）、候選 5（Task 3 groups schema + Task 7/8 身分與 PIN + created_by 貫穿）、候選 6（routes.py 全程只做表單解析與模板渲染）。
2. **Placeholder 掃描**：無 TBD/TODO；所有步驟含完整程式碼。
3. **型別一致性**：`Entry`/`SettlementLine`/`Snapshot`/`Repo` 簽名已在各 task 的 Interfaces 區塊交叉核對；`payer_id` 在 transfer 語意 = 轉出方，全計畫一致。

