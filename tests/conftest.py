import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from bookworm.config import get_settings
from bookworm.database import get_engine
from bookworm.imports.config import get_import_settings
from bookworm.main import app


@pytest.fixture(scope="session")
def database():
    # Always create a disposable database; never truncate the configured application DB.
    base_url = os.environ.get("BOOKWORM_TEST_DATABASE_URL", get_settings().database_url)
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    name = "bookworm_test_" + uuid4().hex
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    previous = os.environ.get("BOOKWORM_DATABASE_URL")
    os.environ["BOOKWORM_DATABASE_URL"] = admin.url.set(database=name).render_as_string(
        hide_password=False
    )
    get_settings.cache_clear()
    get_import_settings.cache_clear()
    get_engine.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = get_engine()
    yield engine
    engine.dispose()
    get_engine.cache_clear()
    if previous is None:
        os.environ.pop("BOOKWORM_DATABASE_URL", None)
    else:
        os.environ["BOOKWORM_DATABASE_URL"] = previous
    get_settings.cache_clear()
    get_import_settings.cache_clear()
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(autouse=True)
def clean_database(database):
    with database.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE projects, jobs, import_items, source_reservations, "
                "procrastinate.procrastinate_jobs, procrastinate.procrastinate_workers, "
                "procrastinate.procrastinate_periodic_defers CASCADE"
            )
        )


@pytest.fixture
async def client(database, monkeypatch):
    # Endpoint tests control dispatch explicitly; lifespan behavior is tested separately.
    async def idle_dispatcher():
        import asyncio

        await asyncio.Future()

    monkeypatch.setattr("bookworm.main.run_dispatcher", idle_dispatcher)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


@pytest.fixture(autouse=True)
def import_client(monkeypatch):
    from bookworm.imports.client import ImportResult, OpenLibraryClient

    def succeed(self, record):
        return ImportResult(success=True)

    monkeypatch.setattr(OpenLibraryClient, "import_record", succeed)


@pytest.fixture
def record():
    return {
        "title": "A book",
        "source_records": ["vendor:1"],
        "authors": [{"name": "An Author"}],
        "publishers": ["A Publisher"],
        "publish_date": "2020",
    }


@pytest.fixture
def user():
    return {"X-User-Id": "alice"}


@pytest.fixture
def approver():
    return {"X-User-Id": "reviewer", "X-Can-Approve": "true"}


async def submit(client, user, records, project_id=None):
    body = {"data": records}
    if project_id is not None:
        body["project_id"] = project_id
    response = await client.post("/imports", headers=user, json=body)
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
