"""状态查询插件 — 响应 /status 命令"""

import time

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent


_bot_start_time = time.time()


@register_plugin
class StatusPlugin(Plugin):
    @property
    def name(self) -> str:
        return "status"

    async def on_message(self, event: MessageEvent) -> str | None:
        if event.message.strip() in ("/status", "状态", "运行状态"):
            uptime = time.time() - _bot_start_time
            hours, rem = divmod(int(uptime), 3600)
            mins, secs = divmod(rem, 60)
            return (
                f"AutoChat 运行状态\n"
                f"• 运行时间: {hours}时{mins}分{secs}秒\n"
                f"• 平台: {event.platform_name}\n"
                f"• 工作正常 ✓"
            )
        return None

