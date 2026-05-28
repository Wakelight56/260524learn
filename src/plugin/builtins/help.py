"""帮助插件 — 响应 /help 命令"""

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent


@register_plugin
class HelpPlugin(Plugin):
    @property
    def name(self) -> str:
        return "help"

    @property
    def description(self) -> str:
        return "帮助命令：发送 /help 查看帮助"

    async def on_message(self, event: MessageEvent) -> str | None:
        msg = event.message.strip()
        if msg in ("/help", "/start", "帮助"):
            return (
                "我是 AI 机器人，支持以下功能：\n"
                "• 直接对话 — @我 或私聊即可\n"
                "• /help — 查看此帮助\n"
                "• /clear — 清除当前对话记忆\n"
                "• /status — 查看运行状态"
            )
        return None
