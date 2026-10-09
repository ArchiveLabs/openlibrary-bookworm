# Bookworm

An internal FastAPI service for reviewing and dispatching Open Library imports. It uses Postgres, Procrastinate, SQLModel, Pydantic, Alembic, pytest, and Docker.

The Open Library client temporarily waits 2–5 seconds and returns success for concurrency testing; no requests are sent to Open Library. Replace it before real imports. Tests mock the client explicitly.

## Run

```bash
rtk proxy docker compose up --build -d
```

The API is at `http://localhost:8000`, with interactive documentation at `/docs`. Compose runs Postgres, a one-shot migration, and the API. The dispatcher runs inside the API process. Only Postgres uses a persistent volume. Uploaded JSON is never written to files.

For local development:

```bash
rtk proxy uv sync --frozen
rtk proxy docker compose up -d postgres
rtk proxy uv run alembic upgrade head
rtk proxy uv run uvicorn bookworm.main:app --reload
```

Settings are documented in `.env.example`. Copy it to `.env` for local development if needed. Compose supplies its database URL directly. To customize Compose settings, add environment values to the API service; host `.env` settings are not automatically passed into containers.

## Internal identity

Supply `X-User-Id` on every application request. `X-Can-Approve: true` grants cross-user job access and approval/retry permission; it does not grant access to another user's project management.

These headers are trusted identity assertions, not authentication. Put production behind a trusted internal gateway that authenticates callers and overwrites both headers. Compose binds ports to localhost and uses development database credentials.

## API

| Endpoint | Behavior |
| --- | --- |
| `POST /projects` | Create with `{ "name": "My project" }` |
| `GET /projects` | List caller's active projects; `include_archived=true` includes archived projects |
| `GET /projects/{id}` | Read caller's project |
| `PATCH /projects/{id}` | Rename with `{ "name": "New name" }` |
| `DELETE /projects/{id}` | Archive, preserving jobs and reservations |
| `POST /imports` | Validate a JSON request; return HTTP 202 with `job_id` after the transaction commits |
| `GET /imports` | List accessible jobs |
| `GET /imports/{id}` | Job metadata, counts, and paginated item data/status/errors |
| `POST /imports/{id}/approve` | Approver only: `{ "all": true }` or `{ "item_ids": ["UUID"] }` |
| `POST /imports/{id}/retry` | Approver only: same selection shape, for eligible failed records |
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Database connectivity |

All paginated endpoints use [fastapi-pagination](https://github.com/uriyyo/fastapi-pagination) cursor pagination through its SQLModel integration. Use `size` (default 100, maximum 1,000) and pass the returned opaque `next_page` value as `cursor` to fetch the next page. Responses also include `previous_page`, `current_page`, `current_page_backwards`, and `total`. Job detail retains its job metadata and status counts; its total counts all job records even when filtering by status. Keep the same status filter while paging. Input positions still start at zero; cursors are no longer positions. The old `limit` parameter and `next_cursor` response field are replaced by the library interface.

An upload looks like:

```json
{
  "project_id": "00000000-0000-0000-0000-000000000001",
  "data": [
    {
      "title": "An example book",
      "source_records": ["vendor:123"],
      "authors": [{"name": "An Author"}],
      "publishers": ["A Publisher"],
      "publish_date": "2020"
    }
  ]
}
```

Omit `project_id` or supply `null` to disable project deduplication. Records follow the vendored Open Library import schema. Its source commit is recorded in `bookworm/imports/schemata/UPSTREAM`; validation resolves all references locally and does not coerce types.

Send JSON with `Content-Type: application/json`. Configure the production gateway or reverse proxy to enforce the upload size limit (for example, 100 MiB). The application and local Compose setup do not impose a request body size limit.

FastAPI validates the envelope and every record through Pydantic before ingestion starts. A Pydantic hook checks records against the vendored JSON Schema; project imports also validate source identifiers. Invalid input returns HTTP 422 without creating a job or items. Ingestion creates the job and its items in one synchronous database transaction. Requests are buffered in memory, so memory use grows with the complete upload; use several smaller jobs for large datasets. HTTP 202 means all records have been durably accepted and classified; there is no separate ingestion worker. Keep proxy/client timeouts long enough for ingestion. Upload interruption, malformed JSON, invalid envelopes, and database failures roll back the whole job. Database duplication errors are retained as individual failed items in otherwise accepted jobs.

Concurrent upload transactions are distinct. If a commit succeeds but the client loses the response, retrying without a project can create another job. Project reservations prevent accepted source records from being duplicated on resubmission; request-level idempotency is not provided in v1.

## Projects and deduplication

Project names are unique per user, including archived projects. Project imports require at least one nonblank source identifier, with each reserved identifier at most 1,024 UTF-8 bytes to fit Postgres's unique index. Identifiers are exact and case-sensitive; blank identifiers are ignored for reservation.

Every distinct identifier is reserved through the unique `(project_id, source_record)` key. Any overlap makes the whole incoming record a duplicate; no identifiers from that duplicate are reserved. Invalid records reject the entire request and reserve nothing. Reservations survive failed imports, manual retries, successful completion, and project archival. The reservation phase is serialized within each project to avoid deadlocks between uploads with different identifier ordering.

## States and retries

```text
pending_approval → queued → processing → completed
                              ↓
                            failed

processing → queued   safe automatic retry
failed → queued       eligible manual retry
```

`error_context` is nullable JSONB with `error_code` and `description`. New ingestion failures use `DUPLICATE_SOURCE`; dispatch can produce `OUTCOME_UNKNOWN` and remote failure codes. Older jobs may retain `INVALID_RECORD` and `INVALID_SOURCE_RECORD`. The future client can provide additional remote failure codes.

Approval is idempotent, moves only valid pending items, and records actor/time. Explicit selections must belong entirely to the specified job. Batch approval skips failed items. Previously accepted jobs can be approved and dispatched even after project archival.

Retryable import failures and unhandled task errors share Procrastinate’s built-in retry strategy: at most five total task executions, with a five-second delay between retries. Procrastinate owns execution status, the attempt counter, and the schedule. Each item stores only its linked queue job ID; API statuses map `todo` to `queued`, `doing` to `processing`, and `succeeded` to `completed`. Failed or aborted tasks appear as `failed`. Items without a task appear as pending approval or rejected, based on their error context. Infrastructure failures also consume the task counter. Permanent failures and exhausted retries become failed. An approver can enqueue a new task for an eligible failed item, retaining approval and source reservations. Explicit retry selections containing ineligible items return 409 without changing anything; `all=true` skips ineligible items.

Invalid records, duplicates, and unknown outcomes cannot be retried unchanged. Unhandled client exceptions are treated as unknown, never as safe transient errors. Successful completion clears the item's error context. Use `status == completed` to identify success: pending and queued items may also have a null error. No attempt history or result payload is stored.

## Dispatcher and production replicas

FastAPI starts a dispatcher task in each server process during its lifespan. Each task opens a dedicated Postgres connection and competes for the same session advisory lock. Only the winner runs requests; standbys wait. All replicas must use the same database and `BOOKWORM_DISPATCHER_LOCK_KEY`. The dedicated connection must connect directly to Postgres or through session pooling, never transaction pooling.

The elected dispatcher runs a [Procrastinate](https://procrastinate.readthedocs.io/) worker with up to 50 concurrent imports globally. Procrastinate handles queue fetching, notification-based wakeups, scheduled tasks, concurrency, and graceful draining. `BOOKWORM_DISPATCHER_CONCURRENCY` can reduce the limit, but cannot exceed 50. There is no time-based rate limit. Its queue tables and functions live in the `procrastinate` PostgreSQL schema, installed by Alembic. Linked jobs must be retained: the worker keeps jobs by default, and the item foreign key prevents deleting its current task.

Approval and manual retry enqueue tasks in the same transaction as their item updates. A definite retryable remote failure saves the item error and raises an exception for Procrastinate to schedule a retry. Bookworm retains approval, source reservations, the linked task ID, and the latest error. Tasks contain only item IDs; record data stays in Bookworm's tables.

No database transaction stays open during a remote request. The elected server checks its advisory-lock connection every polling interval. On connection loss or FastAPI shutdown, it asks Procrastinate to stop fetching and finish started imports before releasing resources. A database error within an import task receives a bounded infrastructure retry and may replay a remote request whose outcome was not saved. Other imports can continue during an individual task failure.

Shutdown drains running imports gracefully. There is no automatic recovery for jobs left running by a process crash; those jobs require manual intervention. Explicit unknown responses and client exceptions become failed items with `OUTCOME_UNKNOWN`.

FastAPI starts and cancels the dispatcher task through its lifespan. There are no custom stop events or unfinished-attempt reconciliation. The remaining dispatcher loop acquires the advisory lock and monitors its dedicated connection so only one server imports at a time.

To run multiple server processes locally:

```bash
rtk proxy uv run uvicorn bookworm.main:app --workers 2
```

Only one process dispatches; all processes serve API requests. FastAPI shutdown signals the dispatcher to stop, drains started imports, and then disposes the database engine. Compose gives the API 60 seconds to shut down gracefully.

Logs report election, ingestion failures, and Procrastinate task outcomes. Run migrations once before API processes start. For the real client, implement `OpenLibraryClient.import_record` and classify definite rejection versus unknown outcomes conservatively. Normal `/api/import` responses are synchronous and need no job polling.

## Verification

Run `uv run alembic upgrade head` before starting the app. Two baseline migrations install the frozen Procrastinate 3.10.0 schema, then Bookworm's tables. Future schema changes should use new migrations rather than editing these baselines.

The squashed history retains the existing head revision (`d391b724e608`), so databases already at that revision need no changes. Databases on earlier revisions must be upgraded to that head using the old migration files before switching to this history.

Tests create and drop a uniquely named disposable database on the configured Postgres server. The test database account needs permission to create databases. They never truncate the application database. Set `BOOKWORM_TEST_DATABASE_URL` to choose a different test server.

```bash
rtk proxy uv run pytest -q
rtk proxy uv run ruff check .
rtk proxy uv run ruff format --check .
rtk proxy uv run python scripts/smoke.py
```

The suite covers permissions, pagination, project archival, concurrent reservations, schema references, rollback, buffered uploads, atomic database failure rollback, retries, migration round trips, dispatcher election, unknown outcomes, the configured concurrency limit, immediate refill, and graceful drain. The smoke script uses the running Compose stack and verifies upload, validation, deduplication, approval, and completion through the temporary client.

## Code organization

`bookworm.main` assembles the app and its lifecycle. Projects and imports each own their routers, SQLModel tables, request/response schemas, services, and access dependencies. Shared modules provide database sessions, gateway caller parsing, application error mapping, and cursor pagination. API responses use dedicated read schemas rather than table models.

Database settings live in `bookworm.config`; dispatcher settings live in `bookworm.imports.config`. Both use `BOOKWORM_` environment variables. Database-backed routes use synchronous sessions; ingestion runs in a synchronous route on FastAPI's threadpool, and Procrastinate runs each synchronous import task in its thread pool. The dispatcher uses Python’s default thread pool, which may run fewer imports at once than the configured job limit. The import dispatcher, Procrastinate task, and unimplemented Open Library client live in the imports package.

Tests use `httpx.AsyncClient` with `ASGITransport` and the application lifespan, against disposable PostgreSQL databases. Project and import tests are grouped in their respective directories.
