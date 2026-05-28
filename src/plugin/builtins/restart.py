"""重启机器人插件 — 通过聊天指令重启 AutoChat（重启后通知）"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.plugin.restart")

_MASTER_QQ: int = 0

RESTART_FLAG = "memory/.restart_flag.json"


def setup(master_qq: int):
    global _MASTER_QQ
    _MASTER_QQ = master_qq


@register_plugin
class RestartPlugin(Plugin):

    @property
    def name(self) -> str:
        return "restart"

    async def on_message(self, event: MessageEvent) -> str | None:
        if event.message.strip() not in ("/restart", "/reboot", "重启", "重启服务"):
            return None

        if int(event.user_id) != _MASTER_QQ:
            return "你没有权限执行此操作。"

        # 保存重启目标，恢复后通知用
        flag = {"user_id": int(event.user_id)}
        if event.group_id:
            flag["group_id"] = int(event.group_id)
        os.makedirs(os.path.dirname(RESTART_FLAG), exist_ok=True)
        with open(RESTART_FLAG, "w") as f:
            json.dump(flag, f)

        async def _do_restart():
            await asyncio.sleep(0.5)

            # Docker 环境：退出进程，靠 restart: unless-stopped 自动重启
            in_docker = os.path.exists("/.dockerenv")
            if in_docker:
                logger.info("Docker 环境，退出进程等待自动重启")
                os._exit(0)
                return

            # systemd 环境
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
