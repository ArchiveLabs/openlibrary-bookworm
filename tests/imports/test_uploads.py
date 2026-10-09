import json
from uuid import uuid4

import pytest
from sqlalchemy import event, func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from bookworm.imports.models import ImportItem, Job, SourceReservation
from bookworm.imports.schemas import ImportEnvelope
from bookworm.imports.service import prepare_items
from tests.conftest import submit


def test_prepare_items_preserves_inputs_and_duplicate_order(record):
    job = Job(user_id="alice", project_id=uuid4())
    existing = {"existing"}
    records = [
        {**record, "source_records": ["existing", "available"]},
        {**record, "source_records": ["available", "available"]},
        {**record, "source_records": ["available", "another"]},
        {**record, "source_records": ["another"]},
    ]
    original = json.dumps(records)

    items, reservations = prepare_items(job, records, existing)

    assert existing == {"existing"}
    assert json.dumps(records) == original
    assert [item.error_context is not None for item in items] == [True, False, True, False]
    assert {(r.source_record, r.item_id) for r in reservations} == {
        ("available", items[1].id),
        ("another", items[3].id),
    }


async def test_upload_creates_all_items_in_order(client, user, record, database):
    job_id = await submit(client, user, [{**record, "title": str(i)} for i in range(1000)])
    with Session(database) as session:
        items = session.exec(
            select(ImportItem).where(ImportItem.job_id == job_id).order_by(ImportItem.position)
        ).all()
        assert len(items) == 1000
        assert [item.data["title"] for item in items] == [str(i) for i in range(1000)]


async def test_project_reservations_use_one_lookup(client, user, record, database):
    count = 1000
    project_id = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    await submit(client, user, [{**record, "source_records": ["source:0"]}], project_id)
    queries = []

    def capture_queries(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(database, "before_cursor_execute", capture_queries)
    try:
        records = [{**record, "source_records": [f"source:{i}"]} for i in range(count)]
        job_id = await submit(client, user, records, project_id)
    finally:
        event.remove(database, "before_cursor_execute", capture_queries)
    lookups = [
        sql
        for sql in queries
        if sql.lstrip().startswith("SELECT") and "FROM source_reservations" in sql
    ]
    assert len(lookups) == 1
    with Session(database) as session:
        items = session.exec(
            select(ImportItem).where(ImportItem.job_id == job_id).order_by(ImportItem.position)
        ).all()
        assert len(items) == count
        assert items[0].error_context["error_code"] == "DUPLICATE_SOURCE"
        assert all(item.approved_at is None and item.error_context is None for item in items[1:])
        assert session.exec(select(func.count()).select_from(SourceReservation)).one() == count


async def test_database_failure_rolls_back_entire_upload(client, user, record, database):
    project_id = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]

    def fail_reservation_insert(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO source_reservations"):
            raise SQLAlchemyError("Reservation insert failure")

    event.listen(database, "before_cursor_execute", fail_reservation_insert)
    try:
        response = await client.post(
            "/imports", headers=user, json={"project_id": project_id, "data": [record, record]}
        )
    finally:
        event.remove(database, "before_cursor_execute", fail_reservation_insert)
    assert response.status_code == 503
    with Session(database) as session:
        for model in (Job, ImportItem, SourceReservation):
            assert session.exec(select(func.count()).select_from(model)).one() == 0


async def test_commit_failure_returns_503_and_rolls_back(client, user, record, database):
    def fail_commit(session):
        raise SQLAlchemyError("Commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = await client.post("/imports", headers=user, json={"data": [record]})
    finally:
        event.remove(Session, "before_commit", fail_commit)

    assert response.status_code == 503
    with Session(database) as session:
        for model in (Job, ImportItem, SourceReservation):
            assert session.exec(select(func.count()).select_from(model)).one() == 0


@pytest.mark.parametrize("invalid", [None, 123, {}, {"unknown": "field"}])
async def test_invalid_record_rejects_whole_request(
    client, user, record, invalid, monkeypatch, database
):
    def unexpected_ingestion(*args, **kwargs):
        pytest.fail("Invalid requests must not reach ingestion")

    monkeypatch.setattr("bookworm.imports.service.create_job", unexpected_ingestion)
    response = await client.post("/imports", headers=user, json={"data": [record, invalid]})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "data", 1]
    with Session(database) as session:
        for model in (Job, ImportItem, SourceReservation):
            assert session.exec(select(func.count()).select_from(model)).one() == 0


@pytest.mark.parametrize("sources", [[], ["", "  "], ["é" * 513]])
async def test_invalid_project_sources_reject_whole_request(
    client, user, record, sources, database
):
    project_id = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    response = await client.post(
        "/imports",
        headers=user,
        json={"project_id": project_id, "data": [record, {**record, "source_records": sources}]},
    )
    assert response.status_code == 422
    assert "data.1.source_records" in response.json()["detail"][0]["msg"]
    with Session(database) as session:
        for model in (Job, ImportItem, SourceReservation):
            assert session.exec(select(func.count()).select_from(model)).one() == 0


async def test_source_identifier_boundaries(client, user, record):
    project_id = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    sources = ["é" * 512, "  "]
    job_id = await submit(client, user, [{**record, "source_records": sources}], project_id)
    assert (await client.get(f"/imports/{job_id}", headers=user)).json()["counts"][
        "pending_approval"
    ] == 1
    # Without a project, source identifiers are not reserved and can be empty.
    await submit(client, user, [{**record, "source_records": []}])


@pytest.mark.parametrize(
    "field,value",
    [
        ("number_of_pages", "123"),
        ("authors", [{"name": "A", "extra": True}]),
        ("languages", ["english"]),
        ("publish_country", "USA"),
        ("isbn_10", ["not-isbn"]),
        ("isbn_13", ["123"]),
        ("links", [{"title": "Missing URL"}]),
    ],
)
async def test_referenced_schema_constraints(client, user, record, field, value, database):
    response = await client.post(
        "/imports", headers=user, json={"data": [record, {**record, field: value}]}
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "data", 1]
    with Session(database) as session:
        for model in (Job, ImportItem, SourceReservation):
            assert session.exec(select(func.count()).select_from(model)).one() == 0


async def test_optional_schema_fields(record):
    extended = {
        **record,
        "number_of_pages": 123,
        "languages": ["eng"],
        "publish_country": "us",
        "isbn_10": ["0-306-40615-2"],
        "isbn_13": ["9780306406157"],
        "links": [{"title": "Source", "url": "https://example.com"}],
        "identifiers": {"gutenberg": ["123"]},
        "contributor": [{"name": "Editor", "role": "Editor"}],
    }
    assert ImportEnvelope(data=[extended]).data == [extended]


async def test_migrations_match_models_and_round_trip(database):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    command.check(config)
    command.downgrade(config, "b014c2a8d790")
    with database.connect() as connection:
        assert (
            connection.execute(text("SELECT to_regclass('public.import_items')")).scalar_one()
            is None
        )
        assert (
            connection.execute(
                text("SELECT to_regclass('procrastinate.procrastinate_jobs')")
            ).scalar_one()
            is not None
        )
    command.downgrade(config, "base")
    with database.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM pg_namespace WHERE nspname = 'procrastinate'")
            ).scalar_one()
            == 0
        )
    command.upgrade(config, "head")
    command.check(config)


pytestmark = pytest.mark.anyio
