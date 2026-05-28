"""SQLite 数据库存储 — 用于配置持久化、会话管理、日志"""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("autochat.db")


class Database:
    """SQLite 封装，支持便捷的 KV 存储 + 结构化表"""

    def __init__(self, db_path: str = "data/autochat.db"):
        self._path = db_path
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(self._path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
            self._init_tables()
        return self._local.conn

    def _init_tables(self):
        c = self.conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_session
            ON conversations(session_key)
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                platform TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY (platform, key)
            )
        """)
        self.conn.commit()

    # ---- KV ----
    def kv_get(self, key: str, default=None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def kv_set(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO kv_store(key, value) VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    # ---- 会话 ----
    def get_conversation(self, session_key: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM conversations WHERE session_key=? ORDER BY id DESC LIMIT ?",
            (session_key, limit),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def append_conversation(self, session_key: str, role: str, content: str):
        self.conn.execute(
            "INSERT INTO conversations(session_key, role, content) VALUES (?, ?, ?)",
            (session_key, role, content),
        )
        self.conn.commit()

    def clear_conversation(self, session_key: str):
        self.conn.execute("DELETE FROM conversations WHERE session_key=?", (session_key,))
        self.conn.commit()
