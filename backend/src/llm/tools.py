"""
工具定义和实现 — OpenAI function calling 格式
"""

import logging
from typing import Any
from contextvars import ContextVar

from ..rag.vector_store import search_similar

logger = logging.getLogger(__name__)

# Context variable for project-scoped search
_current_project_id: ContextVar[str | None] = ContextVar('_current_project_id', default=None)

# ============ 工具定义（OpenAI function calling 格式）============

SEARCH_KB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": "在本地知识库中搜索相关文档片段。返回最相关的文档内容和来源信息。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询，尽量使用与用户问题相关的关键词",
                }
            },
            "required": ["query"],
        },
    },
}

# 所有可用工具列表
ALL_TOOLS = [SEARCH_KB_TOOL]

# 工具名 → 执行函数映射
_TOOL_FUNCTIONS: dict[str, Any] = {}

# 文档名缓存 {doc_id: name}
_doc_name_cache: dict[str, str] = {}


def _resolve_doc_name(doc_id: str) -> str:
    """从 metadata JSON 中查找文档名（带缓存）"""
    if doc_id in _doc_name_cache:
        return _doc_name_cache[doc_id]
    try:
        from ..utils.paths import DATA_DIR

        meta_path = DATA_DIR / "documents.json"
        if meta_path.exists():
            import json

            data = json.loads(meta_path.read_text("utf-8"))
            # 一次性缓存所有文档名
            for did, entry in data.items():
                if isinstance(entry, dict):
                    _doc_name_cache[did] = entry.get("name", did)
            return _doc_name_cache.get(doc_id, doc_id)
    except Exception:
        pass
    return doc_id


def _search_knowledge_base(query: str, top_k: int = 5) -> tuple[str, list[dict]]:
    """
    执行知识库搜索，格式化结果

    Returns:
        (格式化文本, 检索结果元数据列表)
    """
    project_id = _current_project_id.get()
    results = search_similar(query, top_k=top_k, project_id=project_id)

    if not results:
        return f"未找到与「{query}」相关的内容。", []

    formatted = []
    for i, r in enumerate(results, 1):
        # 来源标识
        if r.get("location"):
            source = r["location"]
        elif r.get("page"):
            source = f"第{r['page']}页"
        else:
            source = "未知位置"

        doc_id = r.get("doc_id", "unknown")
        doc_name = _resolve_doc_name(doc_id)
        text = r.get("text", "")
        formatted.append(f"[结果{i}] 来源: {doc_name}#{source}\n{text}")

    return "\n\n".join(formatted), results


# 注册工具函数
_TOOL_FUNCTIONS["search_knowledge_base"] = _search_knowledge_base


def execute_tool(tool_name: str, arguments: dict) -> tuple[str, list[dict]]:
    """
    执行工具函数

    Args:
        tool_name: 工具名称
        arguments: 工具参数

    Returns:
        (工具执行结果字符串, chunk 元数据列表)
    """
    func = _TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return f"错误：未知工具 {tool_name}", []

    try:
        result = func(**arguments)
        # 搜索工具返回 (text, chunks)，其他工具可能只返回 str
        if isinstance(result, tuple):
            text, chunks = result
            logger.info(
                f"工具 {tool_name} 执行成功，返回 {len(text)} 字符，{len(chunks)} 个 chunk"
            )
            return text, chunks
        logger.info(f"工具 {tool_name} 执行成功，返回 {len(result)} 字符")
        return result, []
    except TypeError as e:
        logger.error(f"工具 {tool_name} 参数错误: {e}")
        return f"工具执行失败：参数错误（{e}）", []
    except Exception as e:
        logger.error(f"工具 {tool_name} 执行失败: {e}")
        return "工具执行失败，请重试或更换查询方式。", []
