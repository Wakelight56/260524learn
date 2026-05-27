from typing import Optional

from anthropic import AsyncAnthropic

from .base import AIProvider


class ClaudeProvider(AIProvider):
    """Anthropic Claude 接口"""

    def __init__(self, config: dict):
        self.client = AsyncAnthropic(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", "https://api.anthropic.com"),
        )
        self.model = config.get("model", "claude-sonnet-4-6")
        self.max_tokens = config.get("max_tokens", 2000)
        self.temperature = config.get("temperature", 0.7)

    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        resp = await self.client.messages.create(
            model=self.model,
            system=system_prompt or "",
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
        )
        return resp.content[0].text if resp.content else ""

    def count_tokens(self, text: str) -> int:
        return len(text) // 2
