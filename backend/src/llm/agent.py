"""
Agent 查询入口 — 委托给 LlamaIndex Workflow 执行

保持原有的 query_with_agent 接口不变，内部使用 QueryWorkflow。
"""

import logging
from typing import Any

from .workflow import QueryWorkflow

logger = logging.getLogger(__name__)


async def query_with_agent(
    question: str, max_rounds: int = 5, context_messages: list[dict] | None = None
) -> dict[str, Any]:
    """
    带工具调用的 Agent 查询

    通过 LlamaIndex Workflow 执行：
    1. ToolCallStep — LLM + 工具循环（最多 3 轮）
    2. ExpandContextStep — 扩展检索 chunk 的上下文
    3. GenerateStep — 生成最终回答

    Returns:
        {"answer": str, "citations": list[str], "rounds": int, "retrieved_chunks": list[dict]}
    """
    workflow = QueryWorkflow(timeout=180)
    result = await workflow.run(
        question=question, context_messages=context_messages or []
    )

    # workflow.run 返回 StopEvent.result
    if isinstance(result, dict):
        logger.info(f"Workflow 完成: {result.get('rounds', '?')} 轮")
        return result

    logger.error(f"Workflow 返回意外类型: {type(result)}")
    return {
        "answer": "抱歉，Workflow 执行异常。",
        "citations": [],
        "rounds": 0,
        "retrieved_chunks": [],
    }
