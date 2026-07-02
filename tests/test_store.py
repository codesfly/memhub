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
    # opposite meaning has deceptively high cosine but MUST stay separate
    store.store_memory(conn, content="这项目统一用 pnpm，禁止 npm", project="p1", agent="x")
    store.store_memory(conn, content="这项目别用 pnpm，改用 npm", project="p1", agent="x")
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 2


def test_near_dup_detected_even_when_other_projects_crowd_knn(conn):
    # the near-dup KNN probe must be scoped to the same project up front —
    # top-5 global neighbors from other projects would otherwise mask the real dup
    a = store.store_memory(conn, content="团队约定：所有微服务统一用 pnpm，禁止 npm/yarn", project="p1", agent="x")
    for i in range(6):
        store.store_memory(conn, content=f"团队约定：所有微服务统一用 pnpm，禁止 npm 或 yarn（第{i}版）",
                           project="p2", agent="x", dedup=False)
    b = store.store_memory(conn, content="团队约定：所有微服务统一用 pnpm，禁止 npm 或 yarn", project="p1", agent="x")
    assert b == a
    assert conn.execute("SELECT count(*) FROM memories WHERE project='p1'").fetchone()[0] == 1


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


def test_upsert_inserts_new_with_source_key(conn):
    mid = store.upsert_memory(conn, content="原始内容一二三四", source_key="/p/a.md",
                              project="p", agent="claude-memory")
    row = conn.execute("SELECT content, session_id FROM memories WHERE id=?", (mid,)).fetchone()
    assert row[0] == "原始内容一二三四"
    assert row[1] == "/p/a.md"


def test_upsert_updates_same_row_on_edit(conn):
    a = store.upsert_memory(conn, content="第一版：关于 pnpm 的团队约定", source_key="/p/a.md",
                            project="p", agent="claude-memory")
    b = store.upsert_memory(conn, content="第二版：约定改成 yarn，补充了一些新说明", source_key="/p/a.md",
                            project="p", agent="claude-memory")
    assert b == a  # same row updated in place
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    assert conn.execute("SELECT content FROM memories WHERE id=?", (a,)).fetchone()[0] == "第二版：约定改成 yarn，补充了一些新说明"


def test_upsert_noop_when_unchanged(conn):
    a = store.upsert_memory(conn, content="不变的内容", source_key="/p/a.md", project="p", agent="claude-memory")
    b = store.upsert_memory(conn, content="不变的内容", source_key="/p/a.md", project="p", agent="claude-memory")
    assert b == a
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1


def test_upsert_refreshes_index_on_update(conn):
    a = store.upsert_memory(conn, content="old alpha 内容", source_key="/p/a.md", project="p", agent="claude-memory")
    store.upsert_memory(conn, content="new beta 内容", source_key="/p/a.md", project="p", agent="claude-memory")
    fts = conn.execute("SELECT content FROM memories_fts WHERE rowid=?", (a,)).fetchone()[0]
    assert "beta" in fts and "alpha" not in fts
    assert conn.execute("SELECT count(*) FROM memories_vec WHERE memory_id=?", (a,)).fetchone()[0] == 1


def test_reindex_rebuilds_vec_and_fts(conn):
    from memhub import search
    a = store.store_memory(conn, "项目部署流程：用 launchd 定时器每小时推送", project="p", agent="x")
    store.store_memory(conn, "the api authenticates with JWT tokens", project="p", agent="x")
    # simulate stale indexes (old embedding model / old FTS text rules)
    conn.execute("DELETE FROM memories_vec")
    conn.execute("DELETE FROM memories_fts")
    conn.commit()
    n = store.reindex(conn)
    assert n == 2
    assert conn.execute("SELECT count(*) FROM memories_vec").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM memories_fts").fetchone()[0] == 2
    assert a in search._fts_ids(conn, "部署", 10)  # rebuilt FTS is CJK-segmented
    results = search.search(conn, "jwt token auth", project="p", scope="current")
    assert results and "JWT" in results[0]["content"]


def test_reindex_empty_db_is_noop(conn):
    assert store.reindex(conn) == 0
