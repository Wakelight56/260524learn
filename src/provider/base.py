"""AI Provider 抽象基类"""

import abc
from typing import Optional


class Provider(abc.ABC):
    """AI 模型提供商接口"""

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """发送聊天请求，返回回复文本"""
        ...
