"""对话记忆存储 — JSON 持久化 + 记忆消退 + 过期清理"""

import json
import logging
import os
import time
from threading import Lock

logger = logging.getLogger("autochat.memory")

SUMMARY_MAX_LEN = 600


class MemoryStore:
    """对话记忆管理器 — 按用户/群组隔离，支持记忆消退"""

    def __init__(self, data_dir: str = "memory", max_history: int = 50):
        self._data_dir = data_dir
        self._max_history = max_history
        self._hot_size = max(10, max_history // 2)  # 保留完整内容的消息数
        self._caches: dict[str, list[dict]] = {}
        self._summaries: dict[str, str] = {}
        self._lock = Lock()

    # ── 路径 ──────────────────────────────────────────────

    def _path(self, key: str) -> str:
        return os.path.join(self._data_dir, f"{key}.json")

    def _summary_path(self, key: str) -> str:
        return os.path.join(self._data_dir, f"{key}_summary.json")

    # ── 持久化 ────────────────────────────────────────────

    def _load(self, key: str) -> list[dict]:
        path = self._path(key)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self, key: str, msgs: list[dict]):
        os.makedirs(self._data_dir, exist_ok=True)
        path = self._path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False, indent=2)

    def _load_summary(self, key: str) -> str:
        path = self._summary_path(key)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                return data.get("summary", "")
        except (FileNotFoundError, json.JSONDecodeError):
            return ""

    def _save_summary(self, key: str, summary: str):
        os.makedirs(self._data_dir, exist_ok=True)
        path = self._summary_path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "updated_at": time.time()},
                      f, ensure_ascii=False, indent=2)

    # ── 加载（带缓存）─────────────────────────────────────

    def _ensure_loaded(self, key: str):
        """确保会话已加载到缓存"""
        if key not in self._caches:
            self._caches[key] = self._load(key)
            self._summaries[key] = self._load_summary(key)

    # ── 公开接口 ──────────────────────────────────────────

    def get(self, key: str) -> list[dict]:
        """获取会话消息（含摘要）"""
        with self._lock:
            self._ensure_loaded(key)
            msgs = list(self._caches[key])
            summary = self._summaries.get(key, "")

        if summary:
            return [{"role": "system", "content": f"[过去的对话摘要] {summary}"}] + msgs
        return msgs

    def append(self, key: str, role: str, content: str):
        """追加一条消息，超出上限时自动压缩旧消息"""
        with self._lock:
            self._ensure_loaded(key)
            msgs = self._caches[key]
            msgs.append({
                "role": role,
                "content": content,
                "timestamp": time.time(),
            })

            if len(msgs) > self._max_history:
                self._summarize_session(key)

            self._save(key, self._caches[key])

    def get_last_active(self, key: str) -> float:
        """获取会话最后活跃时间戳"""
        with self._lock:
            self._ensure_loaded(key)
            msgs = self._caches[key]
            if not msgs:
                return 0
            return msgs[-1].get("timestamp", 0)

    # ── 记忆消退 ──────────────────────────────────────────

    def _summarize_session(self, key: str):
        """将最旧的{max_history - hot_size}条消息压缩成摘要"""
        msgs = self._caches[key]
        existing = self._summaries.get(key, "")

        # 保留最近 hot_size 条，其余压缩
        to_compress = msgs[:-self._hot_size]
        msgs = msgs[-self._hot_size:]

        compressed = self._compress_messages(to_compress, existing)

        self._summaries[key] = compressed
        self._caches[key] = msgs
        self._save_summary(key, compressed)
        logger.info("记忆消退: %s 压缩了 %d 条消息", key, len(to_compress))

    def _compress_messages(self, msgs: list[dict], existing_summary: str) -> str:
        """文本级压缩：提取关键信息，限制总长度"""
        # 提取最近几个轮次的关键信息
        lines = []
        for m in msgs[-8:]:  # 只看最后 8 条
            label = "用户" if m["role"] == "user" else "冬弥"
            content = m["content"].strip()[:60]
            lines.append(f"{label}: {content}")

        new_part = " | ".join(lines)

        if existing_summary:
            combined = f"{existing_summary} | {new_part}"
        else:
            combined = f"过去的对话: {new_part}"

        # 限制总长度，保留结尾（最新信息）
        if len(combined) > SUMMARY_MAX_LEN:
            combined = "…" + combined[-(SUMMARY_MAX_LEN - 1):]

        return combined

    # ── 过期清理 ──────────────────────────────────────────

    def cleanup_stale_sessions(self, inactive_days: int = 7) -> int:
        """删除超过指定天数未活跃的会话，返回清理数"""
        now = time.time()
        cutoff = now - (inactive_days * 86400)
        cleaned = 0

        with self._lock:
            for f in os.listdir(self._data_dir):
                if not f.endswith(".json") or f.endswith("_summary.json"):
                    continue
                path = os.path.join(self._data_dir, f)
                try:
                    mtime = os.path.getmtime(path)
                    if mtime < cutoff:
                        key = f[:-5]
                        os.remove(path)

                        spath = os.path.join(self._data_dir, f"{key}_summary.json")
                        if os.path.exists(spath):
                            os.remove(spath)

                        self._caches.pop(key, None)
                        self._summaries.pop(key, None)
                        cleaned += 1
                except Exception:
                    continue

        if cleaned:
            logger.info("过期清理: 删除了 %d 个会话（%d 天未活跃）", cleaned, inactive_days)
        return cleaned

    # ── 清空 ──────────────────────────────────────────────

    def clear(self, key: str):
        """清空指定会话"""
        with self._lock:
            self._caches.pop(key, None)
            self._summaries.pop(key, None)
            path = self._path(key)
            if os.path.exists(path):
                os.remove(path)
            spath = self._summary_path(key)
            if os.path.exists(spath):
                os.remove(spath)

    def clear_all(self):
        """清空所有会话"""
        with self._lock:
            self._caches.clear()
            self._summaries.clear()
            for f in os.listdir(self._data_dir):
                if f.endswith(".json"):
                    os.remove(os.path.join(self._data_dir, f))
