"""示例用户插件 — 收到 "ping" 回复 "pong!"""
import logging

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.plugin.user.example")


@register_plugin
class ExamplePlugin(Plugin):

    @property
    def name(self) -> str:
        return "example"

    @property
    def description(self) -> str:
        return '示例插件：收到 "ping" 回复 "pong!"'

    async def on_message(self, event: MessageEvent) -> str | None:
        if event.message.strip() == "ping":
            logger.info("example plugin triggered by %s", event.user_id)
            return "pong!"
        return None

    async def on_bot_start(self):
        logger.info("示例插件已启动")

    async def on_bot_stop(self):
        logger.info("示例插件已停止")
