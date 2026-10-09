import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi_pagination import add_pagination
from sqlakeyset import BadBookmark
from sqlalchemy import literal
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from bookworm.database import get_engine
from bookworm.dependencies import SessionDep
from bookworm.exceptions import (
    ApplicationError,
    error_responses,
)
from bookworm.imports import router as imports_router
from bookworm.imports.dispatcher import run as run_dispatcher
from bookworm.projects import router as projects_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        async with asyncio.TaskGroup() as tasks:
            dispatcher = tasks.create_task(run_dispatcher())
            try:
                yield
            finally:
                dispatcher.cancel()
    finally:
        # Disposal is synchronous, like every operation on this engine.
        await run_in_threadpool(get_engine().dispose)


app = FastAPI(title="Bookworm", version="0.1.0", lifespan=lifespan)


@app.exception_handler(ApplicationError)
async def application_error(request: Request, exc: ApplicationError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(BadBookmark)
async def invalid_bookmark(request: Request, exc: BadBookmark) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": "Invalid cursor value"})


@app.get("/health/live", tags=["Health"], summary="Check process liveness")
def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/health/ready",
    tags=["Health"],
    summary="Check database readiness",
    responses=error_responses(503),
)
def ready(session: SessionDep) -> dict[str, str]:
    try:
        session.exec(select(literal(1)))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Database unavailable") from exc
    return {"status": "ok"}


app.include_router(projects_router.router)
app.include_router(imports_router.router)
add_pagination(app)
