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
