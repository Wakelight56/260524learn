"""Anthropic Claude provider"""

from typing import Optional

from anthropic import AsyncAnthropic

from src.provider.base import Provider


class ClaudeProvider(Provider):
    """Anthropic Claude 接口"""

    def __init__(self, config: dict):
        ai_cfg = config.get("ai", {}).get("claude", {})
        self._client = AsyncAnthropic(
            api_key=ai_cfg.get("api_key", ""),
            base_url=ai_cfg.get("base_url", "https://api.anthropic.com"),
        )
        self._model = ai_cfg.get("model", "claude-sonnet-4-6")
        self._max_tokens = ai_cfg.get("max_tokens", 2000)
        self._temperature = ai_cfg.get("temperature", 0.7)

    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            system=system_prompt or "",
            messages=messages,
            max_tokens=max_tokens or self._max_tokens,
            temperature=self._temperature,
        )
        return resp.content[0].text if resp.content else ""
