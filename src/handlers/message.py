import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger("autochat.handler")


class MessageHandler:
    """消息处理引擎 — 决定何时调用 AI 回复"""

    def __init__(self, config: dict, ai_provider):
        self.config = config
        self.ai = ai_provider
        self.bot_config = config.get("bot", {})
        self.enable_memory = self.bot_config.get("enable_memory", True)
        self.max_history = self.bot_config.get("max_history", 50)
        self.master_qq = self.bot_config.get("master_qq", 0)
        self.auto_reply_groups = self.bot_config.get("auto_reply_groups", [])
        self.auto_reply_private = self.bot_config.get("auto_reply_private", True)
        self.trigger_prefix = self.bot_config.get("trigger_prefix", "")
        self.trigger_at_mention = self.bot_config.get("trigger_at_mention", True)
        self.reply_prefix = self.bot_config.get("reply_prefix", "")
        self.nickname = self.bot_config.get("nickname", [])

        # 对话记忆 { "user_123": [{"role":..., "content":...}] }
        self.memories: dict[str, list[dict]] = {}

    def _get_memory_key(self, msg: dict) -> str:
        """生成记忆键名 — 按用户或群组"""
        if msg.get("message_type") == "group":
            return f'group_{msg["group_id"]}'
        return f'user_{msg["user_id"]}'

    def _load_memory(self, key: str):
        """从磁盘加载记忆"""
        if not self.enable_memory:
            return
        path = os.path.join("memory", f"{key}.json")
        try:
            with open(path, encoding="utf-8") as f:
                self.memories[key] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.memories[key] = []

    def _save_memory(self, key: str):
        """保存记忆到磁盘"""
        if not self.enable_memory:
            return
        path = os.path.join("memory", f"{key}.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.memories.get(key, []), f, ensure_ascii=False, indent=2)

    def _add_to_memory(self, key: str, role: str, content: str):
        """添加一条记忆"""
        if not self.enable_memory:
            return
        if key not in self.memories:
            self._load_memory(key)
        self.memories[key].append({"role": role, "content": content})
        if len(self.memories[key]) > self.max_history:
            self.memories[key] = self.memories[key][-self.max_history:]
        self._save_memory(key)

    def _should_reply(self, msg: dict) -> bool:
        """判断是否应该回复这条消息"""
        msg_type = msg.get("message_type")
        raw_msg = msg.get("raw_message", "")
        user_id = msg.get("user_id")
        self_id = msg.get("self_id")

        # 不回复自己的消息
        if user_id == self_id:
            return False

        if msg_type == "private":
            return self.auto_reply_private

        if msg_type == "group":
            group_id = msg.get("group_id")

            # 前缀触发
            if self.trigger_prefix and raw_msg.startswith(self.trigger_prefix):
                return True

            # @触发
            if self.trigger_at_mention:
                for seg in msg.get("message", []):
                    if seg.get("type") == "at" and seg.get("data", {}).get("qq") == str(self_id):
                        return True

            # 群白名单
            if group_id in self.auto_reply_groups:
                return True

            # 关键词昵称触发
            if self.nickname:
                for name in self.nickname:
                    if name in raw_msg:
                        return True

        return False

    def _clean_message(self, raw_msg: str, self_id: int) -> str:
        """清理消息中的 @ 和前缀"""
        msg = raw_msg
        # 去除 @自己
        import re
        msg = re.sub(rf"\[CQ:at,qq={self_id}\]", "", msg).strip()
        # 去除触发前缀
        if self.trigger_prefix and msg.startswith(self.trigger_prefix):
            msg = msg[len(self.trigger_prefix):].strip()
        return msg

    def _build_system_prompt(self, msg: dict) -> str:
        """构建系统提示词"""
        nickname = self.nickname[0] if self.nickname else "AI助手"
        return f"你是{nickname}，一个智能QQ机器人助手。请用中文回复，保持友好、有帮助的态度。"

    async def handle(self, msg: dict, send_func):
        """处理单条消息"""
        msg_type = msg.get("message_type")
        user_id = msg.get("user_id")
        raw_msg = msg.get("raw_message", "")
        self_id = msg.get("self_id", 0)

        if not self._should_reply(msg):
            return

        clean_msg = self._clean_message(raw_msg, self_id)
        if not clean_msg:
            return

        mem_key = self._get_memory_key(msg)
        logger.info("收到消息: [%s] %s", mem_key, clean_msg)

        # 记录用户消息
        self._add_to_memory(mem_key, "user", clean_msg)

        # 构建对话上下文
        if mem_key not in self.memories:
            self._load_memory(mem_key)

        try:
            system_prompt = self._build_system_prompt(msg)

            # 调用 AI
            reply = await self.ai.chat(
                messages=self.memories.get(mem_key, []),
                system_prompt=system_prompt,
            )

            if self.reply_prefix:
                reply = f"{self.reply_prefix}{reply}"

            # 记录AI回复
            self._add_to_memory(mem_key, "assistant", reply)

            # 发送回复
            if msg_type == "group":
                await send_func(message=reply, group_id=msg["group_id"])
            else:
                await send_func(message=reply, user_id=user_id)

            logger.info("回复 %s: %s", mem_key, reply[:100])

        except Exception as e:
            logger.error("AI 调用失败: %s", e)
            await send_func(
                message=f"AI 服务暂时不可用: {str(e)[:100]}",
                user_id=user_id if msg_type == "private" else None,
                group_id=msg.get("group_id") if msg_type == "group" else None,
            )
