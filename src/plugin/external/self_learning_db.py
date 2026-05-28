"""自学习 SQLite 数据库 — 存储对话消息"""
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autochat.plugin.external.self_learning.db")

DB_PATH = Path("data/self_learning/messages.db")


class MessageDB:
    """SQLite 消息数据库（线程安全）"""

    def __init__(self, db_path: str | Path = None):
        self._path = Path(db_path or DB_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        """每个线程独立的连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_db(self):
        conn = sqlite3.connect(str(self._path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT DEFAULT '',
                message TEXT NOT NULL,
                timestamp REAL NOT NULL,
                platform TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_msgs_group_time
                ON messages(group_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_msgs_time
                ON messages(timestamp DESC);
        """)
        conn.commit()
        conn.close()

    def save_message(self, group_id: str, user_id: str, message: str,
                     user_name: str = "", platform: str = ""):
        """保存一条消息"""
        self._conn.execute(
            "INSERT INTO messages (group_id, user_id, user_name, message, timestamp, platform) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (group_id, user_id, user_name, message, time.time(), platform),
        )
        self._conn.commit()

    def get_recent_messages(self, group_id: str, limit: int = 20,
                            exclude_user_id: Optional[str] = None) -> list[dict]:
        """获取某个群最近的 N 条消息"""
        if exclude_user_id:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE group_id=? AND user_id!=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (group_id, exclude_user_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE group_id=? "
                "ORDER BY timestamp DESC LIMIT ?",
                (group_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_global_recent_messages(self, limit: int = 50) -> list[dict]:
        """全局最近消息（用于私聊时补充上下文）"""
        rows = self._conn.execute(
            "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_message_count(self, group_id: Optional[str] = None) -> int:
        """获取消息总数"""
        if group_id:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE group_id=?", (group_id,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()
        return row["cnt"] if row else 0

    def get_group_ids(self) -> list[str]:
        """获取有消息的所有群号"""
        rows = self._conn.execute(
            "SELECT DISTINCT group_id FROM messages ORDER BY group_id"
        ).fetchall()
        return [r["group_id"] for r in rows]

    def clear_all(self):
        """清空所有消息"""
        self._conn.execute("DELETE FROM messages")
        self._conn.commit()

    def clear_group(self, group_id: str):
        """清空指定群的消息"""
        self._conn.execute("DELETE FROM messages WHERE group_id=?", (group_id,))
        self._conn.commit()

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    @property
    def total_messages(self) -> int:
        return self.get_message_count()


# 全局单例
_db_instance: Optional[MessageDB] = None


def get_db() -> MessageDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = MessageDB()
    return _db_instance


def build_recent_context(group_id: Optional[str], limit: int = 10) -> str:
    """构建近期聊天上下文文本，供 AI 注入"""
    db = get_db()
    if group_id:
        msgs = db.get_recent_messages(group_id, limit=limit)
    else:
        msgs = db.get_global_recent_messages(limit=limit)

    if not msgs:
        return ""

    lines = []
    for m in msgs:
        name = m.get("user_name") or m.get("user_id", "unknown")
        text = m["message"][:200]
        lines.append(f"{name}: {text}")

    return "## 近期群聊动态\n" + "\n".join(lines)
