"""重启机器人插件 — 通过聊天指令重启 AutoChat"""

import asyncio
import logging
import subprocess

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.plugin.restart")

_MASTER_QQ: int = 0


def setup(master_qq: int):
    global _MASTER_QQ
    _MASTER_QQ = master_qq


@register_plugin
class RestartPlugin(Plugin):

    @property
    def name(self) -> str:
        return "restart"

    async def on_message(self, event: MessageEvent) -> str | None:
        if event.message.strip() not in ("/restart", "/reboot"):
            return None

        if int(event.user_id) != _MASTER_QQ:
            return "你没有权限执行此操作。"

        # 先回复，再异步重启
        async def _do_restart():
            await asyncio.sleep(0.5)
            try:
                subprocess.run(
                    ["systemctl", "restart", "autochat"],
                    timeout=5,
                    capture_output=True,
                )
            except Exception as e:
                logger.error("重启失败: %s", e)

        asyncio.create_task(_do_restart())
        return "正在重启……请稍候。"
