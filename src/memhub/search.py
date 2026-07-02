"""Read path: vector KNN + FTS5, fused with RRF, scope-filtered."""
import struct
import sqlite3
from . import embedding, config, fts


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


def _filter_clause(project: str | None, scope: str, kind: str | None) -> tuple[str, list]:
    clause, params = _scope_clause(project, scope)
    if kind:
        clause = f"{clause} AND kind = ?"
        params = params + [kind]
    return clause, params


def _vector_ids(conn, query, k, clause="1=1", params=()):
    # scope/kind are applied INSIDE the KNN: ranking a global top-k and filtering
    # afterwards lets crowded neighbor projects push the real hits out of the pool
    sql = "SELECT memory_id FROM memories_vec WHERE embedding MATCH ? AND k = ?"
    args = [_pack(embedding.embed(query)), k]
    if clause != "1=1":
        sql += f" AND memory_id IN (SELECT id FROM memories WHERE {clause})"
        args += list(params)
    rows = conn.execute(sql + " ORDER BY distance", args).fetchall()
    return [r[0] for r in rows]


def _fts_ids(conn, query, k, clause="1=1", params=()):
    sql = "SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?"
    args = [fts.match_query(query)]
    if clause != "1=1":
        sql += f" AND rowid IN (SELECT id FROM memories WHERE {clause})"
        args += list(params)
    try:
        rows = conn.execute(sql + " ORDER BY rank LIMIT ?", args + [k]).fetchall()
    except sqlite3.OperationalError:
        return []  # degenerate MATCH expression (e.g. symbols only); vector path still works
    return [r[0] for r in rows]


def search(conn, query, project=None, scope="current,global", kind=None, limit=config.DEFAULT_LIMIT):
    if not query.strip():
        return _recent(conn, project, scope, kind, limit)
    clause, params = _filter_clause(project, scope, kind)
    pool = max(limit * 4, 20)
    vec_ids = _vector_ids(conn, query, pool, clause, params)
    fts_ids = _fts_ids(conn, query, pool, clause, params)

    scores: dict[int, float] = {}
    for rank, mid in enumerate(vec_ids):
        scores[mid] = scores.get(mid, 0) + 1.0 / (config.RRF_K + rank)
    for rank, mid in enumerate(fts_ids):
        scores[mid] = scores.get(mid, 0) + 1.0 / (config.RRF_K + rank)
    if not scores:
        return []

    placeholders = ",".join("?" * len(scores))
    rows = conn.execute(
        f"SELECT id, content, kind, project, agent, scope, created_at "
        f"FROM memories WHERE id IN ({placeholders})",
        list(scores.keys()),
    ).fetchall()

    out = [
        {"id": r[0], "content": r[1], "kind": r[2], "project": r[3],
         "agent": r[4], "scope": r[5], "created_at": r[6], "score": scores[r[0]]}
        for r in rows
    ]
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


def _recent(conn, project, scope, kind, limit):
    """Recency feed (the /inject path): newest first, capped per session so one giant
    raw-captured session can't fill every slot; backfills if capping runs short."""
    clause, params = _filter_clause(project, scope, kind)
    rows = conn.execute(
        f"SELECT id, content, kind, project, agent, scope, created_at, session_id "
        f"FROM memories WHERE {clause} ORDER BY created_at DESC, id DESC LIMIT ?",
        params + [max(limit * 5, limit)],
    ).fetchall()
    picked, skipped, per_session = [], [], {}
    for r in rows:
        sid = r[7]
        if sid is not None and per_session.get(sid, 0) >= config.INJECT_SESSION_CAP:
            skipped.append(r)
            continue
        if sid is not None:
            per_session[sid] = per_session.get(sid, 0) + 1
        picked.append(r)
    picked = (picked + skipped)[:limit]
    return [{"id": r[0], "content": r[1], "kind": r[2], "project": r[3],
             "agent": r[4], "scope": r[5], "created_at": r[6], "score": 0.0} for r in picked]
