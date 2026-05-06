from tests.conftest import auth_headers


def _make_batch(client):
    return client.post("/v1/batches", json={"name": "b"}, headers=auth_headers()).json()["id"]


def _add_items(client, batch_id, n=3):
    items = [{"source_id": f"bwb:{i}", "data": {"title": f"Book {i}"}} for i in range(n)]
    client.post(f"/v1/batches/{batch_id}/items", json=items, headers=auth_headers())


def test_get_pending_requires_auth(client):
    r = client.get("/v1/items/pending")
    assert r.status_code == 401

    r = client.get("/v1/items/pending", headers={"Authorization": "Bearer wrong-key"})
    assert r.status_code == 403


def test_get_pending_returns_items(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=3)

    r = client.get("/v1/items/pending", headers=auth_headers())
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_get_pending_limit(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=5)

    r = client.get("/v1/items/pending?limit=2", headers=auth_headers())
    assert len(r.json()) == 2


def test_get_pending_excludes_non_pending(client):
    batch_id = _make_batch(client)
    items = [
        {"source_id": "bwb:1", "data": {}, "status": "pending"},
        {"source_id": "bwb:2", "data": {}, "status": "created"},
    ]
    client.post(f"/v1/batches/{batch_id}/items", json=items, headers=auth_headers())

    r = client.get("/v1/items/pending", headers=auth_headers())
    assert len(r.json()) == 1
    assert r.json()[0]["source_id"] == "bwb:1"


def test_patch_item_status(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=1)

    item_id = client.get("/v1/items/pending", headers=auth_headers()).json()[0]["id"]

    r = client.patch(
        f"/v1/items/{item_id}",
        json={"status": "created", "ol_key": "/books/OL1M"},
        headers=auth_headers(),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "created"
    assert data["ol_key"] == "/books/OL1M"
    assert data["import_time"] is not None


def test_patch_item_not_found(client):
    r = client.patch("/v1/items/9999", json={"status": "failed"}, headers=auth_headers())
    assert r.status_code == 404


def test_patch_item_invalid_status(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=1)
    item_id = client.get("/v1/items/pending", headers=auth_headers()).json()[0]["id"]

    r = client.patch(f"/v1/items/{item_id}", json={"status": "bogus"}, headers=auth_headers())
    assert r.status_code == 422


def test_patch_item_failed_sets_error(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=1)
    item_id = client.get("/v1/items/pending", headers=auth_headers()).json()[0]["id"]

    r = client.patch(
        f"/v1/items/{item_id}",
        json={"status": "failed", "error": "isbn not found"},
        headers=auth_headers(),
    )
    assert r.json()["error"] == "isbn not found"
    assert r.json()["import_time"] is not None
