"""自学习插件 — 采集群聊消息，为 AI 提供上下文"""
import logging
import time
from typing import Optional

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent
from src.plugin.external.self_learning_db import get_db

logger = logging.getLogger("autochat.plugin.external.self_learning")

# 不需要采集的命令前缀
SKIP_PREFIXES = ("/", "rollpig", "今日小猪", "抽小猪", "我的小猪")


@register_plugin
class SelfLearningPlugin(Plugin):
    """采集群聊消息，为 AI 提供近期上下文，改善回复的相关性和逻辑性"""

    def __init__(self):
        super().__init__()
        self._master_qq: Optional[str] = None
        self._db = get_db()
        self._start_time = time.time()

    def setup(self, master_qq: int | str):
        self._master_qq = str(master_qq)

    @property
    def name(self) -> str:
        return "self_learning"

    @property
    def description(self) -> str:
        return "采集群聊消息，提供近期对话上下文"

    async def on_message(self, event: MessageEvent) -> Optional[str]:
        """采集所有消息到数据库（不拦截消息）"""
        try:
            text = event.message.strip()

            # 跳过命令类消息（避免刷库）
            if text.startswith(SKIP_PREFIXES):
                return None

            # 只采集群聊消息（私聊也可选采集）
            if event.is_group:
                self._db.save_message(
                    group_id=event.group_id or event.user_id,
                    user_id=event.user_id,
                    message=text,
                    user_name=event.sender_name or "",
                    platform=event.platform_name,
                )
            elif event.is_private and event.user_id != self._master_qq:
                # 私聊也采集（除了 master 自己的消息，以防隐私）
                self._db.save_message(
                    group_id=event.user_id,
                    user_id=event.user_id,
                    message=text,
                    user_name=event.sender_name or "",
                    platform=event.platform_name,
                )

        except Exception as e:
            logger.error(f"消息采集失败: {e}")

        return None  # 不拦截，继续走管线

    async def on_bot_start(self):
        count = self._db.total_messages
        groups = self._db.get_group_ids()
        logger.info(f"自学习插件启动: 已采集 {count} 条消息, {len(groups)} 个群")

    async def on_bot_stop(self):
        self._db.close()
        logger.info("自学习插件已停止")
