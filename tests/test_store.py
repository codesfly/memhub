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


def test_store_merges_near_duplicate_same_project(conn):
    # paraphrase of the same fact (cos ~0.99) -> NOOP, returns the existing id
    a = store.store_memory(conn, content="团队约定：所有微服务统一用 pnpm，禁止 npm/yarn", project="p1", agent="x")
    b = store.store_memory(conn, content="团队约定：所有微服务统一用 pnpm，禁止 npm 或 yarn", project="p1", agent="x")
    assert b == a
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1


def test_store_keeps_distinct_facts_same_project(conn):
    store.store_memory(conn, content="团队约定：所有微服务统一用 pnpm", project="p1", agent="x")
    store.store_memory(conn, content="HTTP 请求超时统一设置为 30 秒", project="p1", agent="x")
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 2


def test_store_does_not_merge_contradiction(conn):
    # opposite meaning has deceptively high cosine (~0.88) but MUST stay separate
    store.store_memory(conn, content="这项目统一用 pnpm，禁止 npm", project="p1", agent="x")
    store.store_memory(conn, content="这项目别用 pnpm，改用 npm", project="p1", agent="x")
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 2


def test_store_keeps_near_dup_across_different_projects(conn):
    a = store.store_memory(conn, content="统一用 pnpm，禁止 npm/yarn", project="p1", agent="x")
    b = store.store_memory(conn, content="统一用 pnpm，禁止 npm 或 yarn", project="p2", agent="x")
    assert b != a
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 2


def test_list_projects_returns_distinct_sorted(conn):
    store.store_memory(conn, content="统一用 pnpm 做包管理", project="zixungou", agent="x")
    store.store_memory(conn, content="HTTP 客户端超时设 30 秒", project="douyin", agent="x")
    store.store_memory(conn, content="只读查询走 replica 副本库", project="douyin", agent="x")
    store.store_memory(conn, content="封面前三秒必须给结果", project=None, agent="x")
    assert store.list_projects(conn) == ["douyin", "zixungou"]
