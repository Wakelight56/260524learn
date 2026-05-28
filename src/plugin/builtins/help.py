"""帮助命令 — 仅管理员可触发"""

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

_MASTER_QQ: int = 0


def setup(master_qq: int):
    global _MASTER_QQ
    _MASTER_QQ = master_qq


@register_plugin
class HelpPlugin(Plugin):
    @property
    def name(self) -> str:
        return "help"

    async def on_message(self, event: MessageEvent) -> str | None:
        msg = event.message.strip()
        if msg not in ("/help", "/start", "帮助", "菜单", "指令"):
            return None
        if int(event.user_id) != _MASTER_QQ:
            return None
        return (
            "我是冬弥，可用指令：\n"
            "• 直接对话 — 群聊加「小冬」或@我\n"
            "• 帮助/菜单 — 显示此帮助\n"
            "• 清除对话 — 清除对话记忆\n"
            "• 状态 — 查看运行状态\n"
            "• 白名单 — 查看白名单\n"
            "• 更新知识库 — 从GitHub更新剧情知识\n"
            "• 重启 — 重启服务（仅管理）"
        )
