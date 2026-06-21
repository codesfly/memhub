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
