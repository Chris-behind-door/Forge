"""Tests for API endpoints using FastAPI TestClient."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(mock_data_dir, mock_graph):
    """Create TestClient with mocked deps."""
    with patch("src.routers.meetings.rs") as mock_rs, \
         patch("src.routers.meetings.ms") as mock_ms, \
         patch("src.routers.meetings.gq") as mock_gq, \
         patch("src.routers.meetings.load_resolutions") as mock_load_res, \
         patch("src.routers.meetings.save_resolutions") as mock_save_res, \
         patch("src.main.resume_pending_documents", new_callable=AsyncMock):

        from src.main import app
        client = TestClient(app)
        yield client, {
            "ms": mock_ms, "rs": mock_rs, "gq": mock_gq,
            "load_res": mock_load_res, "save_res": mock_save_res,
        }


class TestListMeetings:
    def test_returns_list(self, client):
        c, mocks = client
        mocks["ms"].list_for_project.return_value = []
        resp = c.get("/projects/proj_001/meetings")
        assert resp.status_code == 200
        assert resp.json() == []


class TestGetResolutions:
    def test_returns_resolutions(self, client):
        c, mocks = client
        mocks["rs"].list_for_meeting.return_value = []
        resp = c.get("/meetings/mtg_1/resolutions")
        assert resp.status_code == 200
        assert resp.json() == []


class TestDeleteResolution:
    def test_delete_existing(self, client):
        c, mocks = client
        mocks["rs"].delete = AsyncMock()
        resp = c.delete("/resolutions/res_001")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_nonexistent(self, client):
        c, mocks = client
        mocks["rs"].delete = AsyncMock(side_effect=KeyError)
        resp = c.delete("/resolutions/nonexistent")
        assert resp.status_code == 404


class TestCleanupResolutions:
    def test_cleanup_no_duplicates(self, client):
        c, mocks = client
        mocks["load_res"].return_value = {
            "r1": {"id": "r1", "meeting_id": "m1", "index": 1, "created_at": "2024-01-01"},
        }
        resp = c.post("/admin/cleanup-resolutions")
        assert resp.status_code == 200
        assert resp.json()["removed_duplicates"] == 0

    def test_cleanup_removes_duplicates(self, client):
        c, mocks = client
        mocks["load_res"].return_value = {
            "r1": {"id": "r1", "meeting_id": "m1", "index": 1, "created_at": "2024-01-01"},
            "r2": {"id": "r2", "meeting_id": "m1", "index": 1, "created_at": "2024-01-02"},
        }
        mocks["gq"].delete_resolution = AsyncMock()
        resp = c.post("/admin/cleanup-resolutions")
        assert resp.status_code == 200
        assert resp.json()["removed_duplicates"] == 1


class TestHealthEndpoint:
    def test_health(self, client):
        c, _ = client
        resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
