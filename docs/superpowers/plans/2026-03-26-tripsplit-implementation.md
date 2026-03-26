# TripSplit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mobile-first expense splitting web app for a 40-person group trip, backed by Notion as the data store.

**Architecture:** FastAPI + Jinja2 SSR with htmx for partial updates, Tailwind CSS via CDN for styling. No frontend build step. Each page route reads directly from Notion API. Settlement engine is pure Python with no external dependencies.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx, Tailwind CSS (CDN), notion-client, uvicorn

**Spec:** `docs/superpowers/specs/2026-03-26-tripsplit-design.md`

---

## File Structure

```
tripsplit/
├── main.py                     # FastAPI app entry, mount routers + static
├── deps.py                     # Shared dependencies (Jinja2Templates instance)
├── config.py                   # Settings from .env (NOTION_TOKEN, DB IDs)
├── requirements.txt            # Dependencies
├── .env.example                # Template for environment variables
│
├── routers/
│   ├── pages.py                # GET /, /expenses, /settlement (SSR)
│   └── api.py                  # POST/PUT/DELETE /api/expenses, /api/settle, /api/settle/write
│
├── services/
│   ├── notion.py               # Notion API wrapper: read/write DB1 (members), DB2 (expenses)
│   └── settlement.py           # Settlement engine: compute splits, simplify debts
│
├── templates/
│   ├── base.html               # Shared layout: header, bottom tab bar, Tailwind CDN, htmx CDN
│   ├── members.html            # Members overview page
│   ├── expenses.html           # Expense management page
│   ├── settlement.html         # Settlement preview page
│   └── partials/
│       ├── member_list.html    # htmx fragment: filterable member list
│       ├── expense_form.html   # htmx fragment: new/edit expense modal form
│       └── settlement_result.html  # htmx fragment: settlement preview results
│
├── deploy/
│   ├── nginx.conf              # Nginx config with SSL + basic auth
│   └── tripsplit.service       # systemd service file
│
├── static/
│   └── style.css               # Custom styles (dark mode colors, component overrides)
│
└── tests/
    ├── test_settlement.py      # Unit tests for settlement engine
    └── test_notion.py          # Unit tests for Notion data parsing/formatting
```

---

### Task 1: Project Scaffold & Config

**Files:**
- Create: `tripsplit/main.py`
- Create: `tripsplit/config.py`
- Create: `tripsplit/requirements.txt`
- Create: `tripsplit/.env.example`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.*
uvicorn[standard]==0.34.*
jinja2==3.1.*
notion-client==2.2.*
python-dotenv==1.0.*
httpx==0.28.*
pytest==8.*
```

- [ ] **Step 2: Create .env.example**

```
NOTION_TOKEN=secret_xxx
NOTION_MEMBERS_DB_ID=xxx
NOTION_EXPENSES_DB_ID=xxx
```

- [ ] **Step 3: Create config.py**

```python
from dotenv import load_dotenv
import os

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_MEMBERS_DB_ID = os.environ["NOTION_MEMBERS_DB_ID"]
NOTION_EXPENSES_DB_ID = os.environ["NOTION_EXPENSES_DB_ID"]
```

- [ ] **Step 4: Create main.py**

NOTE: Templates are created in a separate `deps.py` to avoid circular imports between `main.py` and routers.

```python
# main.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from routers import pages, api

app = FastAPI(title="TripSplit")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(pages.router)
app.include_router(api.router)
```

```python
# deps.py
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
```

NOTE: All route handlers that call Notion (synchronous SDK) MUST be regular `def` (not `async def`) so FastAPI automatically runs them in a threadpool, avoiding event loop blocking.

- [ ] **Step 5: Create empty router and service files**

Create empty `__init__.py` files and stub modules:
- `tripsplit/routers/__init__.py`
- `tripsplit/routers/pages.py` (empty router)
- `tripsplit/routers/api.py` (empty router)
- `tripsplit/services/__init__.py`
- `tripsplit/services/notion.py` (empty)
- `tripsplit/services/settlement.py` (empty)
- `tripsplit/tests/__init__.py`

- [ ] **Step 6: Create directory structure for templates and static**

```
tripsplit/templates/partials/  (empty dir)
tripsplit/static/style.css     (empty file)
```

- [ ] **Step 7: Install dependencies and verify app starts**

Run:
```bash
cd tripsplit
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Expected: Server starts, no import errors.

- [ ] **Step 8: Commit**

```bash
git add tripsplit/
git commit -m "feat: scaffold project structure with FastAPI, config, and dependencies"
```

---

### Task 2: Settlement Engine (Pure Logic, No Notion)

**Files:**
- Create: `tripsplit/services/settlement.py`
- Create: `tripsplit/tests/test_settlement.py`

- [ ] **Step 1: Write failing tests for settlement engine**

```python
# tests/test_settlement.py
from services.settlement import compute_settlement, simplify_debts


def test_simplify_debts_basic():
    """Two people: A owes B $100"""
    balances = {"A": -100, "B": 100}
    result = simplify_debts(balances)
    assert result == [{"from": "A", "to": "B", "amount": 100}]


def test_simplify_debts_three_people():
    """A owes 200, B is owed 120, C is owed 80"""
    balances = {"A": -200, "B": 120, "C": 80}
    result = simplify_debts(balances)
    assert result == [
        {"from": "A", "to": "B", "amount": 120},
        {"from": "A", "to": "C", "amount": 80},
    ]


def test_simplify_debts_zero_balance_excluded():
    """Person with 0 balance produces no transactions"""
    balances = {"A": -100, "B": 100, "C": 0}
    result = simplify_debts(balances)
    assert len(result) == 1
    assert result[0] == {"from": "A", "to": "B", "amount": 100}


def test_compute_settlement_basic():
    """One expense, 3 participants, 1 payer"""
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
        {"id": "m2", "name": "Bob", "tags": ["全程"]},
        {"id": "m3", "name": "Carol", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 300, "payer_id": "m1", "tags": ["全程"]},
    ]
    result = compute_settlement(members, expenses)
    assert result["member_totals"]["m1"]["owed"] == 300  # Alice paid
    assert result["member_totals"]["m1"]["owes"] == 100  # Alice's share
    assert result["member_totals"]["m1"]["net"] == 200   # Alice is owed 200
    assert result["member_totals"]["m2"]["net"] == -100
    assert result["member_totals"]["m3"]["net"] == -100


def test_compute_settlement_floor_remainder():
    """floor(100/3)=33, remainder 1 absorbed by payer (payer share = 34)"""
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
        {"id": "m2", "name": "Bob", "tags": ["全程"]},
        {"id": "m3", "name": "Carol", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "餐費", "amount": 100, "payer_id": "m1", "tags": ["全程"]},
    ]
    result = compute_settlement(members, expenses)
    # floor(100/3) = 33, remainder = 1, payer share = 33 + 1 = 34
    assert result["member_totals"]["m1"]["owes"] == 34
    assert result["member_totals"]["m1"]["owed"] == 100
    assert result["member_totals"]["m1"]["net"] == 66  # 100 - 34
    assert result["member_totals"]["m2"]["net"] == -33
    assert result["member_totals"]["m3"]["net"] == -33


def test_compute_settlement_multiple_expenses():
    """Multiple expenses accumulate correctly"""
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程", "酒水"]},
        {"id": "m2", "name": "Bob", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "民宿", "amount": 200, "payer_id": "m1", "tags": ["全程"]},
        {"id": "e2", "name": "酒", "amount": 100, "payer_id": "m2", "tags": ["酒水"]},
    ]
    result = compute_settlement(members, expenses)
    # 民宿: 200/2=100 each. Alice paid 200, owes 100. Bob owes 100.
    # 酒: only Alice has 酒水 tag. 100/1=100. Bob paid 100, Alice owes 100.
    # Alice: owed 200, owes 100+100=200, net=0
    # Bob: owed 100, owes 100, net=0
    assert result["member_totals"]["m1"]["net"] == 0
    assert result["member_totals"]["m2"]["net"] == 0


def test_compute_settlement_union_tags():
    """Tags use union: expense tagged 全程+酒水 includes anyone with either tag"""
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
        {"id": "m2", "name": "Bob", "tags": ["全程", "酒水"]},
        {"id": "m3", "name": "Carol", "tags": ["酒水"]},
    ]
    expenses = [
        {"id": "e1", "name": "酒", "amount": 300, "payer_id": "m2", "tags": ["酒水"]},
    ]
    result = compute_settlement(members, expenses)
    # Only Bob and Carol have 酒水 tag -> 2 people
    assert result["member_totals"]["m2"]["owes"] == 150
    assert result["member_totals"]["m3"]["owes"] == 150
    assert "m1" not in result["member_totals"] or result["member_totals"]["m1"]["owes"] == 0


def test_compute_settlement_zero_participants_warning():
    """Expense with tag matching no one should be skipped with warning"""
    members = [
        {"id": "m1", "name": "Alice", "tags": ["全程"]},
    ]
    expenses = [
        {"id": "e1", "name": "VIP", "amount": 500, "payer_id": "m1", "tags": ["VIP"]},
    ]
    result = compute_settlement(members, expenses)
    assert len(result["warnings"]) > 0
    assert "VIP" in result["warnings"][0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tripsplit && python -m pytest tests/test_settlement.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement settlement engine**

```python
# services/settlement.py
from math import floor


def simplify_debts(balances: dict[str, int]) -> list[dict]:
    """Minimize transactions to settle all debts. All amounts are integer TWD."""
    debtors = []
    creditors = []

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
            "amount": amount,
        })
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1

    return transactions


def compute_settlement(
    members: list[dict], expenses: list[dict]
) -> dict:
    """
    Compute expense splits and settlement transactions.

    members: [{"id", "name", "tags": [str]}]
    expenses: [{"id", "name", "amount": int, "payer_id": str, "tags": [str]}]

    Returns: {
        "member_totals": {member_id: {"name", "owed": int, "owes": int, "net": int, "details": [str]}},
        "transactions": [{"from": id, "to": id, "amount": int}],
        "warnings": [str],
    }
    """
    warnings = []
    # Track per-member: total paid (owed back) and total share (owes)
    totals: dict[str, dict] = {}
    for m in members:
        totals[m["id"]] = {"name": m["name"], "owed": 0, "owes": 0, "net": 0, "details": []}

    members_by_id = {m["id"]: m for m in members}
    tag_index: dict[str, set[str]] = {}
    for m in members:
        for tag in m["tags"]:
            tag_index.setdefault(tag, set()).add(m["id"])

    for exp in expenses:
        # Find participants via union of tags
        participant_ids: set[str] = set()
        for tag in exp["tags"]:
            participant_ids |= tag_index.get(tag, set())

        if not participant_ids:
            warnings.append(f"帳目「{exp['name']}」的標籤匹配不到任何人，已跳過")
            continue

        n = len(participant_ids)
        per_person = floor(exp["amount"] / n)
        remainder = exp["amount"] - per_person * n

        # Credit payer
        payer_id = exp["payer_id"]
        if payer_id in totals:
            totals[payer_id]["owed"] += exp["amount"]

        # Debit each participant
        for pid in participant_ids:
            share = per_person + (remainder if pid == payer_id else 0)
            if pid in totals:
                totals[pid]["owes"] += share
                totals[pid]["details"].append(
                    f"{exp['name']}：${share}（{n}人均分）"
                )

    # Compute net balances
    balances = {}
    for mid, t in totals.items():
        t["net"] = t["owed"] - t["owes"]
        if t["net"] != 0 or t["owed"] > 0 or t["owes"] > 0:
            balances[mid] = t["net"]

    transactions = simplify_debts(balances)

    # Resolve names in transactions
    for tx in transactions:
        tx["from_name"] = totals[tx["from"]]["name"]
        tx["to_name"] = totals[tx["to"]]["name"]

    return {
        "member_totals": totals,
        "transactions": transactions,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tripsplit && python -m pytest tests/test_settlement.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add tripsplit/services/settlement.py tripsplit/tests/test_settlement.py
git commit -m "feat: implement settlement engine with floor rounding and debt simplification"
```

---

### Task 3: Notion API Service

**Files:**
- Create: `tripsplit/services/notion.py`
- Create: `tripsplit/tests/test_notion.py`

- [ ] **Step 1: Write tests for Notion data parsing helpers**

```python
# tests/test_notion.py
from services.notion import parse_member, parse_expense, build_member_update


def test_parse_member():
    """Parse a Notion page into a member dict"""
    page = {
        "id": "page-id-1",
        "properties": {
            "名字": {"title": [{"plain_text": "王小明"}]},
            "繳費狀態": {"select": {"name": "已繳"}},
            "分房": {"rich_text": [{"plain_text": "A01"}]},
            "參與標籤": {"multi_select": [{"name": "全程"}, {"name": "酒水"}]},
        },
    }
    result = parse_member(page)
    assert result["id"] == "page-id-1"
    assert result["name"] == "王小明"
    assert result["payment_status"] == "已繳"
    assert result["room"] == "A01"
    assert result["tags"] == ["全程", "酒水"]


def test_parse_expense():
    """Parse a Notion page into an expense dict"""
    page = {
        "id": "exp-id-1",
        "properties": {
            "項目名稱": {"title": [{"plain_text": "民宿費"}]},
            "類別": {"select": {"name": "民宿"}},
            "總金額": {"number": 40000},
            "付款人": {"relation": [{"id": "page-id-1"}]},
            "參與標籤": {"multi_select": [{"name": "全程"}]},
            "日期": {"date": {"start": "2026-04-15"}},
            "備註": {"rich_text": [{"plain_text": "兩棟民宿"}]},
        },
    }
    result = parse_expense(page)
    assert result["id"] == "exp-id-1"
    assert result["name"] == "民宿費"
    assert result["category"] == "民宿"
    assert result["amount"] == 40000
    assert result["payer_id"] == "page-id-1"
    assert result["tags"] == ["全程"]
    assert result["date"] == "2026-04-15"
    assert result["note"] == "兩棟民宿"


def test_build_member_update():
    """Build Notion page update payload for settlement results"""
    update = build_member_update(
        total_owes=4660,
        total_paid=40000,
        net=35340,
        settlement_instruction="收回 $35,340",
        details=["民宿費：$1,000（40人均分）", "餐費：$500（40人均分）"],
    )
    assert update["應付總額"]["number"] == 4660
    assert update["已付/代墊金額"]["number"] == 40000
    assert update["淨餘額"]["number"] == 35340
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd tripsplit && python -m pytest tests/test_notion.py -v`
Expected: FAIL

- [ ] **Step 3: Implement Notion service**

```python
# services/notion.py
import asyncio
from notion_client import Client
from config import NOTION_TOKEN, NOTION_MEMBERS_DB_ID, NOTION_EXPENSES_DB_ID

notion = Client(auth=NOTION_TOKEN)


# --- Parsers ---

def parse_member(page: dict) -> dict:
    props = page["properties"]
    return {
        "id": page["id"],
        "name": _get_title(props.get("名字")),
        "payment_status": _get_select(props.get("繳費狀態")),
        "room": _get_rich_text(props.get("分房")),
        "tags": _get_multi_select(props.get("參與標籤")),
    }


def parse_expense(page: dict) -> dict:
    props = page["properties"]
    return {
        "id": page["id"],
        "name": _get_title(props.get("項目名稱")),
        "category": _get_select(props.get("類別")),
        "amount": _get_number(props.get("總金額")),
        "payer_id": _get_relation_first(props.get("付款人")),
        "tags": _get_multi_select(props.get("參與標籤")),
        "date": _get_date(props.get("日期")),
        "note": _get_rich_text(props.get("備註")),
    }


def build_member_update(
    total_owes: int,
    total_paid: int,
    net: int,
    settlement_instruction: str,
    details: list[str],
) -> dict:
    details_text = "\n".join(details)
    return {
        "應付總額": {"number": total_owes},
        "已付/代墊金額": {"number": total_paid},
        "淨餘額": {"number": net},
        "結算指示": {"rich_text": [{"text": {"content": settlement_instruction}}]},
        "帳目明細": {"rich_text": [{"text": {"content": details_text}}]},
    }


# --- API calls ---

def get_all_members() -> list[dict]:
    response = notion.databases.query(database_id=NOTION_MEMBERS_DB_ID)
    return [parse_member(page) for page in response["results"]]


def get_all_expenses() -> list[dict]:
    response = notion.databases.query(database_id=NOTION_EXPENSES_DB_ID)
    return [parse_expense(page) for page in response["results"]]


def create_expense(data: dict) -> dict:
    page = notion.pages.create(
        parent={"database_id": NOTION_EXPENSES_DB_ID},
        properties={
            "項目名稱": {"title": [{"text": {"content": data["name"]}}]},
            "類別": {"select": {"name": data["category"]}},
            "總金額": {"number": data["amount"]},
            "付款人": {"relation": [{"id": data["payer_id"]}]},
            "參與標籤": {"multi_select": [{"name": t} for t in data["tags"]]},
            "日期": {"date": {"start": data["date"]}},
            "備註": {"rich_text": [{"text": {"content": data.get("note", "")}}]},
        },
    )
    return parse_expense(page)


def update_expense(page_id: str, data: dict) -> dict:
    props = {}
    if "name" in data:
        props["項目名稱"] = {"title": [{"text": {"content": data["name"]}}]}
    if "category" in data:
        props["類別"] = {"select": {"name": data["category"]}}
    if "amount" in data:
        props["總金額"] = {"number": data["amount"]}
    if "payer_id" in data:
        props["付款人"] = {"relation": [{"id": data["payer_id"]}]}
    if "tags" in data:
        props["參與標籤"] = {"multi_select": [{"name": t} for t in data["tags"]]}
    if "date" in data:
        props["日期"] = {"date": {"start": data["date"]}}
    if "note" in data:
        props["備註"] = {"rich_text": [{"text": {"content": data["note"]}}]}
    page = notion.pages.update(page_id=page_id, properties=props)
    return parse_expense(page)


def delete_expense(page_id: str):
    notion.pages.update(page_id=page_id, archived=True)


def write_settlement_to_member(page_id: str, update_props: dict):
    """Write settlement results to a member's page. Call with 350ms delay between calls."""
    notion.pages.update(page_id=page_id, properties=update_props)


import time

def write_settlement_batch(member_updates: list[dict]) -> dict:
    """
    Write settlement results to all members.
    member_updates: [{"page_id": str, "properties": dict}]
    Returns: {"success": [page_id], "failed": [page_id]}
    """
    success = []
    failed = []
    for item in member_updates:
        retries = 0
        while retries < 3:
            try:
                write_settlement_to_member(item["page_id"], item["properties"])
                success.append(item["page_id"])
                break
            except Exception:
                retries += 1
                time.sleep(0.5 * (2 ** retries))
        else:
            failed.append(item["page_id"])
        time.sleep(0.35)  # Rate limit: 3 req/sec
    return {"success": success, "failed": failed}


# --- Property helpers ---

def _get_title(prop) -> str:
    if not prop or not prop.get("title"):
        return ""
    return prop["title"][0]["plain_text"] if prop["title"] else ""

def _get_select(prop) -> str:
    if not prop or not prop.get("select"):
        return ""
    return prop["select"]["name"]

def _get_multi_select(prop) -> list[str]:
    if not prop or not prop.get("multi_select"):
        return []
    return [item["name"] for item in prop["multi_select"]]

def _get_rich_text(prop) -> str:
    if not prop or not prop.get("rich_text"):
        return ""
    return prop["rich_text"][0]["plain_text"] if prop["rich_text"] else ""

def _get_number(prop) -> int:
    if not prop or prop.get("number") is None:
        return 0
    return int(prop["number"])

def _get_relation_first(prop) -> str:
    if not prop or not prop.get("relation"):
        return ""
    return prop["relation"][0]["id"] if prop["relation"] else ""

def _get_date(prop) -> str:
    if not prop or not prop.get("date") or not prop["date"]:
        return ""
    return prop["date"].get("start", "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tripsplit && python -m pytest tests/test_notion.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add tripsplit/services/notion.py tripsplit/tests/test_notion.py
git commit -m "feat: implement Notion API service with parsers and batch write"
```

---

### Task 4: Base Template & Static Assets

**Files:**
- Create: `tripsplit/templates/base.html`
- Create: `tripsplit/static/style.css`

- [ ] **Step 1: Create base.html with dark mode layout, bottom tab bar, Tailwind CDN, htmx CDN**

Key elements:
- `<meta name="viewport" content="width=device-width, initial-scale=1.0">`
- Tailwind CSS via CDN `<script src="https://cdn.tailwindcss.com"></script>` with custom dark theme colors
- htmx via CDN `<script src="https://unpkg.com/htmx.org@2.0.4"></script>`
- Google Fonts: Fira Sans + Fira Code
- Bottom tab bar with 3 tabs: 人員, 帳目, 結算
- Content block `{% block content %}{% endblock %}`
- Dark mode colors: bg `#0F172A`, card bg `#1E293B`, border `#334155`
- Touch targets >= 44px

- [ ] **Step 2: Create style.css with component classes**

Custom classes for:
- `.stat-card`, `.member-item`, `.expense-item`
- `.tag-paid`, `.tag-unpaid`, `.tag-partial`, `.tag-group`
- `.avatar` (colored initial circle)
- `.amount`, `.amount-positive`, `.amount-negative`
- Loading spinner animation

- [ ] **Step 3: Verify base template renders**

Create a minimal page route in `routers/pages.py`:
```python
from fastapi import APIRouter, Request
from deps import templates

router = APIRouter()

@router.get("/")
def members_page(request: Request):
    return templates.TemplateResponse("base.html", {"request": request})
```

Run: `cd tripsplit && uvicorn main:app --reload --port 8000`
Open http://localhost:8000 in browser, verify dark mode layout with bottom tab bar.

- [ ] **Step 4: Commit**

```bash
git add tripsplit/templates/base.html tripsplit/static/style.css tripsplit/routers/pages.py
git commit -m "feat: create base template with dark mode, bottom tab bar, Tailwind and htmx"
```

---

### Task 5: Members Overview Page

**Files:**
- Modify: `tripsplit/routers/pages.py`
- Create: `tripsplit/templates/members.html`
- Create: `tripsplit/templates/partials/member_list.html`

- [ ] **Step 1: Implement GET / route**

```python
@router.get("/")
def members_page(request: Request):
    try:
        members = get_all_members()
    except Exception as e:
        members = []
        error = str(e)
    # Group by status
    needs_payment = [m for m in members if m.get("net", 0) < 0]
    owed_back = [m for m in members if m.get("net", 0) > 0]
    settled = [m for m in members if m.get("net", 0) == 0]
    total_expense = sum(m.get("total_owes", 0) for m in members)
    paid_count = sum(1 for m in members if m["payment_status"] == "已繳")
    return templates.TemplateResponse("members.html", {
        "request": request,
        "members": members,
        "needs_payment": needs_payment,
        "owed_back": owed_back,
        "settled": settled,
        "total": len(members),
        "total_expense": total_expense,
        "paid_count": paid_count,
        "active_tab": "members",
    })
```

- [ ] **Step 2: Create members.html extending base.html**

Includes:
- Summary banner (total, expense count, total cost, progress bar)
- Settle button
- Member list grouped by status sections
- Empty state when no members

- [ ] **Step 3: Create partials/member_list.html for htmx filtering**

Htmx fragment that renders just the member list, used by `GET /htmx/members?filter={status}`.

- [ ] **Step 4: Add htmx route for member filtering**

```python
@router.get("/htmx/members")
def htmx_members(request: Request, filter: str = "all"):
    members = get_all_members()
    if filter == "unpaid":
        members = [m for m in members if m["payment_status"] != "已繳"]
    elif filter == "paid":
        members = [m for m in members if m["payment_status"] == "已繳"]
    return templates.TemplateResponse("partials/member_list.html", {
        "request": request,
        "members": members,
    })
```

- [ ] **Step 5: Test in browser with real Notion data**

Requires `.env` with real Notion credentials. Verify:
- Members load and display correctly
- Status grouping works
- Filter chips update list via htmx
- Empty state shows when no data

- [ ] **Step 6: Commit**

```bash
git add tripsplit/routers/pages.py tripsplit/templates/members.html tripsplit/templates/partials/member_list.html
git commit -m "feat: implement members overview page with status grouping and htmx filtering"
```

---

### Task 6: Expense Management Page

**Files:**
- Modify: `tripsplit/routers/pages.py`
- Modify: `tripsplit/routers/api.py`
- Create: `tripsplit/templates/expenses.html`
- Create: `tripsplit/templates/partials/expense_form.html`

- [ ] **Step 1: Implement GET /expenses route**

Read DB2 expenses + DB1 members (for payer name resolution). Sort expenses by date.

- [ ] **Step 2: Create expenses.html**

- Expense list with category icons, amount, payer name, tags
- Empty state with "新增帳目" button
- Each expense row has edit/delete actions

- [ ] **Step 3: Create partials/expense_form.html**

Modal form with:
- 項目名稱 (text input, required)
- 類別 (select: 民宿/餐費/保險/酒水/雜支)
- 總金額 (number input, min=1, required, positive integer validation)
- 付款人 (select dropdown populated from members, required)
- 參與標籤 (multi-select checkboxes from available tags)
- 日期 (date input)
- 備註 (textarea)
- Submit button posts to `/api/expenses`

- [ ] **Step 4: Add htmx route for expense form**

```python
@router.get("/htmx/expense-form")
def htmx_expense_form(request: Request, id: str = None):
    members = get_all_members()
    expense = None
    if id:
        # Fetch single expense for editing
        expenses = get_all_expenses()
        expense = next((e for e in expenses if e["id"] == id), None)
    return templates.TemplateResponse("partials/expense_form.html", {
        "request": request,
        "members": members,
        "expense": expense,
    })
```

- [ ] **Step 5: Implement expense CRUD API routes**

```python
# routers/api.py
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from services.notion import create_expense, update_expense, delete_expense

router = APIRouter(prefix="/api")

@router.post("/expenses")
def api_create_expense(
    name: str = Form(...),
    category: str = Form(...),
    amount: int = Form(..., gt=0),
    payer_id: str = Form(...),
    tags: list[str] = Form(...),
    date: str = Form(""),
    note: str = Form(""),
):
    data = {"name": name, "category": category, "amount": amount,
            "payer_id": payer_id, "tags": tags, "date": date, "note": note}
    create_expense(data)
    return RedirectResponse("/expenses", status_code=303)

@router.post("/expenses/{expense_id}/update")
def api_update_expense(
    expense_id: str,
    name: str = Form(...),
    category: str = Form(...),
    amount: int = Form(..., gt=0),
    payer_id: str = Form(...),
    tags: list[str] = Form(...),
    date: str = Form(""),
    note: str = Form(""),
):
    data = {"name": name, "category": category, "amount": amount,
            "payer_id": payer_id, "tags": tags, "date": date, "note": note}
    update_expense(expense_id, data)
    return RedirectResponse("/expenses", status_code=303)

@router.post("/expenses/{expense_id}/delete")
def api_delete_expense(expense_id: str):
    delete_expense(expense_id)
    return RedirectResponse("/expenses", status_code=303)
```

- [ ] **Step 6: Test CRUD in browser**

- Create a new expense via the form
- Verify it appears in the list
- Edit the expense
- Delete the expense
- Verify form validation (empty name, zero amount)

- [ ] **Step 7: Commit**

```bash
git add tripsplit/routers/ tripsplit/templates/expenses.html tripsplit/templates/partials/expense_form.html
git commit -m "feat: implement expense management page with CRUD and htmx modal form"
```

---

### Task 7: Settlement Preview & Write-back Page

**Files:**
- Modify: `tripsplit/routers/pages.py`
- Modify: `tripsplit/routers/api.py`
- Create: `tripsplit/templates/settlement.html`
- Create: `tripsplit/templates/partials/settlement_result.html`

- [ ] **Step 1: Implement GET /settlement route**

Render settlement page with empty state (no results yet).

- [ ] **Step 2: Create settlement.html**

- Empty state: "點擊下方按鈕執行結算" + button
- Results state (shown after POST /api/settle via htmx):
  - Warnings section (if any)
  - Transaction list: "A → B, $金額"
  - Per-member breakdown (expandable)
  - "寫回 Notion" confirmation button
- Loading state for write-back

- [ ] **Step 3: Implement POST /api/settle**

```python
@router.post("/settle")
def api_settle(request: Request):
    members = get_all_members()
    expenses = get_all_expenses()
    result = compute_settlement(members, expenses)
    return templates.TemplateResponse("partials/settlement_result.html", {
        "request": request,
        "result": result,
        "members_by_id": {m["id"]: m for m in members},
    })
```

Returns HTML fragment with preview results, displayed via htmx.

- [ ] **Step 4: Implement POST /api/settle/write**

```python
@router.post("/settle/write")
def api_settle_write(request: Request):
    members = get_all_members()
    expenses = get_all_expenses()
    result = compute_settlement(members, expenses)

    # Build updates for each member
    updates = []
    for mid, totals in result["member_totals"].items():
        # Build settlement instruction
        instructions = []
        for tx in result["transactions"]:
            if tx["from"] == mid:
                instructions.append(f"轉 ${tx['amount']:,} 給 {tx['to_name']}")
            elif tx["to"] == mid:
                instructions.append(f"收 ${tx['amount']:,} 從 {tx['from_name']}")
        instruction_text = "\n".join(instructions) if instructions else "已結清"

        props = build_member_update(
            total_owes=totals["owes"],
            total_paid=totals["owed"],
            net=totals["net"],
            settlement_instruction=instruction_text,
            details=totals["details"],
        )
        updates.append({"page_id": mid, "properties": props})

    write_result = write_settlement_batch(updates)
    return templates.TemplateResponse("settlement.html", {
        "request": request,
        "write_result": write_result,
        "result": result,
        "active_tab": "settlement",
    })
```

- [ ] **Step 5: Test full settlement flow**

1. Ensure members exist in Notion DB1 with tags
2. Create expenses in DB2 via the app
3. Go to settlement page, click "執行結算"
4. Verify preview shows correct transactions
5. Click "寫回 Notion"
6. Wait ~15 seconds
7. Check Notion DB1 — verify fields are populated

- [ ] **Step 6: Commit**

```bash
git add tripsplit/routers/ tripsplit/templates/settlement.html
git commit -m "feat: implement settlement preview and Notion write-back"
```

---

### Task 8: Polish & Mobile UX

**Files:**
- Modify: `tripsplit/templates/base.html`
- Modify: `tripsplit/static/style.css`
- Modify: all template files as needed

- [ ] **Step 1: Verify mobile layout on 375px viewport**

Open Chrome DevTools, set device to iPhone SE (375×667). Check:
- Bottom tab bar visible and tappable (>= 44px targets)
- Summary banner readable
- Member cards not overflowing
- Expense form usable on mobile

- [ ] **Step 2: Fix any mobile layout issues**

Common fixes: overflow-x hidden, proper padding, font-size minimums.

- [ ] **Step 3: Add loading states**

- Settle button shows spinner during calculation
- Write-back shows "寫入中，約需 15 秒..." with spinner
- Expense form submit shows loading

- [ ] **Step 4: Add error display**

- Notion API errors show toast/alert at top of page
- Write-back failures show list of failed members

- [ ] **Step 5: Test end-to-end on mobile browser**

Use phone or Chrome DevTools mobile emulation. Full flow:
1. Open app → see members
2. Go to expenses → add an expense
3. Go to settlement → settle → write back
4. Return to members → verify updated data

- [ ] **Step 6: Commit**

```bash
git add tripsplit/
git commit -m "feat: polish mobile UX, add loading states and error handling"
```

---

### Task 9: Deployment Setup

**Files:**
- Create: `tripsplit/deploy/nginx.conf`
- Create: `tripsplit/deploy/tripsplit.service`

- [ ] **Step 1: Create Nginx config**

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    auth_basic "TripSplit";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location /static/ {
        alias /opt/tripsplit/static/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
```

- [ ] **Step 2: Create systemd service**

```ini
[Unit]
Description=TripSplit
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/tripsplit
EnvironmentFile=/opt/tripsplit/.env
ExecStart=/opt/tripsplit/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Document deployment steps in README**

Quick deployment checklist:
1. Clone repo to `/opt/tripsplit`
2. Create venv, install deps
3. Copy `.env.example` to `.env`, fill in Notion credentials
4. Copy nginx.conf, create `.htpasswd`
5. Enable systemd service
6. Setup Let's Encrypt

- [ ] **Step 4: Commit**

```bash
git add tripsplit/deploy/ README.md
git commit -m "feat: add deployment config for Nginx and systemd"
```
