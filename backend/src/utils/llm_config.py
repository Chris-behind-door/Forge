"""
LLM 配置管理

功能：
- Provider 预定义列表（base_url）
- API Key 通过 keyring 存储到系统密钥链
- 活跃 provider + model 存到 config.json
- 首次启动从 .env 读取默认配置
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import keyring
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# keyring 参数
KEYRING_SERVICE = "engineer-assistant"

# keyring 是否可用
_keyring_available: bool | None = None


def _check_keyring() -> bool:
    """检查 keyring 是否可用"""
    global _keyring_available
    if _keyring_available is not None:
        return _keyring_available
    try:
        keyring.get_keyring()
        _keyring_available = True
    except Exception:
        _keyring_available = False
        logger.warning("keyring 不可用，将使用环境变量作为 fallback")
    return _keyring_available


# 配置目录
CONFIG_DIR = Path.home() / ".engineer_assistant"
CONFIG_FILE = CONFIG_DIR / "config.json"

# ============ Provider 定义 ============

PROVIDERS: dict[str, dict[str, str]] = {
    "zhipu": {
        "name": "智谱 GLM",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4.7-flash",
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
    "tongyi": {
        "name": "通义千问",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-turbo",
    },
    "ollama": {
        "name": "Ollama (本地)",
        "default_base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5:7b",
    },
    "custom": {
        "name": "自定义",
        "default_base_url": "",
        "default_model": "",
    },
}


# ============ keyring 操作 ============


def _get_keyring_username(provider: str) -> str:
    """keyring 存储的 username（即 key 名）"""
    return f"{provider}_api_key"


def _env_key_name(provider: str) -> str:
    """provider 对应的环境变量名"""
    return f"{provider.upper()}_API_KEY"


def save_api_key(provider: str, api_key: str) -> None:
    """保存 API Key 到系统密钥链"""
    if _check_keyring():
        try:
            keyring.set_password(
                KEYRING_SERVICE, _get_keyring_username(provider), api_key
            )
            return
        except Exception as e:
            logger.warning(f"keyring 写入失败，fall back 到环境变量: {e}")
    # fallback: 设到当前进程环境变量
    os.environ[_env_key_name(provider)] = api_key


def get_api_key(provider: str) -> str | None:
    """从系统密钥链读取 API Key，不可用时 fall back 到环境变量"""
    if _check_keyring():
        try:
            key_val = keyring.get_password(
                KEYRING_SERVICE, _get_keyring_username(provider)
            )
            if key_val:
                return key_val
        except Exception:
            pass
    # fallback: 环境变量
    return os.environ.get(_env_key_name(provider))


def delete_api_key(provider: str) -> bool:
    """删除 API Key，返回是否成功"""
    deleted = False
    if _check_keyring():
        try:
            existing = keyring.get_password(
                KEYRING_SERVICE, _get_keyring_username(provider)
            )
            if existing:
                keyring.delete_password(
                    KEYRING_SERVICE, _get_keyring_username(provider)
                )
                deleted = True
        except (keyring.errors.PasswordDeleteError, Exception):
            pass
    # 同时清理环境变量
    env_key = _env_key_name(provider)
    if env_key in os.environ:
        del os.environ[env_key]
        deleted = True
    return deleted


def has_api_key(provider: str) -> bool:
    """检查是否已配置 API Key"""
    return get_api_key(provider) is not None


def mask_api_key(key: str | None) -> str | None:
    """脱敏 API Key，只显示前几位和后几位"""
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


# ============ config.json 操作 ============


# 内存缓存（写入时失效）
_config_cache: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    """读取 config.json（带内存缓存）"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if not CONFIG_FILE.exists():
        _config_cache = {}
        return _config_cache
    try:
        _config_cache = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return _config_cache
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"config.json 读取失败: {e}")
        _config_cache = {}
        return _config_cache


def _save_config(config: dict[str, Any]) -> None:
    """写入 config.json（同时更新缓存）"""
    global _config_cache
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _config_cache = config


def get_active_provider() -> str | None:
    """获取当前活跃 provider"""
    config = _load_config()
    return config.get("active_provider")


def get_active_model() -> str | None:
    """获取当前活跃 model"""
    config = _load_config()
    return config.get("active_model")


def get_provider_base_url(provider: str) -> str | None:
    """获取 provider 的 base_url（用户自定义 > 预定义默认）"""
    config = _load_config()
    custom_urls = config.get("base_urls", {})
    if provider in custom_urls and custom_urls[provider]:
        return custom_urls[provider]
    if provider in PROVIDERS:
        default = PROVIDERS[provider]["default_base_url"]
        return default if default else None
    return None


def set_active_config(
    provider: str, model: str | None = None, base_url: str | None = None
) -> None:
    """设置活跃 provider/model/base_url"""
    config = _load_config()
    config["active_provider"] = provider
    if model is not None:
        config["active_model"] = model
    if base_url is not None:
        if "base_urls" not in config:
            config["base_urls"] = {}
        config["base_urls"][provider] = base_url
    _save_config(config)


# ============ 首次初始化 ============


def _migrate_config_api_keys() -> None:
    """将 config.json 中的明文 API Keys 迁移到 keyring"""
    config = _load_config()
    api_keys = config.pop("api_keys", None)
    if not api_keys or not isinstance(api_keys, dict):
        return
    migrated = []
    for provider, key in api_keys.items():
        if key and isinstance(key, str) and not get_api_key(provider):
            save_api_key(provider, key)
            migrated.append(provider)
    if migrated:
        # 移除明文字段，写回 config
        _save_config(config)
        logger.info(f"已将 {migrated} 的 API Key 从 config.json 迁移到 keyring")


def _migrate_env_api_keys() -> None:
    """将 .env 中的 API Keys 迁移到 keyring（仅未保存过的 provider）"""
    backend_dir = Path(__file__).parent.parent.parent
    env_file = backend_dir / ".env"
    if not env_file.exists():
        return
    load_dotenv(env_file, override=False)
    for provider in PROVIDERS:
        env_key = _env_key_name(provider)
        val = os.getenv(env_key)
        if val and not get_api_key(provider):
            save_api_key(provider, val)
            logger.info(f"从环境变量迁移 {provider} API Key 到 keyring")


def initialize_from_env() -> None:
    """
    启动时执行初始化：
    1. 将 config.json 中的明文 API Keys 迁移到 keyring
    2. 将 .env 中的 API Keys 迁移到 keyring
    3. 首次启动时从 .env 设置默认活跃配置
    """
    _migrate_config_api_keys()
    _migrate_env_api_keys()

    if CONFIG_FILE.exists():
        return

    # 首次启动：从 .env 设置默认活跃配置
    backend_dir = Path(__file__).parent.parent.parent
    env_file = backend_dir / ".env"
    if not env_file.exists():
        logger.info("未找到 .env 文件，跳过 LLM 默认配置初始化")
        return

    provider = os.getenv("DEFAULT_LLM_PROVIDER", "")
    model = os.getenv("DEFAULT_LLM_MODEL", "")
    base_url = os.getenv(f"{provider.upper()}_API_BASE", "")

    if not provider:
        logger.info(".env 中未找到有效的 LLM 配置，跳过初始化")
        return

    set_active_config(
        provider=provider,
        model=model or PROVIDERS.get(provider, {}).get("default_model"),
        base_url=base_url or None,
    )
    logger.info(f"活跃 LLM 配置: {provider} / {model}")
