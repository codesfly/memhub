"""Read path: vector KNN + FTS5, fused with RRF, scope-filtered."""
import struct
import sqlite3
from . import embedding, config


def _pack(vec: list[float]) -> bytes:
    return struct.pack("%sf" % len(vec), *vec)


def _scope_clause(project: str | None, scope: str) -> tuple[str, list]:
    parts = [s.strip() for s in scope.split(",")]
    if "all" in parts:
        return "1=1", []
    conds, params = [], []
    if "current" in parts:
        if project:
            conds.append("project = ?")
            params.append(project)
        else:
            conds.append("1=0")  # current requested but no project -> match nothing (fail closed)
    if "global" in parts:
        conds.append("scope = 'global'")
    clause = "(" + " OR ".join(conds) + ")" if conds else "1=0"  # no valid scope -> fail closed
    return clause, params


def _vector_ids(conn, query, k):
    rows = conn.execute(
        "SELECT memory_id, distance FROM memories_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (_pack(embedding.embed(query)), k),
    ).fetchall()
    return [r[0] for r in rows]


def _fts_ids(conn, query, k):
    try:
        rows = conn.execute(
            "SELECT rowid FROM memories_fts WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, k),
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # query had FTS syntax chars; vector path still works
    return [r[0] for r in rows]


def search(conn, query, project=None, scope="current,global", kind=None, limit=config.DEFAULT_LIMIT):
    if not query.strip():
        return _recent(conn, project, scope, kind, limit)
    pool = max(limit * 4, 20)
    vec_ids = _vector_ids(conn, query, pool)
    fts_ids = _fts_ids(conn, query, pool)

    scores: dict[int, float] = {}
    for rank, mid in enumerate(vec_ids):
        scores[mid] = scores.get(mid, 0) + 1.0 / (config.RRF_K + rank)
    for rank, mid in enumerate(fts_ids):
        scores[mid] = scores.get(mid, 0) + 1.0 / (config.RRF_K + rank)
    if not scores:
        return []

    clause, params = _scope_clause(project, scope)
    placeholders = ",".join("?" * len(scores))
    sql = f"SELECT id, content, kind, project, agent, scope, created_at FROM memories WHERE id IN ({placeholders}) AND {clause}"
    if kind:
        sql += " AND kind = ?"
        params = list(scores.keys()) + params + [kind]
    else:
        params = list(scores.keys()) + params
    rows = conn.execute(sql, params).fetchall()

    out = [
        {"id": r[0], "content": r[1], "kind": r[2], "project": r[3],
         "agent": r[4], "scope": r[5], "created_at": r[6], "score": scores[r[0]]}
        for r in rows
    ]
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


def _recent(conn, project, scope, kind, limit):
    clause, params = _scope_clause(project, scope)
    sql = f"SELECT id, content, kind, project, agent, scope, created_at FROM memories WHERE {clause}"
    if kind:
        sql += " AND kind = ?"
        params = params + [kind]
    sql += " ORDER BY created_at DESC LIMIT ?"
    params = params + [limit]
    rows = conn.execute(sql, params).fetchall()
    return [{"id": r[0], "content": r[1], "kind": r[2], "project": r[3],
             "agent": r[4], "scope": r[5], "created_at": r[6], "score": 0.0} for r in rows]
