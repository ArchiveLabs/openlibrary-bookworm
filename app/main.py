from fastapi import FastAPI

from app.routes import batches, health, items

app = FastAPI(
    title="BookWorm",
    description="Open Library batch import queue API",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(batches.router, prefix="/v1")
app.include_router(items.router, prefix="/v1")
