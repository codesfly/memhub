def test_init_schema_creates_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "memories" in names
    assert "memories_fts" in names
    assert "capture_queue" in names


def test_vec_table_usable(conn):
    import struct
    vec = struct.pack("%sf" % 384, *([0.1] * 384))
    conn.execute("INSERT INTO memories_vec(memory_id, embedding) VALUES (1, ?)", (vec,))
    conn.commit()
    n = conn.execute("SELECT count(*) FROM memories_vec").fetchone()[0]
    assert n == 1


def test_connect_sets_busy_timeout_and_wal_synchronous(tmp_path):
    # three writer threads share this db (server / worker / memsync): without a
    # busy_timeout a write-lock collision raises "database is locked" immediately
    from memhub import db as db_mod
    c = db_mod.connect(tmp_path / "x.db")
    try:
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
        assert c.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL, the WAL pairing
    finally:
        c.close()
