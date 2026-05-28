"""统一消息事件模型 — 各平台消息统一封装"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MessageType(Enum):
    PRIVATE = "private"
    GROUP = "group"
    OTHER = "other"


@dataclass
class MessageEvent:
    """统一消息事件 — 各平台适配器需将原始消息转为该格式"""

    platform_name: str  # "napcat" | "telegram" | ...
    platform_id: str  # 平台实例标识
    message_type: MessageType
    message: str  # 纯文本内容
    raw_message: str  # 原始消息
    user_id: str
    group_id: Optional[str] = None
    sender_name: str = ""
    self_id: str = ""
    message_id: str = ""
    timestamp: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def session_key(self) -> str:
        """用于记忆存储的会话键"""
        if self.message_type == MessageType.GROUP and self.group_id:
            return f"group_{self.group_id}"
        return f"user_{self.user_id}"

    @property
    def is_group(self) -> bool:
        return self.message_type == MessageType.GROUP

    @property
    def is_private(self) -> bool:
        return self.message_type == MessageType.PRIVATE

    def reply(self, text: str) -> dict:
        """构建回复参数"""
        if self.is_group:
            return {"message": text, "group_id": int(self.group_id)}
        return {"message": text, "user_id": int(self.user_id)}
