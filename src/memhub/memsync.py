"""Sync curated Claude memory files (~/.claude/projects/*/memory/*.md) into memhub.

These files are already agent-distilled structured memories — so this is a pure
read -> store, zero LLM. store_memory() handles redaction, embedding, content-hash
idempotency and near-dup merge, so re-running is safe.
"""
import re
import time
from pathlib import Path

from . import store

_FM = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.S)


def _short_project(dirname: str) -> str:
    """Encoded project dir (-Users-jiumu-Desktop-douyin) -> short label (douyin)."""
    for pre in ("-Users-jiumu-Desktop-", "-Users-jiumu-Code-", "-Users-jiumu-"):
        if dirname.startswith(pre):
            return dirname[len(pre):] or "home"
    return dirname


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
    scanned = stored = skipped = 0
    max_mtime = since_ts
    for f in sorted(root.glob("*/memory/*.md")):
        if f.name == "MEMORY.md":
            continue  # index file, not a memory
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
        proj = _short_project(f.parent.parent.name)
        scope = "global" if ftype in ("user", "feedback") else "current"
        tags = [t for t in (ftype, name) if t]
        mid = store.store_memory(conn, content=content, project=proj, agent="claude-memory",
                                 kind="note", tags=tags, scope=scope)
        if mid:
            stored += 1
        else:
            skipped += 1
    return {"scanned": scanned, "stored": stored, "skipped": skipped, "max_mtime": max_mtime}


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
