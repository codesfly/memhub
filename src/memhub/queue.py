"""capture_queue operations."""
import json
import sqlite3
import time


def enqueue(conn: sqlite3.Connection, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO capture_queue (payload, status, created_at) VALUES (?, 'pending', ?)",
        (json.dumps(payload), int(time.time())),
    )
    conn.commit()
    return cur.lastrowid


def claim_pending(conn: sqlite3.Connection, limit: int = 10) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT id, payload FROM capture_queue WHERE status='pending' ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def delete(conn: sqlite3.Connection, qid: int) -> None:
    """Remove a fully-processed item. Done rows are never read back, and each carries
    the full transcript payload, so keeping them would grow capture_queue unbounded."""
    conn.execute("DELETE FROM capture_queue WHERE id=?", (qid,))
    conn.commit()


def mark_failed(conn: sqlite3.Connection, qid: int) -> None:
    conn.execute(
        "UPDATE capture_queue SET status='failed', attempts=attempts+1 WHERE id=?",
        (qid,),
    )
    conn.commit()


def clear_pending(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM capture_queue WHERE status='pending'")
    conn.commit()
    return cur.rowcount


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, count(*) FROM capture_queue GROUP BY status").fetchall()
    out = {"pending": 0, "done": 0, "failed": 0}
    out.update({r[0]: r[1] for r in rows})
    return out
