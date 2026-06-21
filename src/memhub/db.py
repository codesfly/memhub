"""SQLite connection + sqlite-vec loading + schema."""
import sqlite3
from pathlib import Path

import sqlite_vec

from . import config


def connect(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY,
        content TEXT NOT NULL,
        content_hash TEXT UNIQUE NOT NULL,
        kind TEXT NOT NULL DEFAULT 'raw',
        project TEXT,
        agent TEXT,
        tags TEXT DEFAULT '[]',
        scope TEXT NOT NULL DEFAULT 'current',
        session_id TEXT,
        created_at INTEGER NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
        memory_id INTEGER PRIMARY KEY,
        embedding float[{config.EMBED_DIM}]
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        content, tokenize='porter unicode61'
    );
    CREATE TABLE IF NOT EXISTS capture_queue (
        id INTEGER PRIMARY KEY,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    );
    """)
    conn.commit()
