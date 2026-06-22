"""Server REST routes smoke tests (capture/search/health)."""
from starlette.testclient import TestClient
from memhub import server, db as db_mod, queue


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


def test_capture_skips_when_capture_mode_off(tmp_path):
    client, db_path = _client(tmp_path)
    assert client.patch("/settings", json={"capture_mode": "off"}).status_code == 200
    r = client.post("/capture", json={"transcript": "decided to use JWT", "project": "p1", "agent": "claude-code"})
    assert r.status_code == 200
    assert r.json()["skipped"] == "capture-disabled"
    conn = db_mod.connect(db_path)
    assert conn.execute("SELECT count(*) FROM capture_queue").fetchone()[0] == 0
    conn.close()


def test_settings_capture_mode_round_trip(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/settings").json()["capture_mode"] == "raw"
    r = client.patch("/settings", json={"capture_mode": "llm"})
    assert r.status_code == 200
    assert r.json()["capture_mode"] == "llm"
    assert client.get("/settings").json()["capture_mode"] == "llm"


def test_settings_rejects_invalid_capture_mode(tmp_path):
    client, _ = _client(tmp_path)
    r = client.patch("/settings", json={"capture_mode": "turbo"})
    assert r.status_code == 400


def test_settings_rejects_null_capture_mode(tmp_path):
    client, _ = _client(tmp_path)
    r = client.patch("/settings", json={"capture_mode": None})
    assert r.status_code == 400


def test_settings_inject_enabled_round_trip(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/settings").json()["inject_enabled"] is False
    r = client.patch("/settings", json={"inject_enabled": True})
    assert r.status_code == 200
    assert r.json()["inject_enabled"] is True
    assert client.get("/settings").json()["inject_enabled"] is True


def test_clear_pending_endpoint_only_removes_pending(tmp_path):
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    queue.enqueue(conn, {"transcript": "a"})
    done = queue.enqueue(conn, {"transcript": "b"})
    queue.mark_done(conn, done)
    conn.close()

    r = client.delete("/capture/pending")
    assert r.status_code == 200
    assert r.json()["deleted"] == 1
    conn = db_mod.connect(db_path)
    assert conn.execute("SELECT status, count(*) FROM capture_queue GROUP BY status").fetchall() == [("done", 1)]
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


def test_sync_memory_endpoint(tmp_path, monkeypatch):
    from memhub import config
    root = tmp_path / "projects"
    d = root / "proj" / "memory"
    d.mkdir(parents=True)
    (d / "a.md").write_text("---\nname: a\n---\n一条够长的耐久记忆内容。\n")
    monkeypatch.setattr(config, "MEMORY_PROJECTS_ROOT", root)
    client, db_path = _client(tmp_path)
    r = client.post("/sync-memory")
    assert r.status_code == 200
    assert r.json()["stored"] == 1
    conn = db_mod.connect(db_path)
    n = conn.execute("SELECT count(*) FROM memories WHERE agent='claude-memory'").fetchone()[0]
    conn.close()
    assert n == 1


def test_projects_endpoint(tmp_path):
    from memhub import store
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    store.store_memory(conn, content="只读查询走 replica 副本", project="p2", agent="x")
    store.store_memory(conn, content="统一用 pnpm 做包管理", project="p1", agent="x")
    conn.close()
    r = client.get("/projects")
    assert r.status_code == 200
    assert r.json()["projects"] == ["p1", "p2"]
