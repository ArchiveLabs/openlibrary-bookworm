# OpenLibrary BookWorm

BookWorm is a lightweight FastAPI service that wraps the Open Library batch import queue tables (`import_batch`, `import_item`). It provides a clean API surface for submitting, inspecting, and draining import batches without touching the production Open Library database.

## Architecture

```
POST /v1/batches            — create a named batch
POST /v1/batches/{id}/items — append items to a batch (JSON array of edition records)
GET  /v1/batches/{id}       — batch detail + per-status item counts
GET  /v1/items/pending      — next N pending items (for ImportBot)
PATCH /v1/items/{id}        — update item status (for ImportBot to report back)
GET  /health                — health check
```

Auth: `Authorization: Bearer <key>` on write endpoints. Keys are set via `API_KEYS` env var (comma-separated).

## Quick start

```bash
cp .env.example .env
# edit .env with your values
docker compose up -d
docker compose exec api alembic upgrade head
```

API is at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# start db only
docker compose up -d db
alembic upgrade head

uvicorn app.main:app --reload
```

## Tests

Tests use SQLite in memory. No running database required.

```bash
pytest -v
```
