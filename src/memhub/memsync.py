"""Sync curated Claude memory files (~/.claude/projects/*/memory/*.md) into memhub.

These files are already agent-distilled structured memories — so this is a pure
read -> store, zero LLM. store_memory() handles redaction, embedding, content-hash
idempotency and near-dup merge, so re-running is safe.
"""
import json
import re
import time
from pathlib import Path

from . import store

_FM = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


def _resolve_project(project_dir, cache: dict) -> str:
    """Real working dir for a ~/.claude/projects/<encoded>/ dir, read from a transcript's
    `cwd`. Claude Code's dir-name encoding (/ -> -) is lossy for paths with dashes, so we
    read the actual cwd instead of decoding. This MUST equal the cwd the inject/capture
    hooks send, or project-scoped recall silently misses. Falls back to the dir name."""
    key = str(project_dir)
    if key in cache:
        return cache[key]
    cwd = None
    for jf in sorted(project_dir.glob("*.jsonl")):
        try:
            for line in jf.read_text(errors="replace").splitlines():
                if '"cwd"' not in line:
                    continue
                cwd = (json.loads(line) or {}).get("cwd")
                if cwd:
                    break
        except Exception:
            continue
        if cwd:
            break
    cache[key] = cwd or project_dir.name
    return cache[key]


def _parse(md: str):
    """Return (name, type, description, body) from a memory .md with frontmatter."""
    name = ftype = desc = None
    body = md
    m = _FM.match(md)
    if m:
        fm, body = m.group(1), m.group(2)
        for line in fm.splitlines():
            s = line.strip()
            if s.startswith("name:"):
                name = s.split(":", 1)[1].strip()
            elif s.startswith("description:"):
                desc = s.split(":", 1)[1].strip().strip('"')
            elif s.startswith("type:"):
                ftype = s.split(":", 1)[1].strip()
    return name, ftype, desc, body.strip()


def sync_memory_files(conn, projects_root, since_ts: float = 0.0) -> dict:
    """Ingest memory/*.md files modified after `since_ts` into memhub.

    Idempotent via content_hash. Returns {scanned, stored, skipped, max_mtime}
    where max_mtime is the new high-water mark to persist for the next run.
    """
    root = Path(projects_root)
    files = [f for f in sorted(root.glob("*/memory/*.md")) if f.name != "MEMORY.md"]
    scanned = stored = skipped = 0
    max_mtime = since_ts
    cwd_cache: dict = {}
    for f in files:
        try:
            mt = f.stat().st_mtime
        except OSError:
            continue
        if mt <= since_ts:
            continue  # unchanged since last sync
        scanned += 1
        max_mtime = max(max_mtime, mt)
        try:
            md = f.read_text(errors="replace")
        except OSError:
            skipped += 1
            continue
        name, ftype, desc, body = _parse(md)
        content = body or desc or ""
        if not content.strip():
            skipped += 1
            continue
        proj = _resolve_project(f.parent.parent, cwd_cache)
        # only user-identity is genuinely cross-project; feedback/project/reference
        # live in a project's memory dir and are project-local (else they pollute
        # every project's session-start inject)
        scope = "global" if ftype == "user" else "current"
        tags = [t for t in (ftype, name) if t]
        try:
            # keyed on file path so an edited file UPDATES its row instead of dup/skip
            mid = store.upsert_memory(conn, content=content, source_key=str(f), project=proj,
                                      agent="claude-memory", kind="note", tags=tags, scope=scope)
        except Exception:
            skipped += 1
            continue
        if mid:
            stored += 1
        else:
            skipped += 1
    deleted = _reconcile_deletions(conn, root, files)
    return {"scanned": scanned, "stored": stored, "skipped": skipped, "deleted": deleted, "max_mtime": max_mtime}


def _reconcile_deletions(conn, root, current_files) -> int:
    """Remove claude-memory rows whose source file (session_id) no longer exists.

    Only touches file-backed rows under `root` — store_note/capture memories
    (other agents, or NULL session_id) are never affected.
    """
    present = {str(f) for f in current_files}
    prefix = str(root)
    rows = conn.execute(
        "SELECT id, session_id FROM memories WHERE agent='claude-memory' AND session_id IS NOT NULL"
    ).fetchall()
    deleted = 0
    for mid, src in rows:
        if src.startswith(prefix) and src not in present:
            store.delete_memory(conn, mid)
            deleted += 1
    return deleted


def sync_once(conn, projects_root) -> dict:
    """One sync pass that reads + persists the mtime high-water mark in service_settings,
    so each call only touches files changed since the previous one."""
    since = _get_mtime(conn)
    res = sync_memory_files(conn, projects_root, since)
    if res["max_mtime"] > since:
        _set_mtime(conn, res["max_mtime"])
    return res


def run_sync_loop(db_path, projects_root, interval: float = 300.0, stop=None) -> None:
    """Daemon loop: periodically sync memory files. Never fatal."""
    import logging
    from . import db as db_mod
    logger = logging.getLogger("memhub.memsync")
    while not (stop and stop()):
        conn = db_mod.connect(db_path)
        try:
            res = sync_once(conn, projects_root)
            if res["stored"]:
                logger.info("memory sync: stored %s (scanned %s)", res["stored"], res["scanned"])
        except Exception:
            logger.exception("memory sync tick failed")
        finally:
            conn.close()
        time.sleep(interval)


def _get_mtime(conn) -> float:
    row = conn.execute("SELECT value FROM service_settings WHERE key='memory_sync_mtime'").fetchone()
    return float(row[0]) if row else 0.0


def _set_mtime(conn, mtime: float) -> None:
    conn.execute(
        "INSERT INTO service_settings(key, value, updated_at) VALUES ('memory_sync_mtime', ?, strftime('%s','now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(mtime),),
    )
    conn.commit()
