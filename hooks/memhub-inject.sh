#!/bin/bash
# memhub SessionStart hook: inject relevant memories as additionalContext.
# Fast + silent: short timeout, any failure -> no output, exit 0.
INPUT=$(cat)
python3 -c '
import sys, json, urllib.request
try:
    d = json.loads(sys.argv[1])
    cwd = d.get("cwd")
    if cwd:
        body = json.dumps({"project": cwd}).encode()
        req = urllib.request.Request("http://127.0.0.1:37650/inject", data=body,
                                     headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=3).read())
        ctx = resp.get("context", "")
        if ctx:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                      "additionalContext": ctx}}))
except Exception:
    pass
' "$INPUT" 2>/dev/null || true
exit 0
