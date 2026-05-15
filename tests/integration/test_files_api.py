"""
Integration tests for the Files API routes.
Tests the full upload → list → metadata → delete lifecycle.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_upload_csv(client: TestClient, sample_csv: Path) -> None:
    with open(sample_csv, "rb") as f:
        resp = client.post(
            "/api/v1/files/upload",
            files=[("files", (sample_csv.name, f, "text/csv"))],
            data={"session_id": "test-session"},
        )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    file_id = items[0]["id"]
    assert items[0]["original_name"] == sample_csv.name
    assert items[0]["extension"] == "csv"
    assert items[0]["size_bytes"] > 0
    return file_id  # referenced below


def test_upload_xlsx(client: TestClient, sample_xlsx: Path) -> None:
    with open(sample_xlsx, "rb") as f:
        resp = client.post(
            "/api/v1/files/upload",
            files=[("files", (sample_xlsx.name, f, "application/octet-stream"))],
        )
    assert resp.status_code == 200
    items = resp.json()
    assert items[0]["extension"] == "xlsx"


def test_upload_disallowed_extension(client: TestClient, tmp_path: Path) -> None:
    p = tmp_path / "payload.exe"
    p.write_bytes(b"\x00" * 16)
    with open(p, "rb") as f:
        resp = client.post(
            "/api/v1/files/upload",
            files=[("files", ("payload.exe", f, "application/octet-stream"))],
        )
    assert resp.status_code == 422


def test_list_files_returns_uploads(client: TestClient, sample_csv: Path) -> None:
    # Upload one file first
    with open(sample_csv, "rb") as f:
        client.post(
            "/api/v1/files/upload",
            files=[("files", (sample_csv.name, f, "text/csv"))],
            data={"session_id": "list-test"},
        )
    resp = client.get("/api/v1/files/", params={"session_id": "list-test"})
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert data["total"] >= 1


def test_get_file_metadata(client: TestClient, sample_csv: Path) -> None:
    with open(sample_csv, "rb") as f:
        upload_resp = client.post(
            "/api/v1/files/upload",
            files=[("files", (sample_csv.name, f, "text/csv"))],
        )
    file_id = upload_resp.json()[0]["id"]

    resp = client.get(f"/api/v1/files/{file_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == file_id


def test_get_file_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/files/nonexistent-id")
    assert resp.status_code == 404


def test_delete_file(client: TestClient, sample_csv: Path) -> None:
    with open(sample_csv, "rb") as f:
        upload_resp = client.post(
            "/api/v1/files/upload",
            files=[("files", (sample_csv.name, f, "text/csv"))],
        )
    file_id = upload_resp.json()[0]["id"]

    del_resp = client.delete(f"/api/v1/files/{file_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True

    # Verify gone
    get_resp = client.get(f"/api/v1/files/{file_id}")
    assert get_resp.status_code == 404


def test_delete_nonexistent_file(client: TestClient) -> None:
    resp = client.delete("/api/v1/files/does-not-exist")
    assert resp.status_code == 404
