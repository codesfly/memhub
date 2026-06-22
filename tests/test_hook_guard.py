"""The SessionEnd capture hook must not re-capture memhub's own `claude -p`
extraction calls. memhub marks those subprocesses with MEMHUB_EXTRACTING=1;
the hook (inherited into via claude) must early-exit when it sees it.
"""
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "memhub-capture.sh"


class _Counter(BaseHTTPRequestHandler):
    posts = 0

    def do_POST(self):
        _Counter.posts += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):  # silence
        pass


def _run_hook(transcript_path, url, extra_env=None):
    env = {"PATH": "/usr/bin:/bin", "MEMHUB_URL": url}
    if extra_env:
        env.update(extra_env)
    payload = json.dumps({"transcript_path": str(transcript_path),
                          "cwd": "/x", "session_id": "s"})
    subprocess.run(["bash", str(HOOK)], input=payload, text=True, env=env, timeout=10)


def test_hook_posts_normally_but_skips_when_extracting(tmp_path):
    tp = tmp_path / "t.jsonl"
    tp.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")

    _Counter.posts = 0
    srv = HTTPServer(("127.0.0.1", 0), _Counter)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        _run_hook(tp, url)                                 # normal session -> captured
        assert _Counter.posts == 1
        _run_hook(tp, url, {"MEMHUB_EXTRACTING": "1"})     # memhub's own call -> skipped
        assert _Counter.posts == 1
    finally:
        srv.shutdown()
