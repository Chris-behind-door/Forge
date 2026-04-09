"""
LLM 配置 API 路由

GET  /config/llm            — 获取 provider 列表 + 活跃配置
POST /config/llm            — 设置活跃 provider + api_key + model + base_url
POST /config/llm/test       — 测试连接是否正常
DELETE /config/llm/{provider} — 删除某个 provider 的 key
"""

import logging

import httpx

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..utils.llm_config import (
    PROVIDERS,
    delete_api_key,
    get_active_model,
    get_active_provider,
    get_api_key,
    get_provider_base_url,
    has_api_key,
    initialize_from_env,
    mask_api_key,
    save_api_key,
    set_active_config,
)

router = APIRouter(prefix="/config", tags=["config"])
logger = logging.getLogger(__name__)


class ProviderInfo(BaseModel):
    """Provider 预设信息"""

    id: str
    name: str
    has_key: bool
    masked_key: str | None = None
    default_base_url: str
    default_model: str


class ActiveConfig(BaseModel):
    """当前活跃配置"""

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None


class LlmConfigResponse(BaseModel):
    """LLM 配置响应"""

    providers: list[ProviderInfo]
    active: ActiveConfig


class SetLlmConfigRequest(BaseModel):
    """设置 LLM 配置请求"""

    provider: str
    api_key: str | None = Field(default=None, description="API Key")
    model: str | None = Field(default=None, description="模型名称")
    base_url: str | None = Field(default=None, description="自定义 base URL")
    migrate_from: str | None = Field(
        default=None, description="从指定 provider 迁移 API Key"
    )


class TestConnectionRequest(BaseModel):
    """测试连接请求"""

    base_url: str = Field(description="Base URL")
    api_key: str | None = Field(
        default=None, description="API Key（空则从 keyring 查找）"
    )
    model: str = Field(description="模型名称")
    provider: str | None = Field(
        default=None, description="Provider（用于查找已保存的 Key）"
    )


# 启动时初始化（保护 keyring 不可用的情况）
try:
    initialize_from_env()
except Exception as e:
    logger.warning(f"LLM 配置初始化失败（不影响启动）: {e}")


@router.get("/llm", response_model=LlmConfigResponse)
async def get_llm_config() -> LlmConfigResponse:
    """获取 LLM 配置（含预设的 base_url 和默认模型）"""
    providers = [
        ProviderInfo(
            id=k,
            name=v["name"],
            has_key=has_api_key(k),
            masked_key=mask_api_key(get_api_key(k)),
            default_base_url=v["default_base_url"],
            default_model=v["default_model"],
        )
        for k, v in PROVIDERS.items()
    ]
    active = ActiveConfig(
        provider=get_active_provider(),
        model=get_active_model(),
        base_url=get_provider_base_url(get_active_provider())
        if get_active_provider()
        else None,
    )
    return LlmConfigResponse(providers=providers, active=active)


@router.post("/llm")
async def set_llm_config(request: SetLlmConfigRequest) -> dict:
    """设置 LLM 配置"""
    if request.provider not in PROVIDERS:
        raise HTTPException(
            status_code=400, detail=f"不支持的 provider: {request.provider}"
        )

    # 如果没传新 key，从 migrate_from 或当前活跃 provider 迁移 key
    if not request.api_key:
        source = request.migrate_from or get_active_provider()
        if source and source != request.provider:
            old_key = get_api_key(source)
            if old_key:
                save_api_key(request.provider, old_key)
    else:
        save_api_key(request.provider, request.api_key)

    model = request.model or PROVIDERS[request.provider]["default_model"]

    if not model:
        raise HTTPException(
            status_code=400,
            detail=f"provider {request.provider} 未配置模型名称，请通过 model 参数指定",
        )
    set_active_config(
        provider=request.provider,
        model=model,
        base_url=request.base_url,
    )

    return {
        "status": "ok",
        "provider": request.provider,
        "model": model,
        "has_key": has_api_key(request.provider),
    }


@router.post("/llm/test")
async def test_llm_connection(request: TestConnectionRequest) -> dict:
    """
    测试 LLM 连接（不保存配置，用临时参数测试）

    发送一个简单的 chat completion 请求，验证连接是否正常。
    """
    try:
        url = f"{request.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": request.model,
            "messages": [{"role": "user", "content": "你好"}],
            "max_tokens": 10,
        }
        # 如果没提供 api_key，尝试从已保存的配置中获取
        final_key = request.api_key
        if not final_key and request.provider:
            saved_key = get_api_key(request.provider)
            if saved_key:
                final_key = saved_key

        headers = {
            "Content-Type": "application/json",
        }
        if final_key:
            headers["Authorization"] = f"Bearer {final_key}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code >= 400:
            detail = response.text[:200]
            return {
                "status": "error",
                "detail": f"HTTP {response.status_code}: {detail}",
            }

        data = response.json()
        # 检查返回是否包含 choices
        if "choices" not in data or len(data["choices"]) == 0:
            return {"status": "error", "detail": "响应格式异常：无 choices 字段"}

        return {"status": "ok", "model": data.get("model", request.model)}

    except httpx.ConnectError:
        return {"status": "error", "detail": "无法连接到服务器，请检查 Base URL"}
    except httpx.TimeoutException:
        return {"status": "error", "detail": "连接超时，请检查网络或 Base URL"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.delete("/llm/{provider}")
async def delete_llm_key(provider: str) -> dict:
    """删除某个 provider 的 API Key"""
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的 provider: {provider}")

    deleted = delete_api_key(provider)
    return {"status": "deleted" if deleted else "not_found", "provider": provider}
