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


def _batch(client, name="test-batch", submitter=None):
    return client.post("/v1/batches", json={"name": name, "submitter": submitter}).json()["id"]


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
    assert r.json() == {"added": 2, "skipped": 0}
    assert client.get(f"/v1/batches/{batch_id}").json()["item_counts"] == {"pending": 2}


def test_duplicate_within_same_batch_is_skipped(client):
    """Submitting the same (source, value) twice to one batch skips the second."""
    batch_id = _batch(client)
    client.post(f"/v1/batches/{batch_id}/items", json=[ITEM])
    r = client.post(f"/v1/batches/{batch_id}/items", json=[ITEM])
    assert r.json() == {"added": 0, "skipped": 1}


def test_same_record_allowed_in_different_batches(client):
    """better_world_books:X in Jim's batch does not block it in Mek's batch."""
    jim_batch = _batch(client, name="bwb-2026-04", submitter="jim")
    mek_batch = _batch(client, name="bwb-2026-05", submitter="mek")
    client.post(f"/v1/batches/{jim_batch}/items", json=[ITEM])
    r = client.post(f"/v1/batches/{mek_batch}/items", json=[ITEM])
    assert r.json() == {"added": 1, "skipped": 0}


def test_same_submitter_different_batches_allowed(client):
    """Jim can re-import better_world_books:X in a later batch run."""
    batch_a = _batch(client, name="bwb-2026-04", submitter="jim")
    batch_b = _batch(client, name="bwb-2026-05", submitter="jim")
    client.post(f"/v1/batches/{batch_a}/items", json=[ITEM])
    r = client.post(f"/v1/batches/{batch_b}/items", json=[ITEM])
    assert r.json() == {"added": 1, "skipped": 0}


def test_incomplete_data_accepted(client):
    """BookWorm does not validate record content — that's OL's job at import time."""
    batch_id = _batch(client)
    incomplete = {"source": "better_world_books", "value": "000", "data": {}}
    r = client.post(f"/v1/batches/{batch_id}/items", json=[incomplete])
    assert r.status_code == 201
    assert r.json()["added"] == 1


def test_add_items_unknown_source_rejected(client):
    """source must be a name from identifiers.yml."""
    batch_id = _batch(client)
    bad = {"source": "made_up_source", "value": "123", "data": {}}
    assert client.post(f"/v1/batches/{batch_id}/items", json=[bad]).status_code == 422


def test_add_items_invalid_status(client):
    batch_id = _batch(client)
    r = client.post(f"/v1/batches/{batch_id}/items", json=[{**ITEM, "status": "bogus"}])
    assert r.status_code == 422


def test_add_items_batch_not_found(client):
    assert client.post("/v1/batches/9999/items", json=[]).status_code == 404
