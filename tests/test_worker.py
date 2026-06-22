from memhub import worker, queue, db as db_mod, store


class StubCapturer:
    def __init__(self, items=None, fail=False):
        self.items, self.fail = items or [], fail

    def capture(self, transcript, meta):
        if self.fail:
            raise RuntimeError("boom")
        return self.items


def test_process_pending_stores_and_marks_done(conn):
    queue.enqueue(conn, {"transcript": "t", "project": "p1", "agent": "claude-code"})
    primary = StubCapturer(items=[{"content": "use JWT", "kind": "decision", "tags": [], "scope": "global"}])
    n = worker.process_pending(conn, primary=primary, fallback=StubCapturer(), capture_mode="llm")
    assert n == 1
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    assert queue.claim_pending(conn) == []  # marked done


def test_process_pending_falls_back_on_primary_failure(conn):
    queue.enqueue(conn, {"transcript": "raw text here", "project": "p1", "agent": "x"})
    primary = StubCapturer(fail=True)
    fallback = StubCapturer(items=[{"content": "raw text here", "kind": "raw", "tags": [], "scope": "current"}])
    worker.process_pending(conn, primary=primary, fallback=fallback, capture_mode="llm")
    assert conn.execute("SELECT count(*) FROM memories WHERE kind='raw'").fetchone()[0] == 1


def test_process_pending_marks_failed_when_both_fail(conn):
    qid = queue.enqueue(conn, {"transcript": "t", "project": "p1", "agent": "x"})
    worker.process_pending(conn, primary=StubCapturer(fail=True), fallback=StubCapturer(fail=True), capture_mode="llm")
    row = conn.execute("SELECT status FROM capture_queue WHERE id=?", (qid,)).fetchone()
    assert row[0] == "failed"
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0


def _boom(*a, **k):
    raise RuntimeError("store down")


def test_process_pending_survives_store_failure(conn, monkeypatch):
    queue.enqueue(conn, {"transcript": "t", "project": "p1", "agent": "x"})
    primary = StubCapturer(items=[{"content": "c", "kind": "fact", "tags": [], "scope": "current"}])
    monkeypatch.setattr(store, "store_memory", _boom)
    n = worker.process_pending(conn, primary=primary, fallback=StubCapturer(), capture_mode="llm")
    assert n == 0
    assert conn.execute("SELECT status FROM capture_queue").fetchone()[0] == "failed"


def test_run_loop_survives_bad_tick(tmp_path, monkeypatch):
    db_path = tmp_path / "loop.db"
    c = db_mod.connect(db_path); db_mod.init_schema(c)
    queue.enqueue(c, {"transcript": "t", "project": "p", "agent": "x"}); c.close()
    monkeypatch.setattr(store, "store_memory", _boom)
    ticks = {"n": 0}
    def stop():
        ticks["n"] += 1
        return ticks["n"] > 3
    primary = StubCapturer(items=[{"content": "c", "kind": "fact", "tags": [], "scope": "current"}])
    worker.run_loop(db_path, primary, StubCapturer(), interval=0, stop=stop, capture_mode="llm")  # interval=0 -> no real sleep
    assert ticks["n"] > 3  # loop survived multiple ticks despite store throwing


def test_process_pending_skips_empty_transcript(conn):
    queue.enqueue(conn, {"transcript": "   ", "project": "p", "agent": "x"})
    called = {"n": 0}
    class Spy:
        def capture(self, t, m):
            called["n"] += 1
            return []
    n = worker.process_pending(conn, primary=Spy(), fallback=Spy())
    assert called["n"] == 0  # capturer NOT called for empty transcript
    assert conn.execute("SELECT status FROM capture_queue").fetchone()[0] == "done"
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0


def test_process_pending_defaults_to_raw_mode(conn):
    queue.enqueue(conn, {"transcript": "raw only", "project": "p1", "agent": "x"})
    called = {"primary": 0}

    class Primary:
        def capture(self, transcript, meta):
            called["primary"] += 1
            return [{"content": "structured", "kind": "fact", "tags": [], "scope": "current"}]

    fallback = StubCapturer(items=[{"content": "raw only", "kind": "raw", "tags": [], "scope": "current"}])
    worker.process_pending(conn, primary=Primary(), fallback=fallback)
    assert called["primary"] == 0
    assert conn.execute("SELECT kind, content FROM memories").fetchone() == ("raw", "raw only")


def test_process_pending_off_discards_without_storing(conn):
    queue.enqueue(conn, {"transcript": "do not store", "project": "p1", "agent": "x"})
    n = worker.process_pending(conn, primary=StubCapturer(fail=True), fallback=StubCapturer(fail=True), capture_mode="off")
    assert n == 1
    assert conn.execute("SELECT status FROM capture_queue").fetchone()[0] == "done"
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
