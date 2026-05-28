"""速率限制阶段 — 防止刷屏"""

import logging
import time

from src.pipeline.stage import Stage, StageContext

logger = logging.getLogger("autochat.stage.ratelimit")


class RateLimitStage(Stage):
    """基于用户/群组的请求频率限制"""

    def __init__(self, config: dict):
        bot_cfg = config.get("bot", {})
        self._max_per_min = bot_cfg.get("rate_limit", 20)
        self._records: dict[str, list[float]] = {}

    async def process(self, ctx: StageContext):
        now = time.time()
        key = ctx.event.session_key
        records = self._records.setdefault(key, [])

        # 清理超过1分钟的记录
        self._records[key] = [t for t in records if now - t < 60]
        records = self._records[key]

        if len(records) >= self._max_per_min:
            logger.warning("频率限制: %s", key)
            ctx.should_stop = True
            return

        records.append(now)
