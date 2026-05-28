"""AI 处理阶段 — 调用 LLM 生成回复"""

import logging
import re
from typing import Optional

from src.emotion.tracker import EmotionTracker
from src.knowledge.character import SYSTEM_PROMPT as TOUYA_SYSTEM_PROMPT
from src.knowledge.retriever import StoryRetriever
from src.knowledge.schedule import get_current_activity
from src.knowledge.searcher import extract_query, web_search
from src.pipeline.stage import Stage, StageContext
from src.plugin.external.self_learning_db import build_recent_context

logger = logging.getLogger("autochat.stage.process")

# 去掉 CQ 码，避免把图片代码发给 AI
CQ_TAG_RE = re.compile(r"\[CQ:\S+?\]")


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

    def _build_scene_context(self, event) -> str:
        """根据私聊/群聊构建场景上下文"""
        if event.is_private:
            return (
                "## 当前场景\n"
                "你正在和主人进行私聊（只有你们两人的对话），可以放松一些，\n"
                "话题可以更私人、更随意。"
            )
        if event.is_group:
            group_id = event.group_id or "未知"
            return (
                "## 当前场景\n"
                f"你正在群聊（群号 {group_id}）中说话，群里有其他人，\n"
                "注意保持适当的社交距离，不要说太私密的话。"
            )
        return ""

    async def process(self, ctx: StageContext):
        event = ctx.event
        msg = ctx.extra.get("cleaned_message") or event.message

        # 去掉 CQ 码，AI 看不到图片
        clean_msg = CQ_TAG_RE.sub("", msg).strip()

        if not clean_msg:
            ctx.should_stop = True
            return

        # 记录用户消息
        if self._enable_memory:
            self._memory.append(event.session_key, "user", clean_msg)

        # 组装上下文
        messages = []
        if self._enable_memory:
            messages = self._memory.get(event.session_key)
            # 清理历史消息中的 CQ 码
            for m in messages:
                if "content" in m:
                    m["content"] = CQ_TAG_RE.sub("", m["content"]).strip()

        # 注入对话场景上下文
        scene_context = self._build_scene_context(event)
        system_prompt = f"{TOUYA_SYSTEM_PROMPT}\n\n{scene_context}"

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

        # 检索相关剧情知识并注入（仅对非闲聊消息检索，节省时间）
        if self._retriever and self._retriever.size > 0 and len(clean_msg) > 2:
            results = self._retriever.search(clean_msg, top_k=3)
            if results:
                knowledge_context = self._retriever.format_context(results)
                system_prompt = f"{system_prompt}\n\n{knowledge_context}"
                logger.info("为消息 '%s' 检索到 %d 条相关剧情", clean_msg[:30], len(results))

        # 注入近期群聊上下文（让 AI 了解当前话题）
        recent_context = build_recent_context(
            event.group_id if event.is_group else None,
            limit=8,
        )
        if recent_context:
            system_prompt = f"{system_prompt}\n\n{recent_context}"
            logger.debug("近期对话上下文已注入")

        # 网络搜索："xxx是什么" 类问题自动搜索
        search_query = extract_query(clean_msg)
        if search_query:
            logger.info("检测到搜索查询: %s", search_query)
            search_result = await web_search(search_query)
            if search_result:
                system_prompt = f"{system_prompt}\n\n{search_result}"
                logger.info("网络搜索结果已注入")

        logger.info("调用 AI 前: msg=%s", clean_msg[:50])
        try:
            reply = await self._provider.chat(messages=messages, system_prompt=system_prompt)

            if self._reply_prefix:
                reply = f"{self._reply_prefix}{reply}"

            # 记录 AI 回复
            if self._enable_memory:
                self._memory.append(event.session_key, "assistant", reply)

            # 更新情绪状态
            if self._emotion:
                self._emotion.analyze_and_update(event.session_key, clean_msg, reply)

            if not reply:
                reply = "……嗯。"
                logger.warning("AI 回复为空，使用默认回复")
            ctx.reply = reply
            logger.info("回复 [%s]: %s", event.session_key, reply[:80])

        except Exception as e:
            logger.error("AI 调用失败: %s", e)
            ctx.reply = f"AI 服务暂时不可用，请稍后再试。"
