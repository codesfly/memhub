from memhub import store


def test_store_inserts_one(conn):
    mid = store.store_memory(conn, content="use JWT for auth", project="p1", agent="claude-code")
    row = conn.execute("SELECT content, kind, project, scope FROM memories WHERE id=?", (mid,)).fetchone()
    assert row[0] == "use JWT for auth"
    assert row[2] == "p1"
    assert conn.execute("SELECT count(*) FROM memories_vec WHERE memory_id=?", (mid,)).fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM memories_fts WHERE rowid=?", (mid,)).fetchone()[0] == 1


def test_store_dedupes_identical_content(conn):
    a = store.store_memory(conn, content="same fact", project="p1", agent="x")
    b = store.store_memory(conn, content="same fact", project="p1", agent="x")
    assert a == b
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1


def test_store_redacts_secret(conn):
    mid = store.store_memory(conn, content="key sk-abcdefghijklmnopqrstuvwx", project="p", agent="x")
    content = conn.execute("SELECT content FROM memories WHERE id=?", (mid,)).fetchone()[0]
    assert "sk-" not in content


def test_store_skips_empty_content(conn):
    assert store.store_memory(conn, content="   ", project="p", agent="x") is None
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
