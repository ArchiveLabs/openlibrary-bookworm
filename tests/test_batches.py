ITEM = {
    "source": "better_world_books",
    "value": "9780451524935",
    "data": {"title": "1984", "source_records": ["better_world_books:9780451524935"]},
}
ITEM2 = {
    "source": "better_world_books",
    "value": "9780060935467",
    "data": {"title": "To Kill a Mockingbird", "source_records": ["better_world_books:9780060935467"]},
}


def _batch(client, name="test-batch"):
    return client.post("/v1/batches", json={"name": name}).json()["id"]


def test_health(client):
    assert client.get("/health").status_code == 200


def test_create_batch(client):
    r = client.post("/v1/batches", json={"name": "my-batch", "submitter": "mekBot"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "my-batch"
    assert data["submitter"] == "mekBot"
    assert "id" in data


def test_get_batch_not_found(client):
    assert client.get("/v1/batches/9999").status_code == 404


def test_get_batch_empty(client):
    batch_id = _batch(client)
    r = client.get(f"/v1/batches/{batch_id}")
    assert r.status_code == 200
    assert r.json()["item_counts"] == {}


def test_add_items_and_counts(client):
    batch_id = _batch(client)
    r = client.post(f"/v1/batches/{batch_id}/items", json=[ITEM, ITEM2])
    assert r.status_code == 201
    body = r.json()
    assert body["added"] == 2
    assert body["skipped"] == 0
    assert body["errors"] == []
    assert client.get(f"/v1/batches/{batch_id}").json()["item_counts"] == {"pending": 2}


def test_add_items_skips_duplicates(client):
    batch_id = _batch(client)
    client.post(f"/v1/batches/{batch_id}/items", json=[ITEM])
    r = client.post(f"/v1/batches/{batch_id}/items", json=[ITEM])
    body = r.json()
    assert body["added"] == 0
    assert body["skipped"] == 1
    assert body["errors"] == []


def test_add_items_validation_error(client):
    batch_id = _batch(client)
    bad = {"source": "better_world_books", "value": "999", "data": {}}
    r = client.post(f"/v1/batches/{batch_id}/items", json=[bad])
    assert r.status_code == 201
    body = r.json()
    assert body["added"] == 0
    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["source"] == "better_world_books"
    assert err["value"] == "999"
    assert any("title" in m or "source_records" in m for m in err["messages"])


def test_add_items_unknown_source_rejected(client):
    batch_id = _batch(client)
    bad = {"source": "bwb", "value": "123", "data": {"title": "x", "source_records": ["x:123"]}}
    r = client.post(f"/v1/batches/{batch_id}/items", json=[bad])
    assert r.status_code == 422  # "bwb" is not a valid OL identifier name


def test_add_items_invalid_status(client):
    batch_id = _batch(client)
    r = client.post(f"/v1/batches/{batch_id}/items", json=[{**ITEM, "status": "bogus"}])
    assert r.status_code == 422


def test_add_items_batch_not_found(client):
    assert client.post("/v1/batches/9999/items", json=[]).status_code == 404


def test_mixed_valid_and_invalid(client):
    """Valid items are inserted even when some records in the same request fail validation."""
    batch_id = _batch(client)
    bad = {"source": "better_world_books", "value": "bad-1", "data": {}}
    r = client.post(f"/v1/batches/{batch_id}/items", json=[ITEM, bad])
    body = r.json()
    assert body["added"] == 1
    assert body["skipped"] == 0
    assert len(body["errors"]) == 1


def test_source_response_matches_ol_identifier_name(client):
    """source in the response is the OL identifier name, not a shorthand."""
    batch_id = _batch(client)
    client.post(f"/v1/batches/{batch_id}/items", json=[ITEM])
    item = client.get("/v1/items/pending").json()[0]
    assert item["source"] == "better_world_books"
