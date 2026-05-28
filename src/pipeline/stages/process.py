"""AI 处理阶段 — 调用 LLM 生成回复"""

import logging
from typing import Optional

from src.emotion.tracker import EmotionTracker
from src.knowledge.character import SYSTEM_PROMPT as TOUYA_SYSTEM_PROMPT
from src.knowledge.retriever import StoryRetriever
from src.knowledge.schedule import get_current_activity
from src.pipeline.stage import Stage, StageContext

logger = logging.getLogger("autochat.stage.process")


class AIProcessStage(Stage):
    """核心AI处理：组装上下文 → 调用 LLM → 取回复"""

    def __init__(self, provider, memory_store, config: dict, retriever: Optional[StoryRetriever] = None,
                 emotion_tracker: Optional[EmotionTracker] = None):
        self._provider = provider
        self._memory = memory_store
        self._retriever = retriever
        self._emotion = emotion_tracker
        bot_cfg = config.get("bot", {})
        self._enable_memory = bot_cfg.get("enable_memory", True)
        self._reply_prefix = bot_cfg.get("reply_prefix", "")

    async def process(self, ctx: StageContext):
        event = ctx.event
        msg = ctx.extra.get("cleaned_message") or event.message

        if not msg:
            ctx.should_stop = True
            return

        # 记录用户消息
        if self._enable_memory:
            self._memory.append(event.session_key, "user", msg)

        # 组装上下文
        messages = []
        if self._enable_memory:
            messages = self._memory.get(event.session_key)

        # 角色 system prompt
        system_prompt = TOUYA_SYSTEM_PROMPT

        # 注入情绪上下文
        if self._emotion:
            emotion_state = self._emotion.get(event.session_key)
            emotion_context = self._emotion.format_context(emotion_state)
            system_prompt = f"{system_prompt}\n\n{emotion_context}"
            logger.debug("情绪注入: mood=%d closeness=%d",
                         emotion_state["touya_mood"], emotion_state["touya_closeness"])

        # 注入当前行程上下文
        schedule_context = get_current_activity()
        system_prompt = f"{system_prompt}\n\n{schedule_context}"

        # 检索相关剧情知识并注入
        if self._retriever and self._retriever.size > 0:
            results = self._retriever.search(msg, top_k=3)
            if results:
                knowledge_context = self._retriever.format_context(results)
                system_prompt = f"{system_prompt}\n\n{knowledge_context}"
                logger.info("为消息 '%s' 检索到 %d 条相关剧情", msg[:30], len(results))

        logger.info("调用 AI 前: msg=%s", msg[:50])
        try:
            reply = await self._provider.chat(messages=messages, system_prompt=system_prompt)

            if self._reply_prefix:
                reply = f"{self._reply_prefix}{reply}"

            # 记录 AI 回复
            if self._enable_memory:
                self._memory.append(event.session_key, "assistant", reply)

            # 更新情绪状态
            if self._emotion:
                self._emotion.analyze_and_update(event.session_key, msg, reply)

            ctx.reply = reply
            logger.info("回复 [%s]: %s", event.session_key, reply[:80])

        except Exception as e:
            logger.error("AI 调用失败: %s", e)
            ctx.reply = f"AI 服务暂时不可用，请稍后再试。"
