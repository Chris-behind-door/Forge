"""Shared test fixtures."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Temporary data directory replacing ~/.engineer_assistant/data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def mock_data_dir(tmp_data_dir):
    """Patch the DATA_DIR and RESOLUTIONS_FILE used by services."""
    meetings_file = tmp_data_dir / "meetings.json"
    resolutions_file = tmp_data_dir / "resolutions.json"

    with (
        patch("src.services.meeting_service.DATA_DIR", tmp_data_dir),
        patch("src.services.meeting_service.MEETINGS_FILE", meetings_file),
        patch("src.resolution_store.RESOLUTIONS_FILE", resolutions_file),
    ):
        yield {"meetings_file": meetings_file, "resolutions_file": resolutions_file}


@pytest.fixture
def mock_graph():
    """Mock all kuzu graph queries."""
    with patch("src.graph.queries.exec_query", new_callable=AsyncMock) as exec_q, \
         patch("src.graph.queries.add_project_meeting", new_callable=AsyncMock) as add_pm, \
         patch("src.graph.queries.create_resolution", new_callable=AsyncMock) as create_r, \
         patch("src.graph.queries.add_meeting_resolution", new_callable=AsyncMock) as add_mr, \
         patch("src.graph.queries.update_resolution", new_callable=AsyncMock) as update_r, \
         patch("src.graph.queries.delete_resolution", new_callable=AsyncMock) as delete_r, \
         patch("src.graph.queries.create_relation", new_callable=AsyncMock) as create_rel, \
         patch("src.graph.queries.delete_relation", new_callable=AsyncMock) as delete_rel, \
         patch("src.graph.queries.get_resolution_chain", new_callable=AsyncMock) as get_chain, \
         patch("src.graph.queries.get_project_graph", new_callable=AsyncMock) as get_graph:
        yield {
            "exec_query": exec_q,
            "add_project_meeting": add_pm,
            "create_resolution": create_r,
            "add_meeting_resolution": add_mr,
            "update_resolution": update_r,
            "delete_resolution": delete_r,
            "create_relation": create_rel,
            "delete_relation": delete_rel,
            "get_resolution_chain": get_chain,
            "get_project_graph": get_graph,
        }


@pytest.fixture
def mock_llm():
    """Mock extract_resolutions and find_and_create_links."""
    with \
        patch("src.graph.extract.extract_resolutions", new_callable=AsyncMock) as ext, \
        patch("src.graph.extract.find_and_create_links", new_callable=AsyncMock, return_value=[]) as find_links:
        yield {"extract_resolutions": ext, "find_and_create_links": find_links}


@pytest.fixture
def mock_embeddings():
    """Mock embed_texts to avoid loading models."""
    with patch("src.services.resolution_service.embed_texts", return_value=[[0.1] * 384]):
        yield


@pytest.fixture
def sample_meeting_data():
    return {
        "mtg_abc123": {
            "id": "mtg_abc123",
            "project_id": "proj_001",
            "title": "第1次会议",
            "date": "2024-01-15",
            "raw_text": "讨论了技术方案A",
            "summary": "",
            "created_at": "2024-01-15T10:00:00",
        }
    }


@pytest.fixture
def sample_resolution_data():
    return {
        "res_001": {
            "id": "res_001",
            "meeting_id": "mtg_abc123",
            "project_id": "proj_001",
            "content": "采用方案A",
            "index": 1,
            "status": "active",
            "created_at": "2024-01-15T10:30:00",
        },
        "res_002": {
            "id": "res_002",
            "meeting_id": "mtg_abc123",
            "project_id": "proj_001",
            "content": "预算50万",
            "index": 2,
            "status": "active",
            "created_at": "2024-01-15T10:31:00",
        },
    }
