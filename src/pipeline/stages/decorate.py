"""回复装饰阶段 — 对 AI 回复进行后处理"""

import logging
import re

from src.pipeline.stage import Stage, StageContext

logger = logging.getLogger("autochat.stage.decorate")

# 去掉开头的括号表情描写，如（愣了下）（苦笑）（笑）等
LEADING_ACTION_RE = re.compile(r"^[（(][^）)]*[）)]\s*")

# 最大回复长度（中文字符数），超长截断到最近句号
MAX_REPLY_LEN = 999


class DecorateStage(Stage):
    """对 AI 回复做一些后期处理"""

    def __init__(self, config: dict):
        bot_cfg = config.get("bot", {})
        self._add_timestamp = bot_cfg.get("add_timestamp", False)

    async def process(self, ctx: StageContext):
        if not ctx.reply:
            return

        # 去掉开头的括号表情描写
        ctx.reply = LEADING_ACTION_RE.sub("", ctx.reply).strip()

        # 如果去掉后为空，保留原标题控制长度
        if not ctx.reply:
            ctx.reply = "……嗯。"

        # 截断过长回复
        if len(ctx.reply) > MAX_REPLY_LEN:
            truncated = ctx.reply[:MAX_REPLY_LEN]
            # 找最后一个句尾标点截断
            for punct in ("。", "！", "？", "…", "~", "～"):
                pos = truncated.rfind(punct)
                if pos >= MAX_REPLY_LEN // 2:
                    truncated = truncated[: pos + 1]
                    break
            ctx.reply = truncated.strip()
            logger.info("回复已截断: %d→%d 字", len(ctx.reply), MAX_REPLY_LEN)

        # 去除可能的空行
        ctx.reply = ctx.reply.strip()

        # 如果回复为空，丢弃
        if not ctx.reply:
            ctx.reply = None
            ctx.should_stop = True
            return
