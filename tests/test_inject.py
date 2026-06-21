import json
from starlette.testclient import TestClient
from memhub import server, db as db_mod, store

def _client(tmp_path):
    db_path = tmp_path / "i.db"
    c = db_mod.connect(db_path); db_mod.init_schema(c); c.close()
    return TestClient(server.build_app(db_path)), db_path

def test_capture_accepts_transcript_path(tmp_path):
    tp = tmp_path / "t.jsonl"
    tp.write_text(json.dumps({"type": "user", "message": {"content": "we use JWT for auth"}}))
    client, db_path = _client(tmp_path)
    r = client.post("/capture", json={"transcript_path": str(tp), "project": "p1", "agent": "claude-code"})
    assert r.status_code == 200 and "queued" in r.json()
    conn = db_mod.connect(db_path)
    payload = json.loads(conn.execute("SELECT payload FROM capture_queue").fetchone()[0])
    conn.close()
    assert "JWT" in payload["transcript"]

def test_inject_formats_memories(tmp_path):
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    store.store_memory(conn, "auth uses JWT tokens", project="p1", agent="x", kind="decision", scope="current")
    conn.close()
    r = client.post("/inject", json={"project": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert "context" in body and "JWT" in body["context"] and "memhub" in body["context"]

def test_inject_empty_when_no_memories(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/inject", json={"project": "nope"})
    assert r.status_code == 200 and r.json()["context"] == ""
