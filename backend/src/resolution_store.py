"""
决议数据持久化（JSON 文件读写）

供 routers/meetings.py 和 graph/extract.py 共用，
避免 graph → routers 的循环导入。
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path.home() / ".engineer_assistant" / "data"
RESOLUTIONS_FILE = DATA_DIR / "resolutions.json"


def load_resolutions() -> dict:
    """加载所有决议"""
    if not RESOLUTIONS_FILE.exists():
        return {}
    try:
        return json.loads(RESOLUTIONS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load resolutions from %s: %s", RESOLUTIONS_FILE, e)
        return {}


def save_resolutions(data: dict) -> None:
    """保存所有决议"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESOLUTIONS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
