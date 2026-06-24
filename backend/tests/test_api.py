"""Integration tests for FastAPI endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Must patch before importing main
import sys
sys.path.insert(0, ".")

from main import app, releases_store

client = TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "timestamp" in data

    def test_health_shows_openai_status(self):
        response = client.get("/api/health")
        data = response.json()
        assert "openai_configured" in data


class TestReleasesEndpoint:
    def test_list_empty(self):
        releases_store._store.clear()
        response = client.get("/api/releases")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_nonexistent_release(self):
        response = client.get("/api/releases/nonexistent")
        assert response.status_code == 404

    def test_approve_nonexistent(self):
        response = client.post("/api/releases/nonexistent/approve", json={})
        assert response.status_code == 404

    def test_reject_nonexistent(self):
        response = client.post("/api/releases/nonexistent/reject")
        assert response.status_code == 404

    def test_approve_with_edits(self):
        # Insert a test release
        releases_store.put("test-123", {
            "id": "test-123",
            "name": "v1.0",
            "status": "review",
            "artifacts": {
                "changelog": "original",
                "internal_release_notes": "original",
                "customer_release_notes": "original",
            },
        })
        response = client.post("/api/releases/test-123/approve", json={
            "changelog": "edited changelog"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["artifacts"]["changelog"] == "edited changelog"
        assert data["artifacts"]["internal_release_notes"] == "original"
        # Cleanup
        releases_store._store.pop("test-123", None)

    def test_approve_already_approved(self):
        releases_store.put("approved-1", {
            "id": "approved-1",
            "status": "approved",
            "artifacts": {},
        })
        response = client.post("/api/releases/approved-1/approve", json={})
        assert response.status_code == 409
        releases_store._store.pop("approved-1", None)

    def test_reject_approved_fails(self):
        releases_store.put("approved-2", {
            "id": "approved-2",
            "status": "approved",
            "artifacts": {},
        })
        response = client.post("/api/releases/approved-2/reject")
        assert response.status_code == 409
        releases_store._store.pop("approved-2", None)

    def test_delete_release(self):
        releases_store.put("del-1", {"id": "del-1", "status": "review"})
        response = client.delete("/api/releases/del-1")
        assert response.status_code == 200
        assert releases_store.get("del-1") is None


class TestDocsEndpoint:
    def test_list_docs(self):
        response = client.get("/api/docs")
        assert response.status_code == 200
        docs = response.json()
        assert len(docs) == 3

    def test_search_requires_query(self):
        response = client.get("/api/docs/search")
        assert response.status_code == 422  # Validation error


class TestGenerateValidation:
    def test_empty_release_name_rejected(self):
        response = client.post("/api/releases/generate", json={
            "release_name": "",
        })
        assert response.status_code == 422

    def test_too_long_release_name_rejected(self):
        response = client.post("/api/releases/generate", json={
            "release_name": "x" * 101,
        })
        assert response.status_code == 422


class TestReleaseStore:
    def test_lru_eviction(self):
        from main import ReleaseStore
        store = ReleaseStore(max_size=3)
        store.put("a", {"id": "a"})
        store.put("b", {"id": "b"})
        store.put("c", {"id": "c"})
        store.put("d", {"id": "d"})  # Should evict "a"
        assert store.get("a") is None
        assert store.get("d") is not None
        assert store.count() == 3

    def test_access_refreshes_lru(self):
        from main import ReleaseStore
        store = ReleaseStore(max_size=3)
        store.put("a", {"id": "a"})
        store.put("b", {"id": "b"})
        store.put("c", {"id": "c"})
        store.get("a")  # Refresh "a"
        store.put("d", {"id": "d"})  # Should evict "b" (oldest unused)
        assert store.get("a") is not None
        assert store.get("b") is None
