import json
from memhub import queue


def test_enqueue_then_claim(conn):
    qid = queue.enqueue(conn, {"transcript": "hello", "project": "p1"})
    pending = queue.claim_pending(conn, limit=10)
    assert len(pending) == 1
    assert pending[0][0] == qid
    assert json.loads(pending[0][1])["transcript"] == "hello"


def test_mark_done_removes_from_pending(conn):
    qid = queue.enqueue(conn, {"transcript": "x"})
    queue.mark_done(conn, qid)
    assert queue.claim_pending(conn, limit=10) == []


def test_mark_failed_increments_attempts(conn):
    qid = queue.enqueue(conn, {"transcript": "x"})
    queue.mark_failed(conn, qid)
    row = conn.execute(
        "SELECT status, attempts FROM capture_queue WHERE id=?", (qid,)
    ).fetchone()
    assert row[0] == "failed"
    assert row[1] == 1
