"""uvicorn 入口：uvicorn splitbook.main:app（從 repo root 執行）"""
from splitbook.web.app import create_app

app = create_app()
