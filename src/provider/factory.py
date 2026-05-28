"""Provider 工厂 — 根据配置创建对应 provider 实例"""

import logging

from src.provider.base import Provider
from src.provider.openai_provider import OpenAIProvider
from src.provider.claude_provider import ClaudeProvider

logger = logging.getLogger("autochat.provider")


def create_provider(config: dict) -> Provider:
    """根据 ai.provider 字段选择并创建 Provider"""
    provider_name = config.get("ai", {}).get("provider", "openai")

    if provider_name == "claude":
        logger.info("使用 Claude Provider")
        return ClaudeProvider(config)
    else:
        logger.info("使用 OpenAI Provider")
        return OpenAIProvider(config)
