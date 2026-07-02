from memhub import store, search


def _seed(conn):
    store.store_memory(conn, "authentication uses JWT tokens", project="p1", agent="x", scope="current")
    store.store_memory(conn, "we deploy with docker compose", project="p1", agent="x", scope="current")
    store.store_memory(conn, "python list comprehension tips", project="p2", agent="x", scope="global")


def test_semantic_search_ranks_relevant_first(conn):
    _seed(conn)
    results = search.search(conn, query="how do we log users in", project="p1", scope="all")
    assert results, "expected at least one result"
    assert "JWT" in results[0]["content"]


def test_scope_filter_excludes_other_project(conn):
    _seed(conn)
    results = search.search(conn, query="anything", project="p1", scope="current")
    projects = {r["project"] for r in results}
    assert projects <= {"p1"}


def test_global_scope_included(conn):
    _seed(conn)
    results = search.search(conn, query="python tips", project="p1", scope="current,global")
    contents = " ".join(r["content"] for r in results)
    assert "comprehension" in contents


def test_current_without_project_fails_closed(conn):
    _seed(conn)
    results = search.search(conn, query="anything", project=None, scope="current")
    assert results == []

def test_current_without_project_still_returns_global(conn):
    _seed(conn)
    results = search.search(conn, query="python tips", project=None, scope="current,global")
    assert any("comprehension" in r["content"] for r in results)

def test_kind_filter_restricts_results(conn):
    store.store_memory(conn, "decision: cache with redis", project="pk", agent="x", kind="decision", scope="current")
    store.store_memory(conn, "raw note about redis cache", project="pk", agent="x", kind="raw", scope="current")
    results = search.search(conn, query="redis cache", project="pk", scope="current", kind="decision")
    assert results
    assert all(r["kind"] == "decision" for r in results)

def test_fts_syntax_chars_dont_crash(conn):
    _seed(conn)
    results = search.search(conn, query='broken" AND (', project="p1", scope="all")
    assert isinstance(results, list)

def test_recent_fallback_respects_limit_and_marks_score_zero(conn):
    for i in range(3):
        store.store_memory(conn, f"mem number {i}", project="pr", agent="x", scope="current")
    results = search.search(conn, query="   ", project="pr", scope="current", limit=2)
    assert len(results) == 2                      # _recent respects limit
    assert all(r["score"] == 0.0 for r in results)  # _recent marks score 0.0


def test_scope_prefilter_survives_crowding_by_other_project(conn):
    # 100 near-identical rows in another project must not crowd the target
    # project's only relevant memory out of the KNN/FTS candidate pool:
    # scope has to be applied BEFORE ranking, not after
    store.store_memory(conn, "the service is deployed with docker compose on the mac mini",
                       project="small", agent="x")
    for i in range(100):
        store.store_memory(conn, f"docker compose deploy {i}", project="big", agent="x", dedup=False)
    results = search.search(conn, "docker compose deploy", project="small", scope="current")
    assert results, "pre-filtered search must still find the small project's memory"
    assert all(r["project"] == "small" for r in results)


def test_fts_matches_chinese_word_inside_run(conn):
    # unicode61 keeps a CJK run as ONE token, so '部署' can never match unless
    # CJK is segmented at index time and phrase-queried at match time
    mid = store.store_memory(conn, "项目部署流程：用 launchd 定时器每小时推送", project="pz", agent="x")
    assert mid in search._fts_ids(conn, "部署", 10)


def test_fts_english_stemming_still_works(conn):
    mid = store.store_memory(conn, "we are deploying the api with docker", project="pe", agent="x")
    assert mid in search._fts_ids(conn, "deploy", 10)


def test_fts_mixed_chinese_english_query(conn):
    mid = store.store_memory(conn, "项目部署流程：用 launchd 定时器每小时推送", project="pm", agent="x")
    assert mid in search._fts_ids(conn, "部署 launchd", 10)


def test_chinese_semantic_search_ranks_topic_first(conn):
    store.store_memory(conn, "定时任务用 launchd 的 StartInterval 每小时触发一次", project="pc", agent="x")
    store.store_memory(conn, "首页按钮颜色改成品牌蓝", project="pc", agent="x")
    store.store_memory(conn, "数据库查询加了覆盖索引", project="pc", agent="x")
    results = search.search(conn, "怎么配置周期性调度任务", project="pc", scope="current")
    assert results and "launchd" in results[0]["content"]


def test_recent_inject_not_flooded_by_one_session(conn):
    # one giant raw-captured session must not fill every injection slot
    for i in range(10):
        store.store_memory(conn, f"大会话原文分块 {i}", project="pd", agent="x",
                           session_id="big-session", dedup=False)
    store.store_memory(conn, "会话乙确定了新的部署端口 8080", project="pd", agent="x", session_id="s2")
    store.store_memory(conn, "会话丙记录了数据库迁移方案", project="pd", agent="x", session_id="s3")
    # force the big session to be newest so pure recency would return only its chunks
    conn.execute("UPDATE memories SET created_at = created_at + 3600 WHERE session_id='big-session'")
    conn.commit()
    results = search.search(conn, "", project="pd", scope="current", limit=6)
    contents = " ".join(r["content"] for r in results)
    assert "会话乙确定了新的部署端口" in contents
    assert "会话丙记录了数据库迁移方案" in contents


def test_recent_inject_backfills_when_only_one_session(conn):
    # cap must not shrink results when there is nothing else to show
    for i in range(6):
        store.store_memory(conn, f"唯一会话的分块 {i}", project="po", agent="x",
                           session_id="only", dedup=False)
    results = search.search(conn, "", project="po", scope="current", limit=4)
    assert len(results) == 4
