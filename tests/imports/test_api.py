import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func
from sqlmodel import Session, select

from bookworm.imports.models import ImportItem, Job, SourceReservation
from tests.conftest import submit


async def test_pagination_access_and_approval(client, user, approver, record):
    job = await submit(client, user, [record] * 4)
    bob = {"X-User-Id": "bob"}
    assert (await client.get(f"/imports/{job}", headers=bob)).status_code == 404
    assert (await client.get("/imports", headers=bob)).json()["items"] == []
    assert len((await client.get("/imports", headers=approver)).json()["items"]) == 1
    first = (await client.get(f"/imports/{job}?size=2", headers=approver)).json()
    assert first["counts"]["pending_approval"] == 4
    assert first["counts"]["failed"] == 0
    assert [item["position"] for item in first["items"]] == [0, 1]
    second = (
        await client.get(f"/imports/{job}?size=2&cursor={first['next_page']}", headers=user)
    ).json()
    assert [item["position"] for item in second["items"]] == [2, 3]
    assert second["next_page"] is None
    assert (
        len(
            (await client.get(f"/imports/{job}?status=pending_approval", headers=user)).json()[
                "items"
            ]
        )
        == 4
    )
    assert (
        await client.post(f"/imports/{job}/approve", headers=user, json={"all": True})
    ).status_code == 403
    assert (
        await client.post(f"/imports/{job}/approve", headers=approver, json={"all": True})
    ).json()["updated"] == 4
    assert (
        await client.post(f"/imports/{job}/approve", headers=approver, json={"all": True})
    ).json()["updated"] == 0


async def test_source_overlap_is_atomic(client, user, record, database):
    project = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    job = await submit(
        client,
        user,
        [
            {**record, "source_records": ["a", "b", "a"]},
            {**record, "source_records": ["b", "c"]},
            {**record, "source_records": ["c"]},
        ],
        project,
    )
    items = (await client.get(f"/imports/{job}", headers=user)).json()["items"]
    assert [item["status"] for item in items] == [
        "pending_approval",
        "failed",
        "pending_approval",
    ]
    assert items[1]["error_context"]["error_code"] == "DUPLICATE_SOURCE"
    with Session(database) as session:
        assert session.exec(select(func.count()).select_from(SourceReservation)).one() == 3
    other = await submit(client, user, [{**record, "source_records": ["c"]}], project)
    assert (await client.get(f"/imports/{other}", headers=user)).json()["items"][0][
        "status"
    ] == "failed"


async def test_concurrent_source_reservations(client, user, record):
    project = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    jobs = await asyncio.gather(*(submit(client, user, [record], project) for _ in range(2)))
    states = [
        (await client.get(f"/imports/{job}", headers=user)).json()["items"][0]["status"]
        for job in jobs
    ]
    assert sorted(states) == ["failed", "pending_approval"]


async def test_concurrent_reversed_source_order(client, user, record):
    project = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    batches = [
        [{**record, "source_records": [source]} for source in order]
        for order in [("a", "b"), ("b", "a")]
    ]
    jobs = await asyncio.gather(*(submit(client, user, batch, project) for batch in batches))
    counts = [(await client.get(f"/imports/{job}", headers=user)).json()["counts"] for job in jobs]
    assert sorted(count["pending_approval"] for count in counts) == [0, 2]


async def test_project_scope_and_no_project_repeats(client, user, record):
    project = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    bob = {"X-User-Id": "bob"}
    assert (
        await client.post("/imports", headers=bob, json={"project_id": project, "data": [record]})
    ).status_code == 404
    for _ in range(2):
        job = await submit(client, user, [record, record])
        assert (await client.get(f"/imports/{job}", headers=user)).json()["counts"][
            "pending_approval"
        ] == 2


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"{}",
        b'{"data": []}',
        b'{"data": {}}',
        b'{"data": [], "extra": 1}',
        b'{"data": [], "data": []}',
        b'{"data": [',
        b'{"project_id": 12, "data": []}',
        b'{"project_id": "bad", "data": []}',
    ],
)
async def test_bad_envelope_rolls_back(client, user, database, body):
    response = await client.post(
        "/imports", headers={**user, "Content-Type": "application/json"}, content=body
    )
    assert response.status_code == 422, response.text
    with Session(database) as session:
        assert session.exec(select(func.count()).select_from(Job)).one() == 0
        assert session.exec(select(func.count()).select_from(ImportItem)).one() == 0


async def test_both_envelope_orders(client, user, record):
    project = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    for body in [
        {"data": [record], "project_id": project},
        {"project_id": project, "data": [record]},
    ]:
        assert (await client.post("/imports", headers=user, json=body)).status_code == 202


async def test_selection_validation_and_atomicity(client, user, approver, record):
    job = await submit(client, user, [record])
    item = (await client.get(f"/imports/{job}", headers=user)).json()["items"][0]["id"]
    assert (
        await client.post(
            f"/imports/{job}/approve", headers=approver, json={"item_ids": [item, str(uuid4())]}
        )
    ).status_code == 422
    assert (await client.get(f"/imports/{job}", headers=user)).json()["counts"][
        "pending_approval"
    ] == 1
    for selection in [
        {},
        {"all": True, "item_ids": [item]},
        {"item_ids": []},
        {"item_ids": [item, item]},
    ]:
        assert (
            await client.post(f"/imports/{job}/approve", headers=approver, json=selection)
        ).status_code == 422
    assert (
        await client.post(f"/imports/{job}/approve", headers=approver, json={"item_ids": [item]})
    ).json()["updated"] == 1


async def test_list_cursors_and_headers(client, user, record):
    for i in range(3):
        await client.post("/projects", headers=user, json={"name": str(i)})
        await submit(client, user, [record])
    for path in ["/projects", "/imports"]:
        first = (await client.get(path + "?size=2", headers=user)).json()
        second = (
            await client.get(path, params={"size": 2, "cursor": first["next_page"]}, headers=user)
        ).json()
        assert len(first["items"]) == 2 and len(second["items"]) == 1
        assert not set(row["id"] for row in first["items"]) & set(
            row["id"] for row in second["items"]
        )
        assert (await client.get(path + "?cursor=broken", headers=user)).status_code == 400
    assert (await client.get("/imports")).status_code == 422
    assert (await client.get("/imports", headers={"X-User-Id": " "})).status_code == 422
    assert (
        await client.get("/imports", headers={**user, "X-Can-Approve": "bad"})
    ).status_code == 422
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 200


async def test_library_cursor_navigation_and_size_validation(client, user, record):
    job = await submit(client, user, [record] * 5)
    path = f"/imports/{job}"
    first = (await client.get(path, params={"size": 2}, headers=user)).json()
    second = (
        await client.get(path, params={"size": 2, "cursor": first["next_page"]}, headers=user)
    ).json()
    back = (
        await client.get(path, params={"size": 2, "cursor": second["previous_page"]}, headers=user)
    ).json()
    last = (
        await client.get(path, params={"size": 2, "cursor": second["next_page"]}, headers=user)
    ).json()
    assert [row["position"] for row in first["items"]] == [0, 1]
    assert [row["position"] for row in second["items"]] == [2, 3]
    assert back["items"] == first["items"]
    assert [row["position"] for row in last["items"]] == [4]
    assert last["next_page"] is None
    assert first["total"] == 5
    assert "next_cursor" not in first
    for endpoint in ["/projects", "/imports", path]:
        for size in [0, 1001]:
            assert (
                await client.get(endpoint, params={"size": size}, headers=user)
            ).status_code == 422
        assert (
            await client.get(endpoint, params={"cursor": "eyJ4IjoxfQ=="}, headers=user)
        ).status_code == 400


async def test_filtered_pagination_retains_job_counts(client, user, record):
    project = (await client.post("/projects", headers=user, json={"name": "P"})).json()["id"]
    job = await submit(
        client, user, [record, record, record, {**record, "source_records": ["other"]}], project
    )
    path = f"/imports/{job}"
    first = (await client.get(path, params={"size": 1, "status": "failed"}, headers=user)).json()
    second = (
        await client.get(
            path, params={"size": 1, "status": "failed", "cursor": first["next_page"]}, headers=user
        )
    ).json()
    assert [first["items"][0]["position"], second["items"][0]["position"]] == [1, 2]
    assert first["total"] == second["total"] == 4
    assert first["counts"]["failed"] == 2
    assert second["next_page"] is None
    assert (await client.get("/projects", headers=user)).json()["total"] == 1


pytestmark = pytest.mark.anyio
