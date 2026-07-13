from fastapi import APIRouter, Form, Depends, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api")


def _parse_expense_form(
    name: str = Form(...),
    category: str = Form(...),
    amount: int = Form(..., gt=0),
    payer_id: str = Form(...),
    tags: list[str] = Form([]),
    date: str = Form(""),
    note: str = Form(""),
) -> dict:
    return {"name": name, "category": category, "amount": amount,
            "payer_id": payer_id, "tags": tags, "date": date, "note": note}


@router.post("/expenses")
def api_create_expense(data: dict = Depends(_parse_expense_form)):
    from services.notion import create_expense
    create_expense(data)
    return RedirectResponse("/expenses", status_code=303)


@router.post("/expenses/{expense_id}/update")
def api_update_expense(expense_id: str, data: dict = Depends(_parse_expense_form)):
    from services.notion import update_expense
    update_expense(expense_id, data)
    return RedirectResponse("/expenses", status_code=303)


@router.post("/expenses/{expense_id}/delete")
def api_delete_expense(expense_id: str):
    from services.notion import delete_expense
    delete_expense(expense_id)
    return RedirectResponse("/expenses", status_code=303)


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

def _get_settlement():
    """Fetch data + compute settlement (uses cache)."""
    from services.notion import get_all_data
    from services.settlement import compute_settlement
    from services.cache import cache, SETTLEMENT

    cached = cache.get(SETTLEMENT)
    if cached is not None:
        return cached

    members, expenses, txns = get_all_data()
    result = compute_settlement(members, expenses, txns)
    data = (result, members)
    cache.set(SETTLEMENT, data)
    return data


@router.post("/settle")
def api_settle(request: Request):
    from deps import templates
    result, members = _get_settlement()
    return templates.TemplateResponse("partials/settlement_result.html", {
        "request": request,
        "result": result,
        "members_by_id": {m["id"]: m for m in members},
    })


@router.post("/settle/write")
def api_settle_write():
    from services.notion import build_member_update, write_settlement_batch, get_all_transactions
    from services.settlement import build_settlement_instructions

    result, members = _get_settlement()

    # Build paid_map from 結算轉帳 records: (from_id, to_id) -> total paid
    all_txns = get_all_transactions()
    paid_map: dict[tuple, int] = {}
    for t in all_txns:
        if t["type"] == "結算轉帳":
            key = (t["from_id"], t["to_id"])
            paid_map[key] = paid_map.get(key, 0) + t["amount"]

    updates = []
    for mid, totals in result["member_totals"].items():
        instruction_text = build_settlement_instructions(mid, result["transactions"], paid_map)
        props = build_member_update(
            total_owes=totals["owes"],
            total_paid=totals["total_contributed"],
            net=totals["net"],
            settlement_instruction=instruction_text,
            details=totals["details"],
        )
        updates.append({"page_id": mid, "properties": props})

    write_settlement_batch(updates)
    return RedirectResponse("/settlement?written=1", status_code=303)


# ---------------------------------------------------------------------------
# Payment tracking (匯款紀錄)
# ---------------------------------------------------------------------------

@router.post("/payments")
def api_create_payment(
    request: Request,
    from_id: str = Form(...),
    to_id: str = Form(...),
    amount: int = Form(..., gt=0),
):
    from services.notion import create_payment
    create_payment(from_id, to_id, amount)
    return _render_payment_progress(request)


@router.post("/payments/{txn_id}/undo")
def api_undo_payment(request: Request, txn_id: str):
    from services.notion import delete_transaction
    delete_transaction(txn_id)
    return _render_payment_progress(request)


@router.get("/payments/progress")
def api_payment_progress(request: Request):
    return _render_payment_progress(request)


def _render_payment_progress(request: Request):
    from services.notion import get_all_data
    from services.settlement import compute_settlement, compute_payment_progress
    from deps import templates

    members, expenses, txns = get_all_data()
    result = compute_settlement(members, expenses, txns)
    members_by_id = {m["id"]: m for m in members}

    payment_records = [t for t in txns if t["type"] == "結算轉帳"]
    progress = compute_payment_progress(result["transactions"], payment_records, members_by_id)

    return templates.TemplateResponse("partials/payment_progress.html", {
        "request": request,
        "progress": progress,
    })
