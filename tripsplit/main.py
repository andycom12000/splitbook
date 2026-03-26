from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from routers import pages, api

app = FastAPI(title="TripSplit")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(pages.router)
app.include_router(api.router)
