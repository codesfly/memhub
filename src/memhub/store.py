"""Write path: redact -> dedupe -> embed -> insert into 3 tables."""
import hashlib
import json
import struct
import time
import sqlite3

from . import embedding, config
from .redact import redact


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _pack(vec: list[float]) -> bytes:
    return struct.pack("%sf" % len(vec), *vec)


def _near_duplicate(conn: sqlite3.Connection, vec: list[float], project: str | None) -> int | None:
    """id of an existing SAME-PROJECT memory within DEDUP_L2_MAX of `vec`, else None.

    Same-project scope + a tight threshold keep this from merging contradictions:
    opposite-meaning text scores ~0.88 cosine (L2 ~0.49), well above DEDUP_L2_MAX.
    """
    rows = conn.execute(
        "SELECT memory_id, distance FROM memories_vec WHERE embedding MATCH ? ORDER BY distance LIMIT 5",
        (_pack(vec),),
    ).fetchall()
    for mid, dist in rows:
        if dist > config.DEDUP_L2_MAX:
            break  # ascending distance — nothing closer remains
        row = conn.execute("SELECT project FROM memories WHERE id=?", (mid,)).fetchone()
        if row and row[0] == project:
            return mid
    return None


def store_memory(
    conn: sqlite3.Connection,
    content: str,
    project: str | None = None,
    agent: str | None = None,
    kind: str = "raw",
    tags: list[str] | None = None,
    scope: str = "current",
    session_id: str | None = None,
    dedup: bool = True,
) -> int | None:
    content = redact(content)
    if not content.strip():
        return None
    h = _hash(content)
    existing = conn.execute("SELECT id FROM memories WHERE content_hash=?", (h,)).fetchone()
    if existing:
        return existing[0]

    vec = embedding.embed(content)
    if dedup:
        dup = _near_duplicate(conn, vec, project)
        if dup is not None:
            return dup

    cur = conn.execute(
        """INSERT INTO memories (content, content_hash, kind, project, agent, tags, scope, session_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (content, h, kind, project, agent, json.dumps(tags or []), scope, session_id, int(time.time())),
    )
    mid = cur.lastrowid
    conn.execute(
        "INSERT INTO memories_vec(memory_id, embedding) VALUES (?, ?)",
        (mid, _pack(vec)),
    )
    conn.execute("INSERT INTO memories_fts(rowid, content) VALUES (?, ?)", (mid, content))
    conn.commit()
    return mid


def list_memories(conn, project=None, kind=None, limit=50, offset=0):
    # Management view: intentionally unscoped (lists across ALL projects),
    # unlike search.py's fail-closed scope model. Local single-user tool.
    limit = max(1, min(int(limit), 500))   # clamp: avoid ?limit=-1 dumping the table
    offset = max(0, int(offset))
    conds, params = [], []
    if project:
        conds.append("project = ?"); params.append(project)
    if kind:
        conds.append("kind = ?"); params.append(kind)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql = (f"SELECT id, content, kind, project, agent, scope, created_at "
           f"FROM memories{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?")
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    return [{"id": r[0], "content": r[1], "kind": r[2], "project": r[3],
             "agent": r[4], "scope": r[5], "created_at": r[6]} for r in rows]


def delete_memory(conn, mid) -> bool:
    cur = conn.execute("DELETE FROM memories WHERE id=?", (mid,))
    conn.execute("DELETE FROM memories_vec WHERE memory_id=?", (mid,))
    conn.execute("DELETE FROM memories_fts WHERE rowid=?", (mid,))
    conn.commit()
    return cur.rowcount > 0
