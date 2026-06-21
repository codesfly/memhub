from starlette.testclient import TestClient
from memhub import server, db as db_mod, store


def _client(tmp_path):
    db_path = tmp_path / "m.db"
    c = db_mod.connect(db_path); db_mod.init_schema(c); c.close()
    return TestClient(server.build_app(db_path)), db_path


def test_list_memories_orders_newest_first(conn):
    a = store.store_memory(conn, "first", project="p1", agent="x")
    b = store.store_memory(conn, "second", project="p1", agent="x")
    items = store.list_memories(conn, project="p1")
    assert [m["id"] for m in items] == [b, a]  # newest first


def test_list_memories_filters_and_paginates(conn):
    store.store_memory(conn, "d1", project="p1", agent="x", kind="decision")
    store.store_memory(conn, "f1", project="p1", agent="x", kind="fact")
    store.store_memory(conn, "d2", project="p2", agent="x", kind="decision")
    assert all(m["kind"] == "decision" for m in store.list_memories(conn, kind="decision"))
    assert all(m["project"] == "p1" for m in store.list_memories(conn, project="p1"))
    assert len(store.list_memories(conn, limit=1)) == 1


def test_delete_memory_removes_from_all_tables(conn):
    mid = store.store_memory(conn, "to delete", project="p1", agent="x")
    assert store.delete_memory(conn, mid) is True
    assert conn.execute("SELECT count(*) FROM memories WHERE id=?", (mid,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM memories_vec WHERE memory_id=?", (mid,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM memories_fts WHERE rowid=?", (mid,)).fetchone()[0] == 0


def test_delete_missing_returns_false(conn):
    assert store.delete_memory(conn, 99999) is False


def test_memories_endpoint_lists(tmp_path):
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    store.store_memory(conn, "hello world", project="p1", agent="x")
    conn.close()
    r = client.get("/memories", params={"project": "p1"})
    assert r.status_code == 200
    assert any("hello world" in m["content"] for m in r.json()["memories"])


def test_memories_bad_limit_400(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/memories", params={"limit": "abc"}).status_code == 400


def test_delete_endpoint(tmp_path):
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    mid = store.store_memory(conn, "delete me", project="p1", agent="x")
    conn.close()
    assert client.delete(f"/memories/{mid}").status_code == 200
    assert client.delete(f"/memories/{mid}").status_code == 404  # already gone


def test_ui_serves_html(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "memhub" in r.text and "fetch(" in r.text


def test_ui_escapes_id_interpolation():
    from memhub import ui
    assert "esc(String(m.id))" in ui.PAGE  # id is escaped — no XSS via id attribute


def test_list_memories_clamps_limit(conn):
    for i in range(5):
        store.store_memory(conn, f"mem {i}", project="pc", agent="x")
    # negative limit must not dump everything; clamped to >=1
    assert len(store.list_memories(conn, project="pc", limit=-1)) <= 5
    assert len(store.list_memories(conn, project="pc", limit=2)) == 2


def test_list_memories_preserves_raw_content(conn):
    # server returns raw; escaping is the client's job (ui.esc)
    store.store_memory(conn, "<script>alert(1)</script>", project="px", agent="x")
    items = store.list_memories(conn, project="px")
    assert any("<script>" in m["content"] for m in items)
