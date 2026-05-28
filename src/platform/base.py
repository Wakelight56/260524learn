"""Platform 抽象基类 — 所有 IM 平台适配器需实现该接口"""

import abc
import asyncio
from asyncio import Queue
from typing import Optional

from src.event_bus import Event, EventBus
from src.platform.event import MessageEvent


class Platform(abc.ABC):
    """IM 平台适配器基类"""

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self._running = False

    @property
    @abc.abstractmethod
    def platform_name(self) -> str:
        """平台唯一标识，如 napcat/telegram"""
        ...

    @abc.abstractmethod
    async def start(self):
        """启动平台连接"""
        ...

    @abc.abstractmethod
    async def stop(self):
        """停止平台连接"""
        ...

    @abc.abstractmethod
    async def send_message(self, target: dict, message: str):
        """发送消息。target 包含 user_id 或 group_id"""
        ...

    async def _publish_event(self, event: MessageEvent):
        """将消息事件发布到总线"""
        await self.event_bus.publish(
            Event(
                type="message",
                data=event,
                platform_name=self.platform_name,
                source=self.platform_name,
            )
        )
