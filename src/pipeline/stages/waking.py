"""唤醒检测阶段 — 判断是否需要回复（含概率触发）"""

import logging
import random
import re

from src.pipeline.stage import Stage, StageContext

logger = logging.getLogger("autochat.stage.waking")

# 关键词 → 概率权重加成
RELEVANT_WORDS = [
    "音乐", "歌", "曲", "练习", "VBS", "舞台", "演出", "live", "ライブ",
    "咖啡", "コーヒー", "coffee",
    "书", "本", "読", "读", "图书馆", "図書館",
    "彰人", "杏", "心羽", "MEIKO", "KAITO", "谦", "連", "司学长",
    "CRANE", "游戏", "街頭", "ストリート",
    "钢琴", "ピアノ", "piano", "小提琴", "バイオリン", "古典",
    "鱿鱼", "イカ",
    "学校", "授業", "上课", "クラス",
    "冬弥", "Toya",
]


class WakingStage(Stage):
    """唤醒检测：私聊全回复；群聊需触发或概率触发"""

    def __init__(self, config: dict):
        self._config = config
        bot_cfg = config.get("bot", {})
        self._trigger_prefix = bot_cfg.get("trigger_prefix", "")
        self._trigger_at_mention = bot_cfg.get("trigger_at_mention", True)
        self._nickname = bot_cfg.get("nickname", [])
        self._auto_reply_private = bot_cfg.get("auto_reply_private", True)
        self._random_prob = bot_cfg.get("random_reply_probability", 0.0)

    async def process(self, ctx: StageContext):
        event = ctx.event

        if event.is_private:
            if not self._auto_reply_private:
                ctx.should_stop = True
            return

        if event.is_group:
            msg = event.message

            # 前缀触发
            if self._trigger_prefix and msg.startswith(self._trigger_prefix):
                ctx.extra["cleaned_message"] = msg[len(self._trigger_prefix):].strip()
                return

            # @触发
            if self._trigger_at_mention and self._has_at_self(event):
                ctx.extra["cleaned_message"] = re.sub(
                    r"\[CQ:at,qq=\d+\]", "", msg
                ).strip()
                return

            # 关键词触发
            if self._nickname:
                for name in self._nickname:
                    if name in msg:
                        return

            # 概率触发（不满足直接触发条件时）
            if self._random_prob > 0:
                prob = self._calculate_probability(msg)
                roll = random.random()
                logger.debug(
                    "概率触发: prob=%.2f roll=%.2f msg=%s", prob, roll, msg[:30],
                )
                if roll < prob:
                    logger.info("概率触发回复: prob=%.2f", prob)
                    return

            # 不满足任何条件
            ctx.should_stop = True

    def _calculate_probability(self, message: str) -> float:
        """根据消息内容计算回复概率"""
        base = self._random_prob

        # 提问加成
        has_question = "?" in message or "？" in message

        # 长度加成（较长消息更可能为有效对话）
        length_bonus = 0
        if len(message) > 10:
            length_bonus += 0.05
        if len(message) > 30:
            length_bonus += 0.05
        if len(message) > 60:
            length_bonus += 0.05

        # 关键词加成（涉及冬弥相关话题）
        keyword_bonus = 0
        hit_keywords = [kw for kw in RELEVANT_WORDS if kw in message]
        if hit_keywords:
            keyword_bonus = 0.15 + 0.05 * min(len(hit_keywords), 3)

        # 直接提及加成（提到冬弥本人）
        mention_bonus = 0.3 if "冬弥" in message else 0

        prob = base + (0.2 if has_question else 0) + length_bonus + keyword_bonus + mention_bonus
        return min(prob, 0.85)

    def _has_at_self(self, event) -> bool:
        return f"[CQ:at,qq={event.self_id}]" in event.raw_message
