"""
LLM 客户端 — OpenAI 兼容 API 调用（httpx async）
"""

import logging

import httpx

from ..utils.llm_config import (
    PROVIDERS,
    get_active_model,
    get_active_provider,
    get_api_key,
    get_provider_base_url,
)

logger = logging.getLogger(__name__)

# 请求超时（秒）
TIMEOUT = 180

# 模块级共享 client（复用连接池）
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """获取或创建共享的 AsyncClient"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=TIMEOUT)
    return _client


async def close_client() -> None:
    """关闭共享 client（应用退出时调用）"""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


async def call_llm(
    messages: list[dict],
    provider: str | None = None,
    model: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
) -> dict:
    """
    调用 OpenAI 兼容的 chat/completions API

    Args:
        messages: 消息列表
        provider: provider 名称（默认使用活跃配置）
        model: 模型名称（默认使用活跃配置）
        tools: 工具定义列表（function calling）
        tool_choice: tool_choice 参数

    Returns:
        完整的 API response dict
    """
    provider = provider or get_active_provider()
    model = model or get_active_model()

    if not provider:
        raise ValueError("未配置 LLM provider，请先调用 POST /config/llm 设置")

    if not model:
        model = PROVIDERS.get(provider, {}).get("default_model", "")
        if not model:
            raise ValueError(f"未指定模型，且 provider {provider} 无默认模型")

    base_url = get_provider_base_url(provider)
    if not base_url:
        raise ValueError(f"Provider {provider} 的 base_url 未配置")

    api_key = get_api_key(provider)
    if not api_key:
        raise ValueError(
            f"Provider {provider} 的 API Key 未配置，请先调用 POST /config/llm"
        )

    url = f"{base_url.rstrip('/')}/chat/completions"

    payload: dict = {
        "model": model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.info(f"调用 LLM: {provider}/{model}")

    client = _get_client()
    try:
        response = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as e:
        logger.error(f"LLM 请求失败 ({provider}/{model}): {e}")
        raise

    if response.status_code >= 400:
        logger.error(f"LLM API 错误 {response.status_code}: {response.text[:500]}")
        response.raise_for_status()

    return response.json()
