from notion_client import Client

_notion = None


def _get_client():
    global _notion
    if _notion is None:
        from config import NOTION_TOKEN
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


# ---------------------------------------------------------------------------
# Parsers (pure functions — no Notion client dependency)
# ---------------------------------------------------------------------------

def _get_status(props: dict, key: str) -> str:
    """Get value from a Notion 'status' type property."""
    try:
        return props[key]["status"]["name"]
    except (KeyError, TypeError):
        return ""


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
        "amount": _get_number(props, "總金額"),
        "payer_id": _get_relation_first(props, "付款人"),
        "tags": _get_multi_select(props, "參與標籤"),
        "date": _get_date(props, "日期"),
        "note": _get_rich_text(props, "備註"),
    }


# ---------------------------------------------------------------------------
# Builder (pure function)
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
# API calls
# ---------------------------------------------------------------------------

def get_all_members() -> list[dict]:
    from config import NOTION_MEMBERS_DB_ID
    notion = _get_client()
    response = notion.databases.query(database_id=NOTION_MEMBERS_DB_ID)
    members = [parse_member(page) for page in response["results"]]
    # Filter out cancelled members
    return [m for m in members if m["payment_status"] != "已取消"]


def get_all_expenses() -> list[dict]:
    from config import NOTION_EXPENSES_DB_ID
    notion = _get_client()
    response = notion.databases.query(database_id=NOTION_EXPENSES_DB_ID)
    return [parse_expense(page) for page in response["results"]]


def create_expense(data: dict) -> dict:
    from config import NOTION_EXPENSES_DB_ID
    expenses_db_id = NOTION_EXPENSES_DB_ID
    notion = _get_client()
    properties = {
        "項目名稱": {"title": [{"type": "text", "text": {"content": data["name"]}}]},
        "類別": {"select": {"name": data["category"]}},
        "總金額": {"number": data["amount"]},
        "付款人": {"relation": [{"id": data["payer_id"]}]},
        "參與標籤": {"multi_select": [{"name": t} for t in data.get("tags", [])]},
    }
    if data.get("date"):
        properties["日期"] = {"date": {"start": data["date"]}}
    if data.get("note"):
        properties["備註"] = {
            "rich_text": [{"type": "text", "text": {"content": data["note"]}}]
        }
    response = notion.pages.create(
        parent={"database_id": expenses_db_id},
        properties=properties,
    )
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
        properties["參與標籤"] = {
            "multi_select": [{"name": t} for t in data["tags"]]
        }
    if "date" in data:
        properties["日期"] = {"date": {"start": data["date"]}}
    if "note" in data:
        properties["備註"] = {
            "rich_text": [{"type": "text", "text": {"content": data["note"]}}]
        }
    response = notion.pages.update(page_id=page_id, properties=properties)
    return parse_expense(response)


def delete_expense(page_id: str) -> None:
    notion = _get_client()
    notion.pages.update(page_id=page_id, archived=True)


def write_settlement_batch(member_updates: list[dict]) -> dict:
    """
    Write settlement results to all member pages in Notion.
    member_updates: [{"page_id": str, "properties": dict}]
    Returns: {"success": [page_id], "failed": [page_id]}
    """
    import time
    notion = _get_client()
    success = []
    failed = []
    for item in member_updates:
        retries = 0
        while retries < 3:
            try:
                notion.pages.update(page_id=item["page_id"], properties=item["properties"])
                success.append(item["page_id"])
                break
            except Exception:
                retries += 1
                time.sleep(0.5 * (2 ** retries))
        else:
            failed.append(item["page_id"])
        time.sleep(0.35)
    return {"success": success, "failed": failed}
