#!/bin/bash
# memhub SessionEnd hook: send transcript_path to the local memory service.
# Never blocks the agent: all failures swallowed, always exit 0.

# memhub's own `claude -p` extraction subprocess sets MEMHUB_EXTRACTING=1; its
# SessionEnd would otherwise re-capture the extraction itself (feedback loop).
[ -n "$MEMHUB_EXTRACTING" ] && exit 0

INPUT=$(cat)
MEMHUB_URL="${MEMHUB_URL:-http://127.0.0.1:37650}" python3 -c '
import sys, os, json, urllib.request
try:
    d = json.loads(sys.argv[1])
    tp = d.get("transcript_path")
    if tp:
        body = json.dumps({"transcript_path": tp, "project": d.get("cwd"),
                           "agent": "claude-code", "session_id": d.get("session_id")}).encode()
        req = urllib.request.Request(os.environ["MEMHUB_URL"] + "/capture", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
except Exception:
    pass
' "$INPUT" >/dev/null 2>&1 || true
exit 0
