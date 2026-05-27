from typing import Optional

from openai import AsyncOpenAI

from .base import AIProvider


class OpenAIProvider(AIProvider):
    """OpenAI 兼容接口（支持 OpenAI、Azure、本地 LLM 等）"""

    def __init__(self, config: dict):
        self.client = AsyncOpenAI(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", "https://api.openai.com/v1"),
        )
        self.model = config.get("model", "gpt-3.5-turbo")
        self.max_tokens = config.get("max_tokens", 2000)
        self.temperature = config.get("temperature", 0.7)

    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=full_messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
        )
        return resp.choices[0].message.content or ""

    def count_tokens(self, text: str) -> int:
        return len(text) // 2
