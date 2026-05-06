def _make_batch(client):
    return client.post("/v1/batches", json={"name": "b"}).json()["id"]


def _add_items(client, batch_id, n=3):
    items = [
        {
            "source": "bwb",
            "value": f"978000000000{i}",
            "data": {"title": f"Book {i}", "source_records": [f"bwb:978000000000{i}"]},
        }
        for i in range(n)
    ]
    client.post(f"/v1/batches/{batch_id}/items", json=items)


def test_get_pending_returns_items(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=3)
    r = client.get("/v1/items/pending")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_get_pending_limit(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=5)
    assert len(client.get("/v1/items/pending?limit=2").json()) == 2


def test_get_pending_limit_must_be_positive(client):
    assert client.get("/v1/items/pending?limit=0").status_code == 422


def test_get_pending_excludes_non_pending(client):
    batch_id = _make_batch(client)
    items = [
        {"source": "bwb", "value": "9780001", "data": {"title": "A", "source_records": ["bwb:9780001"]}, "status": "pending"},
        {"source": "bwb", "value": "9780002", "data": {"title": "B", "source_records": ["bwb:9780002"]}, "status": "created"},
    ]
    client.post(f"/v1/batches/{batch_id}/items", json=items)
    r = client.get("/v1/items/pending")
    assert len(r.json()) == 1
    assert r.json()[0]["value"] == "9780001"


def test_patch_item_status(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=1)
    item_id = client.get("/v1/items/pending").json()[0]["id"]

    r = client.patch(f"/v1/items/{item_id}", json={"status": "created", "ol_key": "/books/OL1M"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "created"
    assert data["ol_key"] == "/books/OL1M"
    assert data["import_time"] is not None


def test_patch_does_not_clear_unset_fields(client):
    """Omitting 'error' from PATCH should not overwrite an existing error value."""
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=1)
    item_id = client.get("/v1/items/pending").json()[0]["id"]

    # First set an error
    client.patch(f"/v1/items/{item_id}", json={"status": "failed", "error": "timeout"})
    # Now patch only status — error should be preserved
    r = client.patch(f"/v1/items/{item_id}", json={"status": "pending"})
    assert r.json()["error"] == "timeout"


def test_patch_item_not_found(client):
    assert client.patch("/v1/items/9999", json={"status": "failed"}).status_code == 404


def test_patch_item_invalid_status(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=1)
    item_id = client.get("/v1/items/pending").json()[0]["id"]
    assert client.patch(f"/v1/items/{item_id}", json={"status": "bogus"}).status_code == 422


def test_patch_item_failed_sets_error_and_import_time(client):
    batch_id = _make_batch(client)
    _add_items(client, batch_id, n=1)
    item_id = client.get("/v1/items/pending").json()[0]["id"]
    r = client.patch(f"/v1/items/{item_id}", json={"status": "failed", "error": "isbn not found"})
    assert r.json()["error"] == "isbn not found"
    assert r.json()["import_time"] is not None
