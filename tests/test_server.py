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


def test_capture_then_search(tmp_path):
    client, _ = _client(tmp_path)
    cap = client.post("/capture", json={
        "transcript": "decided to use JWT for authentication",
        "project": "p1", "agent": "claude-code", "session_id": "s1"})
    assert cap.status_code == 200
    res = client.get("/search", params={"query": "auth login", "project": "p1", "scope": "all"})
    assert res.status_code == 200
    assert any("JWT" in m["content"] for m in res.json()["results"])


def test_capture_malformed_json_returns_400(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/capture", content="not json")
    assert r.status_code == 400


def test_search_bad_limit_returns_400(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/search", params={"query": "x", "limit": "abc"})
    assert r.status_code == 400
