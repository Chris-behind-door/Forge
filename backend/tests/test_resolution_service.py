"""Tests for resolution_service: CRUD, auto-index, clear with orphan restore."""

import json

import pytest

from src.services import resolution_service as rs
from src.models.meeting import ResolutionCreate, ResolutionUpdate


class TestListForMeeting:
    def test_filters_by_meeting(self, mock_data_dir, sample_resolution_data):
        mock_data_dir["resolutions_file"].write_text(
            json.dumps(sample_resolution_data), encoding="utf-8"
        )
        result = rs.list_for_meeting("mtg_abc123")
        assert len(result) == 2
        assert all(r.meeting_id == "mtg_abc123" for r in result)

    def test_empty_meeting(self, mock_data_dir):
        mock_data_dir["resolutions_file"].write_text("{}", encoding="utf-8")
        assert rs.list_for_meeting("nonexistent") == []


class TestCreate:
    @pytest.mark.asyncio
    async def test_auto_index(self, mock_data_dir, mock_graph, mock_embeddings):
        mock_data_dir["resolutions_file"].write_text("{}", encoding="utf-8")
        req = ResolutionCreate(content="新决议", index=0, status="active")
        res = await rs.create("mtg_1", "proj_1", req)
        assert res.index == 1  # first resolution gets index 1
        assert res.content == "新决议"
        assert res.meeting_id == "mtg_1"

    @pytest.mark.asyncio
    async def test_auto_index_increments(self, mock_data_dir, mock_graph, mock_embeddings):
        existing = {
            "res_x": {"id": "res_x", "meeting_id": "mtg_1", "project_id": "p1",
                       "content": "旧", "index": 3, "status": "active", "created_at": "..."}
        }
        mock_data_dir["resolutions_file"].write_text(json.dumps(existing), encoding="utf-8")
        req = ResolutionCreate(content="新", index=0, status="active")
        res = await rs.create("mtg_1", "p1", req)
        assert res.index == 4

    @pytest.mark.asyncio
    async def test_explicit_index(self, mock_data_dir, mock_graph, mock_embeddings):
        mock_data_dir["resolutions_file"].write_text("{}", encoding="utf-8")
        req = ResolutionCreate(content="指定序号", index=5, status="active")
        res = await rs.create("mtg_1", "p1", req)
        assert res.index == 5


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_content(self, mock_data_dir, mock_graph, sample_resolution_data):
        mock_data_dir["resolutions_file"].write_text(
            json.dumps(sample_resolution_data), encoding="utf-8"
        )
        req = ResolutionUpdate(content="更新内容")
        res = await rs.update("res_001", req)
        assert res.content == "更新内容"

    @pytest.mark.asyncio
    async def test_update_status(self, mock_data_dir, mock_graph, sample_resolution_data):
        mock_data_dir["resolutions_file"].write_text(
            json.dumps(sample_resolution_data), encoding="utf-8"
        )
        req = ResolutionUpdate(status="superseded")
        res = await rs.update("res_001", req)
        assert res.status == "superseded"

    @pytest.mark.asyncio
    async def test_nonexistent_raises(self, mock_data_dir, mock_graph):
        mock_data_dir["resolutions_file"].write_text("{}", encoding="utf-8")
        with pytest.raises(KeyError):
            await rs.update("nonexistent", ResolutionUpdate(content="x"))


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, mock_data_dir, mock_graph, sample_resolution_data):
        mock_data_dir["resolutions_file"].write_text(
            json.dumps(sample_resolution_data), encoding="utf-8"
        )
        await rs.delete("res_001")
        # Verify it's gone from store
        remaining = json.loads(mock_data_dir["resolutions_file"].read_text())
        assert "res_001" not in remaining
        assert "res_002" in remaining

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises(self, mock_data_dir, mock_graph):
        mock_data_dir["resolutions_file"].write_text("{}", encoding="utf-8")
        with pytest.raises(KeyError):
            await rs.delete("nonexistent")


class TestClearForMeeting:
    @pytest.mark.asyncio
    async def test_clear_deletes_resolutions(self, mock_data_dir, mock_graph):
        data = {
            "r1": {"id": "r1", "meeting_id": "mtg_1", "project_id": "p1",
                    "content": "A", "index": 1, "status": "active", "created_at": "..."},
            "r2": {"id": "r2", "meeting_id": "mtg_1", "project_id": "p1",
                    "content": "B", "index": 2, "status": "active", "created_at": "..."},
            "r3": {"id": "r3", "meeting_id": "mtg_2", "project_id": "p1",
                    "content": "C", "index": 1, "status": "active", "created_at": "..."},
        }
        mock_data_dir["resolutions_file"].write_text(json.dumps(data), encoding="utf-8")
        mock_graph["exec_query"].return_value = []

        count = await rs.clear_for_meeting("mtg_1")
        assert count == 2

        remaining = json.loads(mock_data_dir["resolutions_file"].read_text())
        assert "r3" in remaining
        assert "r1" not in remaining
        assert "r2" not in remaining
