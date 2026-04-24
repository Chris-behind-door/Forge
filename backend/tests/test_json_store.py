"""Tests for json_store: load_json, save_json, ensure_dir."""

from pathlib import Path
import json

from src.services.json_store import load_json, save_json, ensure_dir


class TestEnsureDir:
    def test_creates_single_dir(self, tmp_path):
        target = tmp_path / "new_dir"
        ensure_dir(target)
        assert target.is_dir()

    def test_creates_nested_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c"
        ensure_dir(target)
        assert target.is_dir()

    def test_idempotent(self, tmp_path):
        target = tmp_path / "dir"
        ensure_dir(target)
        ensure_dir(target)  # should not raise
        assert target.is_dir()


class TestSaveAndLoad:
    def test_roundtrip_dict(self, tmp_path):
        fp = tmp_path / "test.json"
        data = {"key": "value", "nums": [1, 2, 3]}
        save_json(fp, data)
        result = load_json(fp)
        assert result == data

    def test_roundtrip_list(self, tmp_path):
        fp = tmp_path / "test.json"
        data = [1, "two", {"three": 3}]
        save_json(fp, data)
        assert load_json(fp) == data

    def test_saves_utf8(self, tmp_path):
        fp = tmp_path / "test.json"
        data = {"中文": "测试"}
        save_json(fp, data)
        assert load_json(fp) == data
        # Verify actual file content is UTF-8
        raw = fp.read_text(encoding="utf-8")
        assert "中文" in raw

    def test_creates_parent_dirs_on_save(self, tmp_path):
        fp = tmp_path / "a" / "b" / "data.json"
        save_json(fp, {"x": 1})
        assert load_json(fp) == {"x": 1}


class TestLoadJsonDefaults:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        fp = tmp_path / "nonexistent.json"
        assert load_json(fp) == {}

    def test_missing_file_returns_custom_default(self, tmp_path):
        fp = tmp_path / "nonexistent.json"
        assert load_json(fp, default=[]) == []

    def test_missing_file_returns_none_default(self, tmp_path):
        fp = tmp_path / "nonexistent.json"
        assert load_json(fp, default=None) == {}

    def test_corrupt_json_returns_empty_dict(self, tmp_path):
        fp = tmp_path / "bad.json"
        fp.write_text("{invalid json content", encoding="utf-8")
        assert load_json(fp) == {}

    def test_corrupt_json_returns_custom_default(self, tmp_path):
        fp = tmp_path / "bad.json"
        fp.write_text("not json at all", encoding="utf-8")
        assert load_json(fp, default=[]) == []
