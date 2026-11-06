import os
import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
import psycopg
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.db import run_migrations
from app.db.seed import seed_if_empty
from app.api.routes import router


logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        seed_if_empty(connection)
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ops", status_code=302)


@app.get("/ops", include_in_schema=False)
def ops_page() -> FileResponse:
    response = FileResponse("app/static/ops.html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}