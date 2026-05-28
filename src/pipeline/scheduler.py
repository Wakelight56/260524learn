"""Pipeline 调度器 — 按顺序执行各阶段"""

import logging
from typing import Callable

from src.pipeline.stage import Stage, StageContext
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.pipeline")


class PipelineScheduler:
    """管线调度器 — 持有阶段列表，依次执行"""

    def __init__(self):
        self._stages: list[Stage] = []
        self._send_func: Callable = None

    def add_stage(self, stage: Stage):
        self._stages.append(stage)

    def set_sender(self, send_func: Callable):
        self._send_func = send_func

    async def execute(self, event: MessageEvent):
        ctx = StageContext(event)
        logger.debug("管线开始: stage_count=%d msg=%s", len(self._stages), event.message[:50])
        for i, stage in enumerate(self._stages):
            try:
                logger.debug("  stage[%d] %s ...", i, type(stage).__name__)
                await stage.process(ctx)
                logger.debug("  stage[%d] done, should_stop=%s", i, ctx.should_stop)
                if ctx.should_stop:
                    break
            except Exception as e:
                logger.error("阶段 %s 异常: %s", type(stage).__name__, e)
                ctx.should_stop = True
                ctx.reply = f"处理出错: {str(e)[:100]}"
                break

        # 发送回复
        if ctx.reply and self._send_func:
            try:
                target = event.reply(ctx.reply)
                await self._send_func(target, ctx.reply)
            except Exception as e:
                logger.error("发送失败: %s", e)
