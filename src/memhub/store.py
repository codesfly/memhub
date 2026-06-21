"""Write path: redact -> dedupe -> embed -> insert into 3 tables."""
import hashlib
import json
import struct
import time
import sqlite3

from . import embedding
from .redact import redact


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _pack(vec: list[float]) -> bytes:
    return struct.pack("%sf" % len(vec), *vec)


def store_memory(
    conn: sqlite3.Connection,
    content: str,
    project: str | None = None,
    agent: str | None = None,
    kind: str = "raw",
    tags: list[str] | None = None,
    scope: str = "current",
    session_id: str | None = None,
) -> int | None:
    content = redact(content)
    if not content.strip():
        return None
    h = _hash(content)
    existing = conn.execute("SELECT id FROM memories WHERE content_hash=?", (h,)).fetchone()
    if existing:
        return existing[0]

    cur = conn.execute(
        """INSERT INTO memories (content, content_hash, kind, project, agent, tags, scope, session_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (content, h, kind, project, agent, json.dumps(tags or []), scope, session_id, int(time.time())),
    )
    mid = cur.lastrowid
    conn.execute(
        "INSERT INTO memories_vec(memory_id, embedding) VALUES (?, ?)",
        (mid, _pack(embedding.embed(content))),
    )
    conn.execute("INSERT INTO memories_fts(rowid, content) VALUES (?, ?)", (mid, content))
    conn.commit()
    return mid
