"""情绪状态追踪器 — 追踪对话中的双方情绪并注入上下文"""

import json
import logging
import os
import re
from threading import Lock
from typing import Optional, Tuple

logger = logging.getLogger("autochat.emotion")

# 默认情绪状态
DEFAULT_EMOTION = {
    "user_mood": 0,        # -5~5 用户心情（负面→正面）
    "user_intensity": 3,   # 0~10 用户情绪强度
    "user_closeness": 2,   # 0~10 亲近度（陌生→亲近）
    "touya_mood": 1,       # -5~5 冬弥心情
    "touya_intensity": 2,  # 0~10 冬弥情绪强度
    "touya_closeness": 2,  # 0~10 冬弥对用户的亲近度
    "turn_count": 0,       # 对话轮次
}

# 情绪关键词
POSITIVE_WORDS = [
    "开心", "高兴", "喜欢", "棒", "厉害", "谢谢", "感谢", "好", "哈哈",
    "可爱", "帅", "好看", "不错", "厉害", "有意思", "有趣", "太好了",
    "嘻嘻", "嘿嘿", "www", "w", "笑", "开心", "兴奋", "感动",
]
NEGATIVE_WORDS = [
    "讨厌", "烦", "无聊", "没意思", "不好", "糟糕", "差", "生气", "怒",
    "伤心", "难过", "哭", "郁闷", "烦躁", "烦人", "可恶", "有病",
]
CLOSE_WORDS = [
    "朋友", "一起", "约", "想你了", "喜欢", "找你", "面基", "出来",
    "陪", "聊", "分享", "告诉", "信任",
]
INTENSE_WORDS = [
    "！！", "真的吗", "太", "超级", "特别", "非常", "完全",
    "!", "?", "？", "绝对", "一定",
]


class EmotionTracker:
    """情绪追踪器 — 分析消息 → 更新情绪 → 注入上下文"""

    def __init__(self, data_dir: str = "emotions"):
        self._data_dir = data_dir
        self._caches: dict[str, dict] = {}
        self._lock = Lock()

    def _path(self, key: str) -> str:
        return os.path.join(self._data_dir, f"{key}.json")

    def _load(self, key: str) -> dict:
        path = self._path(key)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return dict(DEFAULT_EMOTION)

    def _save(self, key: str, state: dict):
        os.makedirs(self._data_dir, exist_ok=True)
        path = self._path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def get(self, key: str) -> dict:
        with self._lock:
            if key not in self._caches:
                self._caches[key] = self._load(key)
            return dict(self._caches[key])

    def analyze_and_update(self, key: str, user_msg: str, touya_reply: str) -> dict:
        """分析用户消息和冬弥回复，更新情绪状态"""
        with self._lock:
            if key not in self._caches:
                self._caches[key] = self._load(key)
            state = self._caches[key]

            # 分析用户消息
            mood_delta = self._analyze_mood(user_msg)
            intensity_delta = self._analyze_intensity(user_msg)
            closeness_delta = self._analyze_closeness(user_msg)

            # 更新用户情绪
            state["user_mood"] = self._clamp(state["user_mood"] + mood_delta, -5, 5)
            state["user_intensity"] = self._clamp(state["user_intensity"] + intensity_delta, 0, 10)
            state["user_closeness"] = self._clamp(state["user_closeness"] + closeness_delta, 0, 10)

            # 用户情绪对冬弥情绪的自然影响
            state["touya_mood"] = self._clamp(
                state["touya_mood"] + mood_delta * 0.5 + (state["user_mood"] - state["touya_mood"]) * 0.1,
                -5, 5,
            )
            state["touya_closeness"] = self._clamp(
                state["touya_closeness"] + closeness_delta * 0.3,
                0, 10,
            )
            state["touya_intensity"] = self._clamp(
                state["touya_intensity"] + intensity_delta * 0.2,
                0, 10,
            )

            # 随时间自然回复
            state["user_intensity"] = self._clamp(state["user_intensity"] - 0.3, 0, 10)
            state["touya_intensity"] = self._clamp(state["touya_intensity"] - 0.2, 0, 10)

            state["turn_count"] += 1
            self._caches[key] = state
            self._save(key, state)
            return dict(state)

    def format_context(self, state: dict) -> str:
        """将情绪状态格式化为注入上下文的文本"""
        mood_map = {
            5: "非常开心", 4: "很开心", 3: "心情不错",
            2: "有点开心", 1: "还可以", 0: "普通",
            -1: "有点低落", -2: "不太好", -3: "心情差",
            -4: "很难过", -5: "非常糟糕",
        }
        close_map = {
            0: "陌生人", 1: "初次见面", 2: "刚认识",
            3: "有点熟", 4: "熟人", 5: "朋友",
            6: "好朋友", 7: "亲近的朋友", 8: "很亲近",
            9: "挚友", 10: "知己",
        }

        user_mood_str = mood_map.get(int(state["user_mood"]), "普通")
        touya_mood_str = mood_map.get(int(state["touya_mood"]), "普通")
        closeness_str = close_map.get(int(state["touya_closeness"]), "刚认识")
        intensity_str = "平静" if state["touya_intensity"] < 3 else "有点波动" if state["touya_intensity"] < 6 else "情绪强烈"

        return (
            f"【当前情绪状态】\n"
            f"对方的心情: {user_mood_str}（{'偏负面' if state['user_mood'] < 0 else '偏正面' if state['user_mood'] > 0 else '中性'}）\n"
            f"你的心情: {touya_mood_str}\n"
            f"你和对方的关系: {closeness_str}（第{state['turn_count']}次对话）\n"
            f"你的情绪强度: {intensity_str}\n"
            f"根据以上情绪状态自然地调整回应方式。"
        )

    def _analyze_mood(self, text: str) -> float:
        """分析文本情绪倾向，返回 mood delta"""
        text_lower = text.lower()
        pos = sum(1 for w in POSITIVE_WORDS if w in text)
        neg = sum(1 for w in NEGATIVE_WORDS if w in text)
        return (pos - neg) * 0.3

    def _analyze_intensity(self, text: str) -> float:
        """分析情绪强度"""
        excl = text.count("！") + text.count("!") + text.count("？") + text.count("?")
        intense = sum(1 for w in INTENSE_WORDS if w in text)
        length_bonus = min(len(text) / 50, 1)
        return (excl * 0.3 + intense * 0.2 + length_bonus * 0.5)

    def _analyze_closeness(self, text: str) -> float:
        """分析亲近度变化"""
        pos = sum(1 for w in CLOSE_WORDS if w in text)
        return pos * 0.3

    @staticmethod
    def _clamp(val, min_v, max_v):
        return max(min_v, min(max_v, val))

    def clear(self, key: str):
        with self._lock:
            self._caches.pop(key, None)
            path = self._path(key)
            if os.path.exists(path):
                os.remove(path)
