import pytest

from tests.conftest import submit

pytestmark = pytest.mark.anyio


async def test_projects_ownership_names_and_archive(client, user, approver, record):
    first = await client.post("/projects", headers=user, json={"name": " Reading "})
    assert first.status_code == 201
    project = first.json()
    assert project["name"] == "Reading"
    assert (
        await client.post("/projects", headers=user, json={"name": "Reading"})
    ).status_code == 409
    bob = {"X-User-Id": "bob"}
    assert (
        await client.post("/projects", headers=bob, json={"name": "Reading"})
    ).status_code == 201
    assert (await client.get(f"/projects/{project['id']}", headers=bob)).status_code == 404
    assert (
        await client.patch(f"/projects/{project['id']}", headers=approver, json={"name": "Other"})
    ).status_code == 404
    assert (
        await client.patch(f"/projects/{project['id']}", headers=user, json={"name": "Renamed"})
    ).status_code == 200
    job = await submit(client, user, [record], project["id"])
    assert (await client.delete(f"/projects/{project['id']}", headers=user)).status_code == 204
    assert (await client.delete(f"/projects/{project['id']}", headers=user)).status_code == 204
    assert (await client.get("/projects", headers=user)).json()["items"] == []
    assert (
        len((await client.get("/projects?include_archived=true", headers=user)).json()["items"])
        == 1
    )
    assert (
        await client.post(
            "/imports", headers=user, json={"project_id": project["id"], "data": [record]}
        )
    ).status_code == 404
    assert (
        await client.post(f"/imports/{job}/approve", headers=approver, json={"all": True})
    ).json()["updated"] == 1
    assert (
        await client.post("/projects", headers=user, json={"name": "Renamed"})
    ).status_code == 409
