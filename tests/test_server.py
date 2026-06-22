"""Server REST routes smoke tests (capture/search/health)."""
from starlette.testclient import TestClient
from memhub import server, db as db_mod


def _client(tmp_path):
    db_path = tmp_path / "srv.db"
    c = db_mod.connect(db_path)
    db_mod.init_schema(c)
    c.close()
    return TestClient(server.build_app(db_path)), db_path


def test_health_ok(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_capture_enqueues(tmp_path):
    client, db_path = _client(tmp_path)
    r = client.post("/capture", json={"transcript": "decided to use JWT", "project": "p1", "agent": "claude-code"})
    assert r.status_code == 200
    assert "queued" in r.json()
    conn = db_mod.connect(db_path)
    assert conn.execute("SELECT count(*) FROM capture_queue WHERE status='pending'").fetchone()[0] == 1
    conn.close()


def test_capture_malformed_json_returns_400(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/capture", content="not json")
    assert r.status_code == 400


def test_search_bad_limit_returns_400(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/search", params={"query": "x", "limit": "abc"})
    assert r.status_code == 400


def test_capture_skips_self_referential(tmp_path):
    # a transcript containing memhub's own extraction prompt is feedback-loop
    # noise (or a session that pasted the prompt) — it must not be enqueued.
    from memhub.capture import _EXTRACT_PROMPT
    client, db_path = _client(tmp_path)
    r = client.post("/capture", json={"transcript": f"user: {_EXTRACT_PROMPT}",
                                       "project": "p", "agent": "claude-code"})
    assert r.status_code == 200
    conn = db_mod.connect(db_path)
    pending = conn.execute("SELECT count(*) FROM capture_queue WHERE status='pending'").fetchone()[0]
    conn.close()
    assert pending == 0
