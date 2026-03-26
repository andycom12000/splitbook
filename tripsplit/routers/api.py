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
