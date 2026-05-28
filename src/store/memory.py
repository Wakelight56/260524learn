"""对话记忆存储 — JSON 文件持久化（轻量，后续可切换 SQLite）"""

import json
import logging
import os
from threading import Lock

logger = logging.getLogger("autochat.memory")


class MemoryStore:
    """对话记忆管理器 — 按用户/群组隔离，LRU 淘汰"""

    def __init__(self, data_dir: str = "memory", max_history: int = 50):
        self._data_dir = data_dir
        self._max_history = max_history
        self._caches: dict[str, list[dict]] = {}
        self._lock = Lock()

    def _path(self, key: str) -> str:
        return os.path.join(self._data_dir, f"{key}.json")

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

    def get(self, key: str) -> list[dict]:
        with self._lock:
            if key not in self._caches:
                self._caches[key] = self._load(key)
            return list(self._caches[key])

    def append(self, key: str, role: str, content: str):
        with self._lock:
            if key not in self._caches:
                self._caches[key] = self._load(key)
            msgs = self._caches[key]
            msgs.append({"role": role, "content": content})
            if len(msgs) > self._max_history:
                msgs = msgs[-self._max_history:]
            self._caches[key] = msgs
            self._save(key, msgs)

    def clear(self, key: str):
        with self._lock:
            self._caches.pop(key, None)
            path = self._path(key)
            if os.path.exists(path):
                os.remove(path)

    def clear_all(self):
        with self._lock:
            self._caches.clear()
            for f in os.listdir(self._data_dir):
                if f.endswith(".json"):
                    os.remove(os.path.join(self._data_dir, f))
