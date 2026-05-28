"""事件总线 — 解耦消息来源与处理管线"""

import asyncio
import logging
from asyncio import Queue
from dataclasses import dataclass, field

logger = logging.getLogger("autochat.eventbus")


@dataclass
class Event:
    """统一事件"""
    type: str  # "message" | "notice" | "request"
    data: dict
    platform_name: str = ""
    source: str = ""  # 平台来源标识


class EventBus:
    """异步事件总线。各平台将事件推入队列，dispatch 分发给对应的 PipelineScheduler。"""

    def __init__(self):
        self._queue: Queue[Event] = Queue()
        self._handlers: dict[str, list] = {}  # event_type -> [handler]

    def subscribe(self, event_type: str, handler):
        """订阅某类事件"""
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler):
        self._handlers.setdefault(event_type, []).remove(handler)

    async def publish(self, event: Event):
        """发布事件"""
        await self._queue.put(event)

    async def dispatch(self):
        """事件分发循环"""
        while True:
            event = await self._queue.get()
            logger.debug("事件: type=%s platform=%s", event.type, event.platform_name)
            handlers = self._handlers.get(event.type, [])
            if not handlers:
                logger.warning("未找到 %s 事件处理器", event.type)
                continue
            for handler in handlers:
                asyncio.create_task(handler(event))
