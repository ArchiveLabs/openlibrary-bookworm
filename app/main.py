from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes import batches, health, items


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database import engine
    from app.models import Base
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="BookWorm",
    description="Open Library batch import queue API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(batches.router, prefix="/v1")
app.include_router(items.router, prefix="/v1")
