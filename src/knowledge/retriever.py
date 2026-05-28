"""轻量知识库检索器 — 多语言剧情检索"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger("autochat.knowledge.retriever")

# 各语言停用字/词
STOP_WORDS_CN = {
    "一个", "什么", "这个", "那个", "可以", "没有", "我们",
    "自己", "知道", "时候", "这么", "怎么", "还是", "就是",
    "因为", "已经", "但是", "不是", "如果", "虽然", "所以",
    "不过", "然后", "而且", "非常", "一下", "可能", "大家",
}

STOP_WORDS_EN = {
    "the", "and", "for", "that", "this", "with", "was",
    "are", "but", "not", "you", "all", "can", "have",
    "has", "had", "its", "just", "like", "what", "were",
    "will", "your", "been", "been", "they", "from", "them",
}

STOP_WORDS_JP = {
    "だっ", "ない", "いる", "する", "いう", "ある",
    "これ", "それ", "ため", "こと", "もの", "さん",
    "なる", "れる", "できる", "よう", "また", "から",
    "べき", "まま", "でも", "だから", "なので",
}


class StoryRetriever:
    """多语言剧情知识库检索器。

    支持中文/日文/英文混合检索，基于关键字匹配。
    """

    def __init__(self, kb_path: str = ""):
        self._entries: list[dict] = []
        if kb_path:
            self.load(kb_path)

    def load(self, kb_path: str):
        try:
            with open(kb_path, encoding="utf-8") as f:
                self._entries = json.load(f)
            lang_count = {}
            # 预计算所有条目的搜索 token，避免每次搜索都重新分词
            for e in self._entries:
                lang = e.get("language", "?")
                lang_count[lang] = lang_count.get(lang, 0) + 1
                search_text = e.get("_search_text", "")
                e["_tokens"] = self._tokenize_multilingual(search_text)
                touya_text = " ".join(e.get("touya_lines", []))
                e["_touya_tokens"] = self._tokenize_multilingual(touya_text)
                e["_title_tokens"] = self._tokenize_multilingual(e.get("title", ""))
            logger.info(
                "知识库加载完成: %d 条故事, 语言分布: %s",
                len(self._entries), lang_count,
            )
        except FileNotFoundError:
            logger.warning("知识库文件不存在: %s", kb_path)
        except json.JSONDecodeError as e:
            logger.error("知识库解析失败: %s", e)

    @property
    def size(self) -> int:
        return len(self._entries)

    def search(self, query: str, top_k: int = 3, lang_filter: Optional[str] = None) -> list[dict]:
        """搜索与查询最相关的故事条目。

        Args:
            query: 用户消息（任意语言）
            top_k: 返回结果数
            lang_filter: 可选语言过滤 "cn"/"jp"/"en"

        Returns:
            匹配故事条目列表
        """
        if not self._entries:
            return []

        query_tokens = self._tokenize_multilingual(query)
        if not query_tokens:
            return []

        entries = self._entries
        if lang_filter:
            entries = [e for e in entries if e.get("language") == lang_filter]

        scored = []
        for entry in entries:
            score = self._score(entry, query_tokens)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: -x[0])
        results = scored[:top_k]

        # 去掉内部字段
        cleaned = []
        for score, entry in results:
            e = {k: v for k, v in entry.items() if not k.startswith("_")}
            e["_score"] = round(score, 3)
            cleaned.append(e)

        return cleaned

    def format_context(self, results: list[dict], max_lines: int = 12) -> str:
        """将检索结果格式化为 AI 上下文文本。"""
        if not results:
            return ""

        lang_label = {"cn": "中文", "jp": "日文", "en": "英文"}
        parts = ["【以下是你过往经历中的相关记忆】"]

        for i, r in enumerate(results, 1):
            title = r.get("title", "未知剧情")
            lang = r.get("language", "?")
            label = lang_label.get(lang, lang)
            scenes = r.get("scenes", [])

            part = f"\n--- 记忆 {i} [{label}] ---"
            if r.get("characters"):
                part += f"\n出场: {'、'.join(r['characters'][:6])}"

            line_count = 0
            for scene in scenes:
                if line_count >= max_lines:
                    break
                scene_lines = scene.get("dialogue", [])
                for d in scene_lines:
                    if line_count >= max_lines:
                        break
                    part += f"\n{d['speaker']}: {d['text']}"
                    line_count += 1

            parts.append(part)

        parts.append("\n【以上记忆可以帮助你更好地回应】")
        return "\n".join(parts)

    def _tokenize_multilingual(self, text: str) -> set[str]:
        """多语言分词。
        - 中文: 单字 + 双字组
        - 英文: 单词
        - 日文: 假名/汉字单字 + 双字组
        - 数字
        """
        tokens = set()

        # 英文单词
        en_words = re.findall(r"[a-zA-Z]{2,}", text)
        for w in en_words:
            tokens.add(w.lower())

        # 中日文字符（汉字 + 假名）
        cjk_chars = re.findall(r"[一-鿿ぁ-んァ-ン]", text)

        # 单字
        for ch in cjk_chars:
            tokens.add(ch)

        # 双字组
        for i in range(len(cjk_chars) - 1):
            tokens.add(cjk_chars[i] + cjk_chars[i+1])

        # 数字
        nums = re.findall(r"\d+", text)
        for n in nums:
            tokens.add(n)

        return tokens

    def _score(self, entry: dict, query_tokens: set[str]) -> float:
        """计算条目与查询的多语言匹配得分（使用预计算 token）。"""
        entry_tokens = entry.get("_tokens") or self._tokenize_multilingual(
            entry.get("_search_text", "")
        )
        if not entry_tokens:
            return 0.0

        intersection = query_tokens & entry_tokens
        if not intersection:
            return 0.0

        base_score = len(intersection)

        touya_tokens = entry.get("_touya_tokens") or set()
        touya_overlap = len(query_tokens & touya_tokens)
        base_score += touya_overlap * 1.5

        title_tokens = entry.get("_title_tokens") or set()
        title_overlap = len(query_tokens & title_tokens)
        base_score += title_overlap * 2.0

        return base_score
