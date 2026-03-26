from fastapi import APIRouter, Form, Depends, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api")


def _parse_expense_form(
    name: str = Form(...),
    category: str = Form(...),
    amount: int = Form(..., gt=0),
    payer_id: str = Form(...),
    tags: list[str] = Form(...),
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


@router.post("/settle")
def api_settle(request: Request):
    from services.notion import get_all_members, get_all_expenses
    from services.settlement import compute_settlement
    from deps import templates

    members = get_all_members()
    expenses = get_all_expenses()
    result = compute_settlement(members, expenses)

    return templates.TemplateResponse("partials/settlement_result.html", {
        "request": request,
        "result": result,
        "members_by_id": {m["id"]: m for m in members},
    })


@router.post("/settle/write")
def api_settle_write():
    from services.notion import get_all_members, get_all_expenses, build_member_update, write_settlement_batch
    from services.settlement import compute_settlement, build_settlement_instructions

    members = get_all_members()
    expenses = get_all_expenses()
    result = compute_settlement(members, expenses)

    updates = []
    for mid, totals in result["member_totals"].items():
        instruction_text = build_settlement_instructions(mid, result["transactions"])
        props = build_member_update(
            total_owes=totals["owes"],
            total_paid=totals["owed"],
            net=totals["net"],
            settlement_instruction=instruction_text,
            details=totals["details"],
        )
        updates.append({"page_id": mid, "properties": props})

    write_result = write_settlement_batch(updates)
    return RedirectResponse("/settlement?written=1", status_code=303)
