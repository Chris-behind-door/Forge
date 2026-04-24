"""
决议数据持久化（JSON 文件读写）

供 graph/extract.py 和 services 共用，
避免循环导入。
"""

from pathlib import Path

from .services.json_store import load_json, save_json

RESOLUTIONS_FILE = Path.home() / ".engineer_assistant" / "data" / "resolutions.json"


def load_resolutions() -> dict:
    """加载所有决议"""
    return load_json(RESOLUTIONS_FILE)


def save_resolutions(data: dict) -> None:
    """保存所有决议"""
    save_json(RESOLUTIONS_FILE, data)
