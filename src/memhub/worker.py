"""Background worker: drain capture_queue through a Capturer into storage."""
import json
import time
import logging
import sqlite3
from . import queue, store, db as db_mod, settings as settings_mod

logger = logging.getLogger("memhub.worker")

def process_pending(conn: sqlite3.Connection, primary, fallback, limit: int = 10,
                    capture_mode: str | None = None) -> int:
    """Process up to `limit` queued items. A failure on one item logs + marks it
    failed and continues; it never aborts the batch or propagates."""
    mode = settings_mod.get_capture_mode(conn) if capture_mode is None else settings_mod.normalize_capture_mode(capture_mode)
    done = 0
    for qid, payload_json in queue.claim_pending(conn, limit):
        try:
            payload = json.loads(payload_json)
            transcript = payload.get("transcript", "")
            if not transcript.strip():
                # empty session (e.g. a short home-dir session) — nothing to capture, don't shell out to claude
                queue.mark_done(conn, qid)
                done += 1
                continue
            if mode == "off":
                queue.mark_done(conn, qid)
                done += 1
                continue
            meta = {"project": payload.get("project"), "agent": payload.get("agent"),
                    "session_id": payload.get("session_id")}
            items = (fallback.capture(transcript, meta) if mode == "raw"
                     else _capture_with_fallback(transcript, meta, primary, fallback))
            for it in items:
                store.store_memory(
                    conn, content=it["content"], project=meta["project"], agent=meta["agent"],
                    kind=it.get("kind", "raw"), tags=it.get("tags", []),
                    scope=it.get("scope", "current"), session_id=meta["session_id"],
                )
            queue.mark_done(conn, qid)
            done += 1
        except Exception:
            logger.exception("capture/store failed for qid=%s", qid)
            queue.mark_failed(conn, qid)
    return done

def _capture_with_fallback(transcript, meta, primary, fallback) -> list[dict]:
    try:
        return primary.capture(transcript, meta)
    except Exception:
        logger.warning("primary capturer failed, falling back to raw", exc_info=True)
        return fallback.capture(transcript, meta)

def run_loop(db_path, primary, fallback, interval: float = 5.0, stop=None,
             capture_mode: str | None = None) -> None:
    """Poll the queue until stop() is truthy. A bad tick is logged, never fatal."""
    while not (stop and stop()):
        conn = db_mod.connect(db_path)
        try:
            process_pending(conn, primary, fallback, capture_mode=capture_mode)
        except Exception:
            logger.exception("memhub worker tick failed")
        finally:
            conn.close()
        time.sleep(interval)
