from fastapi import APIRouter, Request
from deps import templates

router = APIRouter()


@router.get("/")
def members_page(request: Request):
    return templates.TemplateResponse("base.html", {
        "request": request,
        "active_tab": "members",
    })
