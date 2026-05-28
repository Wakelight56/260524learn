"""Pipeline 阶段基类 — 每个阶段处理/转换消息事件，可打断管线"""

import abc
from typing import Optional

from src.platform.event import MessageEvent


class StageContext:
    """管线上下文 — 贯穿整条管线的状态容器"""

    def __init__(self, event: MessageEvent):
        self.event = event
        self.should_stop = False  # 设为 True 中断后续阶段
        self.reply: Optional[str] = None  # 最终回复
        self.extra: dict = {}


class Stage(abc.ABC):
    """处理阶段基类"""

    @abc.abstractmethod
    async def process(self, ctx: StageContext):
        """处理上下文，可修改 ctx 来影响后续阶段"""
        ...
