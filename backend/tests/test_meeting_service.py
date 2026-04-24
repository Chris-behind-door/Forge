"""Tests for meeting_service: import dedup, clear resolutions, orphan restore."""

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.services import meeting_service as ms


class TestCheckImportDuplicate:
    def test_no_duplicate_passes(self, mock_data_dir, sample_meeting_data):
        # Write existing meetings
        mock_data_dir["meetings_file"].write_text(
            json.dumps(sample_meeting_data), encoding="utf-8"
        )
        # Different title/size should not raise
        ms._check_import_duplicate("proj_001", "新会议", "new.pdf", 9999)

    def test_duplicate_raises_409(self, mock_data_dir, sample_meeting_data):
        m = sample_meeting_data
        m["mtg_abc123"]["_import_file_size"] = 1024
        m["mtg_abc123"]["title"] = "第1次会议"
        mock_data_dir["meetings_file"].write_text(
            json.dumps(m), encoding="utf-8"
        )
        with pytest.raises(HTTPException) as exc_info:
            ms._check_import_duplicate("proj_001", "第1次会议", "第1次会议.pdf", 1024)
        assert exc_info.value.status_code == 409

    def test_different_project_no_duplicate(self, mock_data_dir, sample_meeting_data):
        m = sample_meeting_data
        m["mtg_abc123"]["_import_file_size"] = 1024
        m["mtg_abc123"]["title"] = "会议"
        mock_data_dir["meetings_file"].write_text(
            json.dumps(m), encoding="utf-8"
        )
        # Different project_id, should not raise
        ms._check_import_duplicate("proj_other", "会议", "会议.pdf", 1024)


class TestValidateImportFile:
    def test_pdf_accepted(self):
        assert ms._validate_import_file("doc.pdf", b"content") == ".pdf"

    def test_txt_accepted(self):
        assert ms._validate_import_file("notes.txt", b"content") == ".txt"

    def test_unsupported_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            ms._validate_import_file("image.png", b"content")
        assert exc_info.value.status_code == 400


class TestListForProject:
    def test_filters_by_project(self, mock_data_dir):
        meetings = {
            "m1": {"id": "m1", "project_id": "p1", "title": "A", "date": "2024-01-01", "raw_text": "", "summary": "", "created_at": "2024-01-01"},
            "m2": {"id": "m2", "project_id": "p2", "title": "B", "date": "2024-01-02", "raw_text": "", "summary": "", "created_at": "2024-01-02"},
            "m3": {"id": "m3", "project_id": "p1", "title": "C", "date": "2024-01-03", "raw_text": "", "summary": "", "created_at": "2024-01-03"},
        }
        mock_data_dir["meetings_file"].write_text(json.dumps(meetings), encoding="utf-8")
        result = ms.list_for_project("p1")
        assert len(result) == 2
        assert all(m.project_id == "p1" for m in result)

    def test_empty_project(self, mock_data_dir):
        mock_data_dir["meetings_file"].write_text("{}", encoding="utf-8")
        result = ms.list_for_project("nonexistent")
        assert result == []


class TestGet:
    def test_existing_meeting(self, mock_data_dir, sample_meeting_data):
        mock_data_dir["meetings_file"].write_text(
            json.dumps(sample_meeting_data), encoding="utf-8"
        )
        m = ms.get("mtg_abc123")
        assert m.title == "第1次会议"

    def test_nonexistent_raises_404(self, mock_data_dir):
        mock_data_dir["meetings_file"].write_text("{}", encoding="utf-8")
        with pytest.raises(HTTPException) as exc_info:
            ms.get("nonexistent")
        assert exc_info.value.status_code == 404
