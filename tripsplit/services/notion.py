import time
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from notion_client import Client
from config import NOTION_TOKEN, NOTION_MEMBERS_DB_ID, NOTION_EXPENSES_DB_ID, NOTION_TRANSACTIONS_DB_ID
from services.cache import cache, MEMBERS, EXPENSES, TRANSACTIONS, SETTLEMENT

_notion = None


def _get_client():
    global _notion
    if _notion is None:
        _notion = Client(auth=NOTION_TOKEN)
    return _notion


# ---------------------------------------------------------------------------
# Property helpers
# ---------------------------------------------------------------------------

def _get_title(props: dict, key: str) -> str:
    try:
        return props[key]["title"][0]["plain_text"]
    except (KeyError, IndexError, TypeError):
        return ""


def _get_select(props: dict, key: str) -> str:
    try:
        return props[key]["select"]["name"]
    except (KeyError, TypeError):
        return ""


def _get_multi_select(props: dict, key: str) -> list[str]:
    try:
        return [item["name"] for item in props[key]["multi_select"]]
    except (KeyError, TypeError):
        return []


def _get_rich_text(props: dict, key: str) -> str:
    try:
        return props[key]["rich_text"][0]["plain_text"]
    except (KeyError, IndexError, TypeError):
        return ""


def _get_number(props: dict, key: str) -> float | None:
    try:
        return props[key]["number"]
    except (KeyError, TypeError):
        return None


def _get_relation_first(props: dict, key: str) -> str:
    try:
        return props[key]["relation"][0]["id"]
    except (KeyError, IndexError, TypeError):
        return ""


def _get_date(props: dict, key: str) -> str:
    try:
        return props[key]["date"]["start"]
    except (KeyError, TypeError):
        return ""


def _get_status(props: dict, key: str) -> str:
    try:
        return props[key]["status"]["name"]
    except (KeyError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_member(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "id": page["id"],
        "name": _get_title(props, "姓名"),
        "payment_status": _get_status(props, "出席狀態"),
        "room": _get_select(props, "房間"),
        "tags": _get_multi_select(props, "參與標籤"),
    }


def parse_expense(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "id": page["id"],
        "name": _get_title(props, "項目名稱"),
        "category": _get_select(props, "類別"),
        "amount": int(_get_number(props, "總金額") or 0),
        "payer_id": _get_relation_first(props, "付款人"),
        "tags": _get_multi_select(props, "排除標籤"),
        "date": _get_date(props, "日期"),
        "note": _get_rich_text(props, "備註"),
    }


def parse_transaction(page: dict) -> dict:
    props = page.get("properties", {})
    return {
        "id": page["id"],
        "note": _get_title(props, "備註"),
        "from_id": _get_relation_first(props, "付款人"),
        "to_id": _get_relation_first(props, "收款人"),
        "amount": int(_get_number(props, "金額") or 0),
        "type": _get_select(props, "類型"),
        "date": _get_date(props, "日期"),
    }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

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
        "結算指示": {
            "rich_text": [{"type": "text", "text": {"content": settlement_instruction}}]
        },
        "費用明細": {
            "rich_text": [{"type": "text", "text": {"content": details_text}}]
        },
    }


# ---------------------------------------------------------------------------
# Cached data fetching
# ---------------------------------------------------------------------------

def get_all_members() -> list[dict]:
    cached = cache.get(MEMBERS)
    if cached is not None:
        return cached
    notion = _get_client()
    response = notion.databases.query(database_id=NOTION_MEMBERS_DB_ID)
    members = [parse_member(page) for page in response["results"]]
    result = [m for m in members if m["payment_status"] != "已取消"]
    cache.set(MEMBERS, result)
    return result


def get_all_expenses() -> list[dict]:
    cached = cache.get(EXPENSES)
    if cached is not None:
        return cached
    notion = _get_client()
    response = notion.databases.query(database_id=NOTION_EXPENSES_DB_ID)
    result = [parse_expense(page) for page in response["results"]]
    cache.set(EXPENSES, result)
    return result


def get_all_transactions() -> list[dict]:
    if not NOTION_TRANSACTIONS_DB_ID:
        return []
    cached = cache.get(TRANSACTIONS)
    if cached is not None:
        return cached
    notion = _get_client()
    response = notion.databases.query(database_id=NOTION_TRANSACTIONS_DB_ID)
    result = [parse_transaction(page) for page in response["results"]]
    cache.set(TRANSACTIONS, result)
    return result


def get_all_data() -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch members, expenses, and transactions in parallel (only uncached)."""
    cached_m = cache.get(MEMBERS)
    cached_e = cache.get(EXPENSES)
    cached_t = cache.get(TRANSACTIONS)

    if cached_m is not None and cached_e is not None and cached_t is not None:
        return cached_m, cached_e, cached_t

    results = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        if cached_m is None:
            futures[executor.submit(get_all_members)] = "members"
        if cached_e is None:
            futures[executor.submit(get_all_expenses)] = "expenses"
        if cached_t is None:
            futures[executor.submit(get_all_transactions)] = "transactions"

        for future in as_completed(futures):
            results[futures[future]] = future.result()

    return (
        cached_m if cached_m is not None else results.get("members", []),
        cached_e if cached_e is not None else results.get("expenses", []),
        cached_t if cached_t is not None else results.get("transactions", []),
    )


def get_tag_options() -> list[str]:
    """Get exclusion tag options from the Members DB schema."""
    try:
        notion = _get_client()
        db = notion.databases.retrieve(database_id=NOTION_MEMBERS_DB_ID)
        tag_prop = db["properties"].get("參與標籤", {})
        return [opt["name"] for opt in tag_prop.get("multi_select", {}).get("options", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Expense CRUD
# ---------------------------------------------------------------------------

def create_expense(data: dict) -> dict:
    notion = _get_client()
    properties = {
        "項目名稱": {"title": [{"type": "text", "text": {"content": data["name"]}}]},
        "類別": {"select": {"name": data["category"]}},
        "總金額": {"number": data["amount"]},
        "付款人": {"relation": [{"id": data["payer_id"]}]},
        "排除標籤": {"multi_select": [{"name": t} for t in data.get("tags", []) if t]},
    }
    if data.get("date"):
        properties["日期"] = {"date": {"start": data["date"]}}
    if data.get("note"):
        properties["備註"] = {
            "rich_text": [{"type": "text", "text": {"content": data["note"]}}]
        }
    response = notion.pages.create(
        parent={"database_id": NOTION_EXPENSES_DB_ID},
        properties=properties,
    )
    cache.invalidate(EXPENSES, SETTLEMENT)
    return parse_expense(response)


def update_expense(page_id: str, data: dict) -> dict:
    notion = _get_client()
    properties = {}
    if "name" in data:
        properties["項目名稱"] = {
            "title": [{"type": "text", "text": {"content": data["name"]}}]
        }
    if "category" in data:
        properties["類別"] = {"select": {"name": data["category"]}}
    if "amount" in data:
        properties["總金額"] = {"number": data["amount"]}
    if "payer_id" in data:
        properties["付款人"] = {"relation": [{"id": data["payer_id"]}]}
    if "tags" in data:
        properties["排除標籤"] = {
            "multi_select": [{"name": t} for t in data["tags"] if t]
        }
    if "date" in data:
        properties["日期"] = {"date": {"start": data["date"]}}
    if "note" in data:
        properties["備註"] = {
            "rich_text": [{"type": "text", "text": {"content": data["note"]}}]
        }
    response = notion.pages.update(page_id=page_id, properties=properties)
    cache.invalidate(EXPENSES, SETTLEMENT)
    return parse_expense(response)


def delete_expense(page_id: str) -> None:
    notion = _get_client()
    notion.pages.update(page_id=page_id, archived=True)
    cache.invalidate(EXPENSES, SETTLEMENT)


# ---------------------------------------------------------------------------
# Payment CRUD (結算轉帳)
# ---------------------------------------------------------------------------

def create_payment(from_id: str, to_id: str, amount: int, note: str = "") -> dict:
    """Create a 結算轉帳 record in the Transaction DB."""
    notion = _get_client()
    properties = {
        "備註": {"title": [{"type": "text", "text": {"content": note or "結算轉帳"}}]},
        "付款人": {"relation": [{"id": from_id}]},
        "收款人": {"relation": [{"id": to_id}]},
        "金額": {"number": amount},
        "類型": {"select": {"name": "結算轉帳"}},
        "日期": {"date": {"start": datetime.date.today().isoformat()}},
    }
    response = notion.pages.create(
        parent={"database_id": NOTION_TRANSACTIONS_DB_ID},
        properties=properties,
    )
    cache.invalidate(TRANSACTIONS, SETTLEMENT)
    return parse_transaction(response)


def delete_transaction(page_id: str) -> None:
    """Archive a transaction record (undo payment)."""
    notion = _get_client()
    notion.pages.update(page_id=page_id, archived=True)
    cache.invalidate(TRANSACTIONS, SETTLEMENT)


# ---------------------------------------------------------------------------
# Settlement batch write (parallelized)
# ---------------------------------------------------------------------------

def write_settlement_batch(member_updates: list[dict]) -> dict:
    """Write settlement results to all member pages in Notion (parallel)."""
    notion = _get_client()

    def update_one(item):
        retries = 0
        while retries < 3:
            try:
                notion.pages.update(page_id=item["page_id"], properties=item["properties"])
                return ("success", item["page_id"])
            except Exception:
                retries += 1
                time.sleep(0.5 * (2 ** retries))
        return ("failed", item["page_id"])

    success = []
    failed = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        for i, item in enumerate(member_updates):
            futures.append(executor.submit(update_one, item))
            if i % 2 == 1:
                time.sleep(0.4)

        for future in as_completed(futures):
            status, page_id = future.result()
            if status == "success":
                success.append(page_id)
            else:
                failed.append(page_id)

    cache.invalidate_all()
    return {"success": success, "failed": failed}
