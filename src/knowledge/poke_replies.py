"""戳一戳回复管理器 — AI 按时间段生成，缓存复用"""

import asyncio
import json
import logging
import os
import random
from datetime import datetime
from typing import Optional

from src.knowledge.character import SYSTEM_PROMPT as TOUYA_SYSTEM_PROMPT
from src.knowledge.schedule import get_current_activity

logger = logging.getLogger("autochat.poke")

# 每个时间段缓存 6 条回复
REPLIES_PER_SLOT = 6

# 时间段定义（与 schedule.py 保持一致）
TIME_SLOTS = {
    "weekday": [(5, 7), (7, 8), (8, 12), (12, 13), (13, 15), (15, 16), (16, 17), (17, 18), (18, 19), (19, 20), (20, 21), (21, 22), (22, 23)],
    "saturday": [(5, 8), (8, 10), (10, 13), (13, 15), (15, 18), (18, 22), (22, 23)],
    "sunday":   [(5, 9), (9, 12), (12, 13), (13, 16), (16, 18), (18, 21), (21, 23)],
}


def _get_slot_key(dt: Optional[datetime] = None) -> str:
    """返回当前时间段 key，如 weekday_8_12"""
    now = dt or datetime.now()
    weekday = now.weekday()
    hour = now.hour

    if weekday == 5:
        slots = TIME_SLOTS["saturday"]
        prefix = "saturday"
    elif weekday == 6:
        slots = TIME_SLOTS["sunday"]
        prefix = "sunday"
    else:
        slots = TIME_SLOTS["weekday"]
        prefix = "weekday"

    for start, end in slots:
        if start <= hour < end:
            return f"{prefix}_{start}_{end}"
    return f"{prefix}_22_23"  # deep night fallback


def _get_day_type(dt: Optional[datetime] = None) -> str:
    now = dt or datetime.now()
    w = now.weekday()
    return "saturday" if w == 5 else "sunday" if w == 6 else "weekday"


class PokeReplyManager:
    """戳一戳回复管理器 — AI 生成 + 文件缓存"""

    def __init__(self, provider, data_dir: str = "emotions"):
        self._provider = provider
        self._path = os.path.join(data_dir, "poke_replies.json")
        self._cache: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()
        self._load()

    # ── 持久化 ────────────────────────────────────────────

    def _load(self):
        try:
            with open(self._path, encoding="utf-8") as f:
                self._cache = json.load(f)
                logger.info("戳一戳回复缓存加载: %d 个时间段", len(self._cache))
        except (FileNotFoundError, json.JSONDecodeError):
            self._cache = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    # ── 公开接口 ──────────────────────────────────────────

    async def get_reply(self, dt: Optional[datetime] = None) -> str:
        """获取一条戳一戳回复"""
        key = _get_slot_key(dt)
        async with self._lock:
            replies = self._cache.get(key, [])

        if not replies:
            logger.info("戳一戳缓存缺失 %s，调用 AI 生成...", key)
            replies = await self._generate(key, dt)
            async with self._lock:
                self._cache[key] = replies
                self._save()
            logger.info("戳一戳 %s 生成 %d 条回复", key, len(replies))

        reply = random.choice(replies)
        logger.debug("戳一戳回复 [%s]: %s", key, reply)
        return reply

    # ── AI 生成 ───────────────────────────────────────────

    async def _generate(self, key: str, dt: Optional[datetime] = None) -> list[str]:
        """调用 AI 生成该时间段的戳一戳回复"""
        activity = get_current_activity(dt)
        day_type = _get_day_type(dt)

        # 生成用 prompt
        prompt = (
            f"{TOUYA_SYSTEM_PROMPT}\n\n"
            f"现在需要你以青柳冬弥的身份，生成被对方戳了之后的回复。\n\n"
            f"{activity}\n\n"
            f"请生成 {REPLIES_PER_SLOT} 条不同的回复，要求：\n"
            f"1. 每条 1 句话，自然简短\n"
            f"2. 符合当前时间你正在做的事情\n"
            f"3. 语气符合冬弥的性格（礼貌、简洁、略带温柔）\n"
            f"4. 不要用表情符号\n"
            f"5. 直接输出 JSON 数组，如 [\"回复1\", \"回复2\", ...]\n"
            f"不要输出其他内容。"
        )

        try:
            text = await self._provider.chat(
                messages=[{"role": "user", "content": "请生成戳一戳回复。"}],
                system_prompt=prompt,
                max_tokens=500,
            )

            # 解析 JSON
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            replies = json.loads(text)
            if not isinstance(replies, list):
                raise ValueError("返回不是数组")
            replies = [r.strip() for r in replies if isinstance(r, str) and r.strip()]
            if not replies:
                raise ValueError("空数组")
            return replies[:REPLIES_PER_SLOT]

        except Exception as e:
            logger.warning("AI 生成戳一戳回复失败: %s，使用备用回复", e)
            return self._fallback_replies(day_type, key)

    # ── 备用 ──────────────────────────────────────────────

    @staticmethod
    def _fallback_replies(day_type: str, key: str) -> list[str]:
        """AI 失败时的备用回复"""
        common = [
            "……嗯？怎么了？",
            "……你戳我？",
            "有什么事吗？",
        ]
        if day_type == "weekday":
            return common + [
                "……我在上课。",
                "刚放学，准备去练习。",
                "在看书……嗯？",
            ]
        return common + [
            "今天休息……有什么事吗？",
            "在放松……怎么了？",
            "……我在听音乐。",
        ]
