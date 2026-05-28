"""插件基类 — 借鉴 AstrBot Star 系统"""

import abc
from typing import Any

from src.pipeline.stage import StageContext
from src.platform.event import MessageEvent


# 全局插件注册表
plugin_registry: list[type["Plugin"]] = []


def register_plugin(cls):
    """装饰器：注册插件"""
    plugin_registry.append(cls)
    return cls


class Plugin(abc.ABC):
    """插件基类。子类需实现 on_message 方法。"""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """插件名称"""
        ...

    @property
    def description(self) -> str:
        return ""

    async def on_message(self, event: MessageEvent) -> str | None:
        """收到消息时调用。返回非空字符串则拦截消息（不再走 AI 管线）。"""
        return None

    async def on_bot_start(self):
        """机器人启动时调用"""
        pass

    async def on_bot_stop(self):
        """机器人停止时调用"""
        pass
