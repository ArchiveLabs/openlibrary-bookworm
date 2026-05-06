def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_batch(client):
    r = client.post("/v1/batches", json={"name": "test-batch", "submitter": "bot"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "test-batch"
    assert data["submitter"] == "bot"
    assert "id" in data


def test_get_batch_not_found(client):
    r = client.get("/v1/batches/9999")
    assert r.status_code == 404


def test_get_batch_empty(client):
    batch_id = client.post("/v1/batches", json={"name": "empty"}).json()["id"]
    r = client.get(f"/v1/batches/{batch_id}")
    assert r.status_code == 200
    assert r.json()["item_counts"] == {}


def test_add_items_and_get_batch_counts(client):
    batch_id = client.post("/v1/batches", json={"name": "b"}).json()["id"]

    items = [
        {"source_id": "bwb:111", "data": {"title": "Book One"}, "status": "pending"},
        {"source_id": "bwb:222", "data": {"title": "Book Two"}, "status": "pending"},
    ]
    r = client.post(f"/v1/batches/{batch_id}/items", json=items)
    assert r.status_code == 201
    assert r.json() == {"added": 2, "skipped": 0}

    counts = client.get(f"/v1/batches/{batch_id}").json()["item_counts"]
    assert counts == {"pending": 2}


def test_add_items_skips_duplicates(client):
    batch_id = client.post("/v1/batches", json={"name": "dup"}).json()["id"]
    item = [{"source_id": "bwb:123", "data": {"title": "Dupe"}}]
    client.post(f"/v1/batches/{batch_id}/items", json=item)
    r = client.post(f"/v1/batches/{batch_id}/items", json=item)
    assert r.json() == {"added": 0, "skipped": 1}


def test_add_items_invalid_status(client):
    batch_id = client.post("/v1/batches", json={"name": "x"}).json()["id"]
    r = client.post(
        f"/v1/batches/{batch_id}/items",
        json=[{"source_id": "bwb:999", "data": {}, "status": "bogus"}],
    )
    assert r.status_code == 422


def test_add_items_batch_not_found(client):
    r = client.post("/v1/batches/9999/items", json=[])
    assert r.status_code == 404
