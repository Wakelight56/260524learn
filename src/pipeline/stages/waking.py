"""唤醒检测阶段 — 判断是否需要回复"""

import logging
import re

from src.pipeline.stage import Stage, StageContext

logger = logging.getLogger("autochat.stage.waking")


class WakingStage(Stage):
    """唤醒检测：私聊全自动回复；群聊需 @/关键词/前缀触发"""

    def __init__(self, config: dict):
        self._config = config
        bot_cfg = config.get("bot", {})
        self._trigger_prefix = bot_cfg.get("trigger_prefix", "")
        self._trigger_at_mention = bot_cfg.get("trigger_at_mention", True)
        self._nickname = bot_cfg.get("nickname", [])
        self._auto_reply_private = bot_cfg.get("auto_reply_private", True)

    async def process(self, ctx: StageContext):
        event = ctx.event

        if event.is_private:
            if not self._auto_reply_private:
                ctx.should_stop = True
            return

        if event.is_group:
            # 前缀触发
            if self._trigger_prefix and event.message.startswith(self._trigger_prefix):
                ctx.extra["cleaned_message"] = event.message[len(self._trigger_prefix):].strip()
                return

            # @触发
            if self._trigger_at_mention and self._has_at_self(event):
                ctx.extra["cleaned_message"] = re.sub(
                    r"\[CQ:at,qq=\d+\]", "", event.message
                ).strip()
                return

            # 关键词触发
            if self._nickname:
                for name in self._nickname:
                    if name in event.message:
                        return

            # 不满足任何条件，不回复
            ctx.should_stop = True

    def _has_at_self(self, event) -> bool:
        return f"[CQ:at,qq={event.self_id}]" in event.raw_message
