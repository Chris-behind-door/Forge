"""
工具定义和实现 — OpenAI function calling 格式
"""

import logging
from typing import Any
from contextvars import ContextVar

from ..rag.vector_store import search_similar

logger = logging.getLogger(__name__)

# Context variable for project-scoped search
_current_project_id: ContextVar[str | None] = ContextVar(
    "_current_project_id", default=None
)

# ============ 工具定义（OpenAI function calling 格式）============

SEARCH_RESOLUTIONS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_resolutions",
        "description": (
            "搜索会议决议。当用户问及会议决定、决议内容、某事项是否已决定时使用。"
            "返回相关决议及其来源会议。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "关于决议的查询，如'关于基础设计的决定'",
                }
            },
            "required": ["query"],
        },
    },
}

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
ALL_TOOLS = [SEARCH_KB_TOOL, SEARCH_RESOLUTIONS_TOOL]

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
        logger.debug("Failed to resolve doc name for %s", doc_id)
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


# ---- Resolution search tool ----


async def _search_resolutions(query: str, top_k: int = 5) -> tuple[str, list[dict]]:
    """搜索与查询相关的会议决议"""
    project_id = _current_project_id.get()
    if not project_id:
        return "当前未选择项目，无法搜索决议。请先选择一个项目。", []

    from ..rag.embeddings import embed_query
    from ..graph.queries import search_similar_resolutions

    query_emb = embed_query(query)
    results = await search_similar_resolutions(project_id, query_emb, top_k=top_k)

    if not results:
        return f"未找到与「{query}」相关的会议决议。", []

    # Load meeting titles for context
    meeting_titles: dict[str, str] = {}
    try:
        from ..resolution_store import load_resolutions
        all_res = load_resolutions()
        for r in all_res.values():
            mid = r.get("meeting_id", "")
            if mid and mid not in meeting_titles:
                meeting_titles[mid] = mid  # placeholder
    except Exception:
        pass

    formatted = []
    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        content = r.get("content", "")
        meeting_id = r.get("meeting_id", "")
        formatted.append(
            f"[决议{i}] (相关度: {score:.2f})\n{content}\n(来源会议: {meeting_id})"
        )

    return "\n\n".join(formatted), results


# 注册工具函数
_TOOL_FUNCTIONS["search_knowledge_base"] = _search_knowledge_base
_TOOL_FUNCTIONS["search_resolutions"] = _search_resolutions


async def execute_tool(tool_name: str, arguments: dict) -> tuple[str, list[dict]]:
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
        import asyncio as _asyncio

        result = func(**arguments)
        if _asyncio.iscoroutine(result):
            result = await result
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
