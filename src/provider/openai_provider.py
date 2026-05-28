"""OpenAI 兼容接口 provider"""

import logging
from typing import Optional

from openai import AsyncOpenAI
from openai import Timeout as OpenAITimeout

from src.provider.base import Provider

logger = logging.getLogger("autochat.provider.openai")


class OpenAIProvider(Provider):
    """支持 OpenAI / Azure / 本地 LLM 等兼容接口"""

    def __init__(self, config: dict):
        ai_cfg = config.get("ai", {}).get("openai", {})
        self._client = AsyncOpenAI(
            api_key=ai_cfg.get("api_key", ""),
            base_url=ai_cfg.get("base_url", "https://api.openai.com/v1"),
            timeout=OpenAITimeout(120.0, connect=30.0),
        )
        self._model = ai_cfg.get("model", "deepseek-v4-flash")
        self._max_tokens = ai_cfg.get("max_tokens", 2000)
        self._temperature = ai_cfg.get("temperature", 0.7)

    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        full = []
        if system_prompt:
            full.append({"role": "system", "content": system_prompt})
        full.extend(messages)

        for attempt in range(2):
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=full,
                max_tokens=max_tokens or self._max_tokens,
                temperature=self._temperature,
            )
            content = resp.choices[0].message.content or ""
            if content:
                return content
            logger.warning("AI 返回了空内容 (attempt %d/2)", attempt + 1)
        return ""
