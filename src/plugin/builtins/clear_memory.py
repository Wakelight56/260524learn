"""清除记忆插件 — 响应 /clear 命令"""

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent
from src.store.memory import MemoryStore


@register_plugin
class ClearMemoryPlugin(Plugin):
    _store: MemoryStore = None

    @classmethod
    def set_store(cls, store: MemoryStore):
        cls._store = store

    @property
    def name(self) -> str:
        return "clear_memory"

    async def on_message(self, event: MessageEvent) -> str | None:
        if event.message.strip() in ("/clear", "/reset", "清除对话", "清除", "清空"):
            if self._store:
                self._store.clear(event.session_key)
            return "已清除当前对话记忆，让我们重新开始吧！"
        return None

