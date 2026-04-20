"""
Engineering Assistant Backend
FastAPI application entry point
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .routers.config import router as config_router
from .routers.documents import router as documents_router, resume_pending_documents
from .routers.sessions import router as sessions_router
from .routers.projects import router as projects_router
from .routers.meetings import router as meetings_router
from .utils.llm_config import get_active_provider
from .utils.paths import CURRENT_SCHEMA_VERSION, get_schema_version

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    """查询请求"""

    question: str
    top_k: int = Field(default=5, description="返回结果数量")
    session_id: str | None = None


class Citation(BaseModel):
    """引用信息"""

    doc_id: str
    doc_name: str = ""
    chunk_index: int | None = None
    page: int | None
    location: str | None = None  # CHM 用文件路径作为位置标识
    text_snippet: str  # 分块文本前 100 字符


class QueryResponse(BaseModel):
    """查询响应"""

    question: str
    answer: str
    citations: list[Citation]
    rounds: int = 0  # agent 工具调用轮数


app = FastAPI(title="Engineering Assistant Backend")

# CORS（本地开发用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(documents_router)
app.include_router(config_router)
app.include_router(sessions_router)
app.include_router(projects_router)
app.include_router(meetings_router)


@app.on_event("startup")
async def on_startup():
    """应用启动时：检查 schema 版本，恢复未完成的文档处理"""
    # 检查 schema 版本
    stored_version = get_schema_version()
    if stored_version < CURRENT_SCHEMA_VERSION:
        if stored_version == 0:
            # 首次运行或旧数据，需要重建
            logger.warning(
                f"⚠️  Schema 版本不匹配 (存储: {stored_version}, 当前: {CURRENT_SCHEMA_VERSION})"
            )
            logger.warning(
                "向量数据可能需要重建。如果遇到问题，请调用 POST /documents/reprocess-all"
            )
        else:
            logger.info(
                f"Schema 版本升级: {stored_version} -> {CURRENT_SCHEMA_VERSION}"
            )
        # 更新版本号
        from .utils.paths import set_schema_version

        set_schema_version(CURRENT_SCHEMA_VERSION)
    else:
        logger.info(f"Schema 版本: {CURRENT_SCHEMA_VERSION}")

    logger.info("检查未完成的文档...")
    await resume_pending_documents()


@app.get("/health")
async def health() -> dict:
    """健康检查端点"""
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """
    查询端点（LLM + RAG Agent）

    如果已配置 LLM，走 agent 流程（工具调用查询知识库）。
    未配置则返回 403 提示配置 API Key。
    """
    # 检查 LLM 配置
    active_provider = get_active_provider()
    if not active_provider:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="未配置 LLM API Key。请调用 POST /config/llm 设置 provider 和 api_key。",
        )

    # Load session context if session_id provided
    context_messages = None
    if request.session_id:
        from .models.session import get_context_messages

        context_messages = get_context_messages(request.session_id)

    # Save user message early so it persists even if the agent fails
    if request.session_id:
        from .models.session import save_message
        save_message(request.session_id, "user", request.question)

    # Agent 流程
    from .llm.agent import query_with_agent

    try:
        result = await query_with_agent(
            request.question, context_messages=context_messages
        )
    except ValueError as e:
        if request.session_id:
            from .models.session import save_message as _save
            _save(request.session_id, "assistant", f"[错误] {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Agent 查询失败: {e}")
        if request.session_id:
            from .models.session import save_message as _save
            _save(request.session_id, "assistant", f"[错误] LLM 查询失败: {e}")
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"LLM 查询失败: {e}")

    # 用实际检索到的 chunk 元数据构建 citations（而非正则解析回答文本）
    citations: list[Citation] = []
    raw_chunks = result.get("retrieved_chunks", [])
    for c in raw_chunks:
        text = c.get("text", "")
        chunk_id = c.get("chunk_id", "")
        # 从 chunk_id 解析序号: {doc_id}_{index}
        chunk_index = None
        parts = chunk_id.rsplit("_", 1)
        if len(parts) == 2:
            try:
                chunk_index = int(parts[1])
            except ValueError:
                pass
        doc_id = c.get("doc_id", "")
        # 解析文档名
        doc_name = ""
        try:
            from .llm.tools import _resolve_doc_name

            doc_name = _resolve_doc_name(doc_id)
        except Exception:
            pass
        citations.append(
            Citation(
                doc_id=doc_id,
                doc_name=doc_name,
                chunk_index=chunk_index,
                page=c.get("page"),
                location=c.get("location"),
                text_snippet=text[:100] + ("..." if len(text) > 100 else ""),
            )
        )

    response = QueryResponse(
        question=request.question,
        answer=result["answer"],
        citations=citations,
        rounds=result["rounds"],
    )

    # Persist assistant message to session
    if request.session_id:
        from .models.session import save_message, update_session_title, get_session_title

        save_message(
            request.session_id,
            "assistant",
            result["answer"],
            rounds=result["rounds"],
            citations=[c.model_dump() for c in citations],
        )
        # Auto-title: use first user message if title is still default
        current_title = get_session_title(request.session_id)
        if current_title == "新对话":
            title = request.question[:50] + (
                "..." if len(request.question) > 50 else ""
            )
            update_session_title(request.session_id, title)

    return response


if __name__ == "__main__":
    import argparse
    import os

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    port = args.port or int(os.environ.get("FORGE_PORT", 8765))

    uvicorn.run(app, host="127.0.0.1", port=port)
