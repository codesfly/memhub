"""memhub CLI — thin REST client over the local service."""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from urllib.request import urlopen
from . import config

BASE = f"http://{config.HOST}:{config.PORT}"

def _get(path):
    with urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read())

def _delete(mid):
    req = urllib.request.Request(f"{BASE}/memories/{mid}", method="DELETE")
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def _delete_path(path):
    req = urllib.request.Request(BASE + path, method="DELETE")
    with urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def _post(path):
    req = urllib.request.Request(BASE + path, method="POST")
    with urlopen(req, timeout=60) as r:
        return json.loads(r.read())

def _print(items):
    if not items:
        print("(no memories)"); return
    for m in items:
        print(f"#{m['id']} [{m.get('kind','?')}] {m.get('project','—')} :: {m.get('content','')[:100]}")

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="memhub", description="memhub memory management")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list"); pl.add_argument("--project"); pl.add_argument("--kind"); pl.add_argument("--limit", default="50")
    ps = sub.add_parser("search"); ps.add_argument("query"); ps.add_argument("--scope", default="all")
    pd = sub.add_parser("delete"); pd.add_argument("id"); pd.add_argument("--yes", action="store_true")
    pc = sub.add_parser("clear-pending"); pc.add_argument("--yes", action="store_true")
    sub.add_parser("sync-memory")
    pr = sub.add_parser("reindex", help="re-embed all memories + rebuild FTS (after a model switch)")
    pr.add_argument("--db"); pr.add_argument("--yes", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "reindex":
        # offline maintenance on the db file itself — no service round-trip, and the
        # embedding model import stays out of the plain REST commands
        from . import db as db_mod, store
        path = args.db or config.DB_PATH
        if not args.yes and input(f"re-embed ALL memories in {path}? [y/N] ").lower() != "y":
            print("cancelled"); return 0
        conn = db_mod.connect(path)
        try:
            n = store.reindex(conn)
        finally:
            conn.close()
        print(f"reindexed {n} memories")
        return 0
    try:
        if args.cmd == "list":
            qs = urllib.parse.urlencode({k: v for k, v in
                {"project": args.project, "kind": args.kind, "limit": args.limit}.items() if v})
            _print(_get(f"/memories?{qs}")["memories"])
        elif args.cmd == "search":
            qs = urllib.parse.urlencode({"query": args.query, "scope": args.scope})
            _print(_get(f"/search?{qs}")["results"])
        elif args.cmd == "delete":
            if not args.yes and input(f"delete memory #{args.id}? [y/N] ").lower() != "y":
                print("cancelled"); return 0
            print("deleted" if _delete(args.id).get("deleted") else "not found")
        elif args.cmd == "clear-pending":
            if not args.yes and input("delete all pending captures? [y/N] ").lower() != "y":
                print("cancelled"); return 0
            data = _delete_path("/capture/pending")
            print(f"deleted {data.get('deleted', 0)} pending captures")
        elif args.cmd == "sync-memory":
            data = _post("/sync-memory")
            print(f"synced: stored {data.get('stored', 0)}, deleted {data.get('deleted', 0)}, "
                  f"scanned {data.get('scanned', 0)}, skipped {data.get('skipped', 0)}")
    except (urllib.error.URLError, OSError):
        print(f"memhub service unreachable at {BASE} (is it running?)", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
