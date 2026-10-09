"""Run against a running Compose stack: uv run python scripts/smoke.py."""

import os
import time
from uuid import uuid4

import httpx


def main():
    base_url = os.environ.get("BOOKWORM_SMOKE_URL", "http://localhost:8000")
    user = {"X-User-Id": "smoke-" + uuid4().hex}
    approver = {"X-User-Id": "smoke-reviewer", "X-Can-Approve": "true"}
    record = {
        "title": "Smoke test",
        "source_records": ["smoke:1"],
        "authors": [{"name": "Smoke Author"}],
        "publishers": ["Smoke Publisher"],
        "publish_date": "2020",
    }
    with httpx.Client(base_url=base_url, timeout=30) as client:
        assert client.get("/health/ready").status_code == 200
        project_response = client.post("/projects", headers=user, json={"name": "Smoke"})
        project_response.raise_for_status()
        project = project_response.json()["id"]
        assert (
            client.post(
                "/imports",
                headers=user,
                json={"data": [record, {"title": "Invalid"}], "project_id": project},
            ).status_code
            == 422
        )
        assert client.get("/imports", headers=user).json()["items"] == []
        response = client.post(
            "/imports",
            headers=user,
            json={
                "data": [record, record],
                "project_id": project,
            },
        )
        assert response.status_code == 202, response.text
        job = response.json()["job_id"]
        status = client.get(f"/imports/{job}", headers=user).json()
        assert status["counts"]["pending_approval"] == 1
        assert status["counts"]["failed"] == 1
        assert (
            client.post(f"/imports/{job}/approve", headers=approver, json={"all": True}).json()[
                "updated"
            ]
            == 1
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get(f"/imports/{job}", headers=user).json()
            if status["counts"]["completed"] == 1:
                assert status["counts"]["failed"] == 1
                assert status["items"][0]["error_context"] is None
                client.delete(f"/projects/{project}", headers=user).raise_for_status()
                print(
                    "Docker smoke passed: upload → validation/deduplication → approval → temporary client success"
                )
                return
            time.sleep(0.1)
        raise AssertionError(f"Dispatcher did not finish job {job}: {status}")


if __name__ == "__main__":
    main()
