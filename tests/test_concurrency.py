"""Concurrency safety: each thread opens its own connection -> no torn writes."""
import threading
from memhub import db as db_mod, store


def test_concurrent_writes_are_consistent(tmp_path):
    db_path = tmp_path / "concur.db"
    c = db_mod.connect(db_path)
    db_mod.init_schema(c)
    c.close()

    errors = []

    # genuinely distinct facts: digit-only variants ("memory number 3/5") are
    # semantic near-dups the write path is SUPPOSED to merge — this test is about
    # torn writes, so content must not trip the dedup path
    topics = ["docker networking", "launchd timers", "sqlite wal mode", "jwt auth flow",
              "pnpm workspaces", "fts5 tokenizers", "rrf rank fusion", "onnx runtime"]

    def worker(i):
        try:
            conn = db_mod.connect(db_path)
            store.store_memory(conn, content=f"thread {i} wrote a fact about {topics[i]}",
                               project="p", agent="x")
            conn.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent writes raised: {errors}"

    conn = db_mod.connect(db_path)
    m = conn.execute("SELECT count(*) FROM memories").fetchone()[0]
    v = conn.execute("SELECT count(*) FROM memories_vec").fetchone()[0]
    f = conn.execute("SELECT count(*) FROM memories_fts").fetchone()[0]
    conn.close()
    assert m == v == f == 8, f"torn writes: {m}/{v}/{f}"
