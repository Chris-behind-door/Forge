"""术语备忘录服务 — 读写 memo.json，供 LLM 维护易混淆术语的区别记录。"""

import json
import logging
from datetime import datetime, timezone

from ..utils.paths import MEMO_FILE, ensure_dirs

logger = logging.getLogger(__name__)


def _load_memo_data() -> dict:
    """加载备忘录原始数据，返回空结构如果文件不存在。"""
    if not MEMO_FILE.exists():
        return {"entries": []}
    try:
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("备忘录文件损坏或为空，已重置: %s (%s)", MEMO_FILE, exc)
        return {"entries": []}
    return data


def _save_memo_data(data: dict) -> None:
    """原子写入备忘录数据。"""
    ensure_dirs()
    tmp = MEMO_FILE.with_suffix(MEMO_FILE.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(MEMO_FILE)


def load_memo() -> list[dict]:
    """加载所有备忘录条目。"""
    return _load_memo_data().get("entries", [])


def save_memo(entries: list[dict]) -> None:
    """保存备忘录条目列表（覆盖写入）。"""
    _save_memo_data({"entries": entries})


def update_memo_entry(term: str, content: str) -> str:
    """添加或更新一条备忘录条目。返回确认消息。"""
    entries = load_memo()
    now = datetime.now(timezone.utc).isoformat()
    for entry in entries:
        if entry["term"] == term:
            entry["content"] = content
            entry["updated_at"] = now
            save_memo(entries)
            return f"已更新备忘: 「{term}」"
    entries.append({"term": term, "content": content, "updated_at": now})
    save_memo(entries)
    return f"已添加备忘: 「{term}」"


def delete_memo_entry(term: str) -> str:
    """删除一条备忘录条目。返回确认消息。"""
    entries = load_memo()
    original_len = len(entries)
    entries = [e for e in entries if e["term"] != term]
    if len(entries) == original_len:
        return f"未找到备忘: 「{term}」"
    save_memo(entries)
    return f"已删除备忘: 「{term}」"


def format_memo_for_prompt() -> str:
    """将备忘录格式化为可注入系统提示的文本。无条目时返回空字符串。"""
    entries = load_memo()
    if not entries:
        return ""
    lines = []
    for entry in entries:
        lines.append(f"- **{entry['term']}**: {entry['content']}")
    return "\n".join(lines)
