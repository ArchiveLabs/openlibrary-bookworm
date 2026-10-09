import asyncio
import threading
from datetime import timedelta
from uuid import UUID

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from bookworm.imports import dispatcher, service
from bookworm.imports.client import ImportResult, OpenLibraryClient
from bookworm.imports.config import ImportSettings, get_import_settings
from bookworm.imports.models import QUEUE_JOBS, ImportItem, ItemStatus
from bookworm.imports.schemas import ItemSelection
from bookworm.imports.tasks import create_queue
from bookworm.main import app
from bookworm.utils import utcnow
from tests.conftest import submit

pytestmark = pytest.mark.anyio


def item_status(session, item):
    return session.exec(
        select(service.item_status())
        .select_from(ImportItem)
        .outerjoin(QUEUE_JOBS, ImportItem.procrastinate_job_id == QUEUE_JOBS.c.id)
        .where(ImportItem.id == item.id)
    ).one()


@pytest.fixture
async def queue(database):
    url = database.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    queue = create_queue(url)
    async with queue.open_async():
        yield queue


async def drain(queue, concurrency=50):
    async with asyncio.timeout(10):
        await queue.run_worker_async(
            queues=["imports"],
            wait=False,
            concurrency=concurrency,
            install_signal_handlers=False,
        )


async def approved_job(client, user, approver, record, count=1):
    job = await submit(client, user, [record] * count)
    assert (
        await client.post(f"/imports/{job}/approve", headers=approver, json={"all": True})
    ).status_code == 200
    return job


async def test_approval_enqueues_once_and_mock_completes(
    client, user, approver, record, database, queue
):
    job = await approved_job(client, user, approver, record)
    assert (
        await client.post(f"/imports/{job}/approve", headers=approver, json={"all": True})
    ).json()["updated"] == 0
    with Session(database) as session:
        assert (
            session.connection()
            .execute(text("SELECT count(*) FROM procrastinate.procrastinate_jobs"))
            .scalar_one()
            == 1
        )
    await drain(queue)
    item = (await client.get(f"/imports/{job}", headers=user)).json()["items"][0]
    assert item["status"] == "completed"
    assert item["error_context"] is None


async def test_retry_schedule_exhaustion_and_manual_allowance(
    client, user, approver, record, database, queue, monkeypatch
):
    job = await approved_job(client, user, approver, record)

    def temporary(self, record):
        return ImportResult(
            success=False, retryable=True, error_code="TEMPORARY", description="Try later"
        )

    monkeypatch.setattr(OpenLibraryClient, "import_record", temporary)
    for number, delay in enumerate([5, 5, 5, 5, None]):
        before = utcnow()
        await drain(queue)
        with Session(database) as session:
            item = session.exec(select(ImportItem)).one()
            task = (
                session.connection()
                .execute(
                    text(
                        "SELECT id, status, attempts, scheduled_at FROM procrastinate.procrastinate_jobs WHERE task_name = 'imports:import_item'"
                    )
                )
                .one()
            )
            assert task.attempts == number + 1
            assert item.error_context["error_code"] == "TEMPORARY"
            if delay is not None:
                assert item_status(session, item) == ItemStatus.queued
                assert task.status == "todo"
                assert task.scheduled_at >= before + timedelta(seconds=delay)
                session.connection().execute(text("SET LOCAL search_path TO procrastinate, public"))
                session.connection().execute(
                    text(
                        "UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now() WHERE status = 'todo'"
                    )
                )
                session.commit()
            else:
                assert item_status(session, item) == ItemStatus.failed
                assert task.status == "failed"
    assert (
        await client.post(f"/imports/{job}/retry", headers=user, json={"all": True})
    ).status_code == 403
    assert (
        await client.post(f"/imports/{job}/retry", headers=approver, json={"all": True})
    ).json()["updated"] == 1
    await drain(queue)
    with Session(database) as session:
        assert item_status(session, session.exec(select(ImportItem)).one()) == ItemStatus.queued
        assert (
            session.connection()
            .execute(
                text("SELECT attempts FROM procrastinate.procrastinate_jobs WHERE status = 'todo'")
            )
            .scalar_one()
            == 1
        )


async def test_queue_failure_is_reported_and_can_be_manually_retried(
    client, user, approver, record, database, queue, monkeypatch
):
    job = await approved_job(client, user, approver, record)
    load = service.get_import_data

    def unavailable(*args):
        raise SQLAlchemyError("Cannot load import")

    monkeypatch.setattr(service, "get_import_data", unavailable)
    for _ in range(5):
        await drain(queue)
        with Session(database) as session:
            session.connection().execute(text("SET LOCAL search_path TO procrastinate, public"))
            session.connection().execute(
                text(
                    "UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now() WHERE status = 'todo'"
                )
            )
            session.commit()
    page = (await client.get(f"/imports/{job}", headers=user)).json()
    assert page["counts"]["failed"] == 1
    assert page["items"][0]["status"] == "failed"
    assert page["items"][0]["error_context"] is None
    monkeypatch.setattr(service, "get_import_data", load)
    assert (
        await client.post(f"/imports/{job}/retry", headers=approver, json={"all": True})
    ).json()["updated"] == 1
    await drain(queue)
    assert (await client.get(f"/imports/{job}", headers=user)).json()["items"][0][
        "status"
    ] == "completed"


@pytest.mark.parametrize("mode", ["permanent", "unknown", "exception"])
async def test_non_retryable_results(
    client, user, approver, record, database, queue, monkeypatch, mode
):
    job = await approved_job(client, user, approver, record)

    def reject(self, record):
        if mode == "exception":
            raise TimeoutError("Remote might have written the record")
        return ImportResult(
            success=False,
            error_code="PERMANENT",
            unknown=mode == "unknown",
            retryable=mode == "unknown",
        )

    monkeypatch.setattr(OpenLibraryClient, "import_record", reject)
    await drain(queue)
    item = (await client.get(f"/imports/{job}", headers=user)).json()["items"][0]
    assert item["status"] == "failed"
    assert item["error_context"]["error_code"] == (
        "PERMANENT" if mode == "permanent" else "OUTCOME_UNKNOWN"
    )
    with Session(database) as session:
        assert (
            session.connection()
            .execute(
                text("SELECT count(*) FROM procrastinate.procrastinate_jobs WHERE status = 'todo'")
            )
            .scalar_one()
            == 0
        )
    if mode != "permanent":
        assert (
            await client.post(
                f"/imports/{job}/retry", headers=approver, json={"item_ids": [item["id"]]}
            )
        ).status_code == 409


async def test_completed_import_cannot_be_retried(client, user, approver, record, queue):
    job = await approved_job(client, user, approver, record)
    await drain(queue)
    item = (await client.get(f"/imports/{job}", headers=user)).json()["items"][0]
    assert item["status"] == "completed"
    assert (
        await client.post(
            f"/imports/{job}/retry", headers=approver, json={"item_ids": [item["id"]]}
        )
    ).status_code == 409
    await drain(queue)
    assert (await client.get(f"/imports/{job}", headers=user)).json()["items"][0][
        "status"
    ] == "completed"


async def test_old_queue_job_cannot_overwrite_current_error(
    client, user, approver, record, database
):
    await approved_job(client, user, approver, record)
    with Session(database) as session:
        item = session.exec(select(ImportItem)).one()
        item_id, old_queue_id = item.id, item.procrastinate_job_id
        service.enqueue_items(session, [item_id])
        session.commit()
        session.refresh(item)
        new_queue_id = item.procrastinate_job_id
    assert service.get_import_data(item_id, old_queue_id) is None
    assert service.get_import_data(item_id, new_queue_id) == record
    with pytest.raises(RuntimeError, match="Import failed"):
        service.finish_import(
            item_id,
            new_queue_id,
            ImportResult(success=False, retryable=True, error_code="TEMPORARY"),
        )
    service.finish_import(item_id, old_queue_id, ImportResult(success=True))
    with Session(database) as session:
        assert session.get(ImportItem, item_id).error_context["error_code"] == "TEMPORARY"


async def test_queue_insert_and_approval_roll_back_together(
    client, user, record, database, monkeypatch
):
    job = await submit(client, user, [record])
    with Session(database) as session:
        model = service.accessible_job(session, UUID(job), "reviewer", can_approve=True)

        def fail_commit():
            assert (
                session.connection()
                .execute(text("SELECT count(*) FROM procrastinate.procrastinate_jobs"))
                .scalar_one()
                == 1
            )
            raise SQLAlchemyError("Commit failed")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(SQLAlchemyError, match="Commit failed"):
            service.approve(model, ItemSelection(all=True), session, "reviewer")
        session.rollback()
        assert (
            session.connection()
            .execute(text("SELECT count(*) FROM procrastinate.procrastinate_jobs"))
            .scalar_one()
            == 0
        )
        assert (
            item_status(session, session.exec(select(ImportItem)).one())
            == ItemStatus.pending_approval
        )


async def test_persistence_failure_retry_can_replay_import(
    client, user, approver, record, database, queue, monkeypatch
):
    await approved_job(client, user, approver, record)
    calls = 0
    save = service.finish_import

    def import_record(self, record):
        nonlocal calls
        calls += 1
        return ImportResult(success=True)

    def fail_save(*args, **kwargs):
        raise SQLAlchemyError("Cannot save remote outcome")

    monkeypatch.setattr(OpenLibraryClient, "import_record", import_record)
    monkeypatch.setattr(service, "finish_import", fail_save)
    await drain(queue)
    with Session(database) as session:
        assert item_status(session, session.exec(select(ImportItem)).one()) == ItemStatus.queued
        session.connection().execute(text("SET LOCAL search_path TO procrastinate, public"))
        session.connection().execute(
            text(
                "UPDATE procrastinate.procrastinate_jobs SET scheduled_at = now() WHERE status = 'todo'"
            )
        )
        session.commit()
    monkeypatch.setattr(service, "finish_import", save)
    await drain(queue)
    with Session(database) as session:
        item = session.exec(select(ImportItem)).one()
        assert item_status(session, item) == ItemStatus.completed
        assert item.error_context is None
    assert calls == 2


async def test_concurrency_limit_immediate_refill_and_graceful_drain(
    client, user, approver, record, queue, monkeypatch
):
    await approved_job(client, user, approver, record, 3)
    slots_started = asyncio.Event()
    refill_started = asyncio.Event()
    release_first = threading.Event()
    release_rest = threading.Event()
    started = active = peak = 0
    lock = threading.Lock()
    loop = asyncio.get_running_loop()

    def import_record(self, record):
        nonlocal started, active, peak
        with lock:
            started += 1
            active += 1
            peak = max(peak, active)
            number = started
        if number == 2:
            loop.call_soon_threadsafe(slots_started.set)
        if number == 3:
            loop.call_soon_threadsafe(refill_started.set)
        assert (release_first if number == 1 else release_rest).wait(10)
        with lock:
            active -= 1
        return ImportResult(success=True)

    monkeypatch.setattr(OpenLibraryClient, "import_record", import_record)
    task = asyncio.create_task(queue.run_worker_async(concurrency=2, install_signal_handlers=False))
    try:
        await asyncio.wait_for(slots_started.wait(), 10)
        assert started == 2
        release_first.set()
        await asyncio.wait_for(refill_started.wait(), 10)
        assert peak == 2
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
        release_rest.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        assert active == 0
    finally:
        release_first.set()
        release_rest.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_global_lock_election_and_takeover(database):
    url = database.url.render_as_string(hide_password=False).replace(
        "postgresql+psycopg://", "postgresql://"
    )
    key = get_import_settings().dispatcher_lock_key
    first = psycopg.connect(url, autocommit=True)
    second = psycopg.connect(url, autocommit=True)
    try:
        assert first.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
        assert not second.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
        first.close()
        # Postgres may observe the socket close after this client resumes.
        async with asyncio.timeout(2):
            while not second.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]:
                await asyncio.sleep(0.01)
    finally:
        first.close()
        second.close()


async def test_migration_enqueues_preexisting_approved_items(
    client, user, approver, record, database, queue
):
    from alembic import command
    from alembic.config import Config

    await approved_job(client, user, approver, record)
    await submit(client, user, [record])  # Unapproved records stay outside the queue.
    config = Config("alembic.ini")
    command.downgrade(config, "9bde1fb40de7")
    command.upgrade(config, "head")
    with Session(database) as session:
        assert (
            session.connection()
            .execute(text("SELECT count(*) FROM procrastinate.procrastinate_jobs"))
            .scalar_one()
            == 1
        )
    await drain(queue)
    with Session(database) as session:
        assert {item_status(session, item) for item in session.exec(select(ImportItem))} == {
            ItemStatus.completed,
            ItemStatus.pending_approval,
        }


async def test_status_migration_preserves_existing_outcomes(
    client, user, approver, record, database
):
    from alembic import command
    from alembic.config import Config

    job = await approved_job(client, user, approver, record, 3)
    config = Config("alembic.ini")
    command.downgrade(config, "c728ea61f205")
    with database.begin() as connection:
        connection.execute(text("SET LOCAL search_path TO procrastinate, public"))
        connection.execute(
            text("""
            UPDATE import_items SET status = CASE position WHEN 0 THEN 'completed'
                WHEN 1 THEN 'failed' ELSE 'processing' END,
                error_context = CASE WHEN position = 1
                    THEN jsonb_build_object('error_code', 'PERMANENT', 'description', 'Rejected')
                    ELSE 'null'::jsonb END
        """)
        )
        connection.execute(
            text("""
            UPDATE procrastinate.procrastinate_jobs SET status = 'succeeded'
            WHERE args->>'item_id' IN (SELECT id::text FROM import_items WHERE position = 1)
        """)
        )
        connection.execute(
            text("""
            DELETE FROM procrastinate.procrastinate_jobs
            WHERE args->>'item_id' IN (SELECT id::text FROM import_items WHERE position = 0)
        """)
        )
    command.upgrade(config, "head")
    page = (await client.get(f"/imports/{job}", headers=user)).json()
    assert [item["status"] for item in page["items"]] == ["completed", "failed", "queued"]
    assert page["items"][1]["error_context"]["error_code"] == "PERMANENT"
    with Session(database) as session:
        assert all(
            item.procrastinate_job_id is not None for item in session.exec(select(ImportItem))
        )


async def test_fastapi_dispatches_and_drains_on_shutdown(
    database, user, approver, record, monkeypatch
):
    started = asyncio.Event()
    shutdown = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    calls = 0
    job_id = None
    monkeypatch.setattr(
        dispatcher, "get_import_settings", lambda: ImportSettings(poll_interval=0.01)
    )

    def import_record(self, record):
        nonlocal calls
        calls += 1
        loop.call_soon_threadsafe(started.set)
        assert release.wait(10)
        return ImportResult(success=True)

    monkeypatch.setattr(OpenLibraryClient, "import_record", import_record)

    async def serve():
        nonlocal job_id
        # Two application instances compete for the same advisory lock.
        async with app.router.lifespan_context(app), app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                job_id = await approved_job(client, user, approver, record)
                await shutdown.wait()

    task = asyncio.create_task(serve())
    try:
        await asyncio.wait_for(started.wait(), 5)
        with Session(database) as session:
            assert (
                session.connection()
                .execute(text("SELECT count(*) FROM procrastinate.procrastinate_workers"))
                .scalar_one()
                == 1
            )
        shutdown.set()
        await asyncio.sleep(0.05)
        assert not task.done()
        assert calls == 1
        url = database.url.render_as_string(hide_password=False).replace(
            "postgresql+psycopg://", "postgresql://"
        )
        with psycopg.connect(url, autocommit=True) as connection:
            key = get_import_settings().dispatcher_lock_key
            assert not connection.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
            release.set()
            await asyncio.wait_for(task, 5)
            assert connection.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[0]
        with Session(database) as session:
            item = session.exec(select(ImportItem).where(ImportItem.job_id == job_id)).one()
            assert item_status(session, item) == ItemStatus.completed
            assert item.error_context is None

    finally:
        shutdown.set()
        release.set()
        await task
