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
