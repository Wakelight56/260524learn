"""回复装饰阶段 — 对 AI 回复进行后处理"""

import logging

from src.pipeline.stage import Stage, StageContext

logger = logging.getLogger("autochat.stage.decorate")


class DecorateStage(Stage):
    """对 AI 回复做一些后期处理"""

    def __init__(self, config: dict):
        bot_cfg = config.get("bot", {})
        self._add_timestamp = bot_cfg.get("add_timestamp", False)

    async def process(self, ctx: StageContext):
        if not ctx.reply:
            return

        # 去除可能的空行
        ctx.reply = ctx.reply.strip()

        # 如果回复为空，丢弃
        if not ctx.reply:
            ctx.reply = None
            ctx.should_stop = True
            return
