import pytest

from bookworm.config import Settings
from bookworm.dependencies import Caller, get_caller
from bookworm.imports.config import ImportSettings
from bookworm.main import app
from tests.conftest import submit

pytestmark = pytest.mark.anyio


async def test_read_response_fields_and_openapi(client, user, record):
    project = (await client.post("/projects", headers=user, json={"name": "P"})).json()
    assert set(project) == {"id", "user_id", "name", "archived_at", "created_at", "updated_at"}
    job_id = await submit(client, user, [record, record], project["id"])
    page = (await client.get(f"/imports/{job_id}", headers=user)).json()
    assert set(page["job"]) == {"id", "user_id", "project_id", "created_at"}
    assert set(page["items"][0]) == {
        "id",
        "job_id",
        "position",
        "data",
        "status",
        "error_context",
        "approved_by",
        "approved_at",
        "created_at",
        "updated_at",
    }
    assert page["items"][1]["data"] == record
    assert set(page["items"][1]["error_context"]) == {"error_code", "description"}
    schema = (await client.get("/openapi.json")).json()
    for path in ("/projects", "/imports", "/imports/{job_id}"):
        operation = schema["paths"][path]["get"]
        assert operation["tags"] and operation["summary"]
        assert {"cursor", "size"} <= {p["name"] for p in operation["parameters"]}
    components = schema["components"]["schemas"]
    assert {
        "ProjectRead",
        "JobRead",
        "ImportItemRead",
        "ErrorContext",
        "UpdatedCount",
    } <= components.keys()
    for code in ("404", "422", "503"):
        assert code in schema["paths"]["/imports"]["post"]["responses"]
    response = await client.delete(f"/projects/{project['id']}", headers=user)
    assert response.status_code == 204 and response.content == b""


async def test_approver_dependency_is_reused(client, user, record):
    job_id = await submit(client, user, [record])
    calls = 0

    async def reviewer():
        nonlocal calls
        calls += 1
        return Caller("reviewer", True)

    app.dependency_overrides[get_caller] = reviewer
    try:
        response = await client.post(f"/imports/{job_id}/approve", json={"all": True})
        assert response.status_code == 200 and response.json() == {"updated": 1}
        assert calls == 1
    finally:
        app.dependency_overrides.pop(get_caller)
    assert (
        await client.post(f"/imports/{job_id}/approve", headers=user, json={"all": True})
    ).status_code == 403


def test_domain_settings_accept_shared_environment_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOOKWORM_DATABASE_URL=postgresql+psycopg://user:password@localhost/test\n"
        "BOOKWORM_DISPATCHER_CONCURRENCY=7\n"
        "BOOKWORM_DISPATCHER_LOCK_KEY=100\n"
        "BOOKWORM_POLL_INTERVAL=0.5\n"
        "UNRELATED_SETTING=value\n"
    )
    settings = Settings(_env_file=env_file)
    imports = ImportSettings(_env_file=env_file)
    # The disposable test database URL is injected into the environment and takes
    # precedence over the file, just as Compose's environment does in production.
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert imports.dispatcher_concurrency == 7
    assert imports.dispatcher_lock_key == 100
    assert imports.poll_interval == 0.5
