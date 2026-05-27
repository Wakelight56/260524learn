from abc import ABC, abstractmethod
from typing import Optional


class AIProvider(ABC):
    """AI 提供商基类"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """发送聊天请求并获取回复"""
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """估算文本token数"""
        ...
