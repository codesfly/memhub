# memhub 捕获管道 Implementation Plan (Phase 1 · 计划 B1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 异步捕获管道——`/capture` 入队即返回,后台 worker 用 `claude -p` 把 transcript 抽取成结构化记忆(原文切片兜底)→ 脱敏(已在 store)→ 存库。

**Architecture:** 复用 Plan A 的 `capture_queue` 表做持久队列。`Capturer` 接口两实现:`LLMCapturer`(调 `claude -p` 子进程,解析 JSON)、`RawCapturer`(按长度切片兜底)。`worker.process_pending` 取队列 → 抽取(失败降级 Raw)→ 逐条 `store_memory`。`/capture` 改为只 `enqueue`,`main()` 起后台 worker 线程轮询。所有 DB 操作沿用 Plan A 的 per-operation connection。

**Tech Stack:** 复用 Plan A 栈(Python/sqlite-vec/fastembed)+ `subprocess`(claude CLI)。测试全程 mock `claude`,不真调。

**前置:** Plan A 已合入 main(`store_memory`/`db`/`config` 可用,`capture_queue` 表已建)。本计划在新分支 `feat/capture-pipeline` 上做。

---

## 文件结构

```
src/memhub/
├── queue.py     # capture_queue 操作:enqueue / claim_pending / mark_done / mark_failed
├── capture.py   # Capturer 协议 + RawCapturer + LLMCapturer(claude -p)
├── worker.py    # process_pending(一轮) + run_loop(后台循环)
└── server.py    # 改:/capture 入队;main() 起 worker 线程
tests/
├── test_queue.py
├── test_capture.py    # RawCapturer + LLMCapturer(mock subprocess)
└── test_worker.py     # process_pending 端到端(mock capturer)
```

---

## Task 1: queue.py(队列操作)

**Files:** Create `src/memhub/queue.py`; Test `tests/test_queue.py`

- [ ] **Step 1: 写 tests/test_queue.py**

```python
import json
from memhub import queue

def test_enqueue_then_claim(conn):
    qid = queue.enqueue(conn, {"transcript": "hello", "project": "p1"})
    pending = queue.claim_pending(conn, limit=10)
    assert len(pending) == 1
    assert pending[0][0] == qid
    assert json.loads(pending[0][1])["transcript"] == "hello"

def test_mark_done_removes_from_pending(conn):
    qid = queue.enqueue(conn, {"transcript": "x"})
    queue.mark_done(conn, qid)
    assert queue.claim_pending(conn, limit=10) == []

def test_mark_failed_increments_attempts(conn):
    qid = queue.enqueue(conn, {"transcript": "x"})
    queue.mark_failed(conn, qid)
    row = conn.execute("SELECT status, attempts FROM capture_queue WHERE id=?", (qid,)).fetchone()
    assert row[0] == "failed"
    assert row[1] == 1
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_queue.py -v` → FAIL (no module `queue`)

- [ ] **Step 3: 写 src/memhub/queue.py**

```python
"""capture_queue operations."""
import json
import time
import sqlite3

def enqueue(conn: sqlite3.Connection, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO capture_queue (payload, status, created_at) VALUES (?, 'pending', ?)",
        (json.dumps(payload), int(time.time())),
    )
    conn.commit()
    return cur.lastrowid

def claim_pending(conn: sqlite3.Connection, limit: int = 10) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT id, payload FROM capture_queue WHERE status='pending' ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]

def mark_done(conn: sqlite3.Connection, qid: int) -> None:
    conn.execute("UPDATE capture_queue SET status='done' WHERE id=?", (qid,))
    conn.commit()

def mark_failed(conn: sqlite3.Connection, qid: int) -> None:
    conn.execute(
        "UPDATE capture_queue SET status='failed', attempts=attempts+1 WHERE id=?", (qid,)
    )
    conn.commit()
```

- [ ] **Step 4: 跑测试确认通过** — `./.venv/bin/pytest tests/test_queue.py -v` → 3 passed

- [ ] **Step 5: 提交** — `git add src/memhub/queue.py tests/test_queue.py && git commit -m "feat: capture_queue operations"`

---

## Task 2: capture.py — Capturer 协议 + RawCapturer

**Files:** Create `src/memhub/capture.py`; Test `tests/test_capture.py`

- [ ] **Step 1: 写 tests/test_capture.py**

```python
from memhub.capture import RawCapturer

def test_raw_capturer_returns_chunks():
    cap = RawCapturer(max_chars=20)
    text = "a" * 50
    items = cap.capture(text, {})
    assert len(items) == 3  # 50 chars / 20 -> 3 chunks
    assert all(it["kind"] == "raw" for it in items)
    assert all(it["scope"] == "current" for it in items)

def test_raw_capturer_empty_text():
    assert RawCapturer().capture("   ", {}) == []
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_capture.py -v` → FAIL

- [ ] **Step 3: 写 src/memhub/capture.py**

```python
"""Capturers: turn a transcript into a list of memory dicts.

Each item: {"content": str, "kind": str, "tags": list, "scope": str}
"""
from typing import Protocol

class Capturer(Protocol):
    def capture(self, transcript: str, meta: dict) -> list[dict]:
        ...

class RawCapturer:
    """Fallback: slice transcript into fixed-size chunks."""
    def __init__(self, max_chars: int = 1000):
        self.max_chars = max_chars

    def capture(self, transcript: str, meta: dict) -> list[dict]:
        text = transcript.strip()
        if not text:
            return []
        chunks = [text[i:i + self.max_chars] for i in range(0, len(text), self.max_chars)]
        return [{"content": c, "kind": "raw", "tags": [], "scope": "current"} for c in chunks]
```

- [ ] **Step 4: 跑测试确认通过** — `./.venv/bin/pytest tests/test_capture.py -v` → 2 passed

- [ ] **Step 5: 提交** — `git add src/memhub/capture.py tests/test_capture.py && git commit -m "feat: RawCapturer fallback"`

---

## Task 3: capture.py — LLMCapturer(claude -p)

**Files:** Modify `src/memhub/capture.py`; Modify `tests/test_capture.py`

- [ ] **Step 1: 追加测试到 tests/test_capture.py(mock subprocess)**

```python
import json
from unittest.mock import patch, MagicMock
from memhub.capture import LLMCapturer

def _fake_run(stdout):
    m = MagicMock()
    m.stdout = stdout
    m.returncode = 0
    return m

def test_llm_capturer_parses_json():
    out = json.dumps([{"content": "use JWT", "kind": "decision", "tags": [], "scope": "global"}])
    with patch("memhub.capture.subprocess.run", return_value=_fake_run(out)):
        items = LLMCapturer().capture("transcript text", {})
    assert items[0]["content"] == "use JWT"
    assert items[0]["kind"] == "decision"

def test_llm_capturer_handles_fenced_json():
    out = "```json\n[{\"content\":\"x\",\"kind\":\"fact\",\"tags\":[],\"scope\":\"current\"}]\n```"
    with patch("memhub.capture.subprocess.run", return_value=_fake_run(out)):
        items = LLMCapturer().capture("t", {})
    assert items[0]["content"] == "x"

def test_llm_capturer_raises_on_bad_output():
    with patch("memhub.capture.subprocess.run", return_value=_fake_run("not json at all")):
        try:
            LLMCapturer().capture("t", {})
            assert False, "expected CaptureError"
        except Exception as e:
            assert "parse" in str(e).lower() or "json" in str(e).lower()

def test_llm_capturer_raises_on_timeout():
    import subprocess as sp
    with patch("memhub.capture.subprocess.run", side_effect=sp.TimeoutExpired("claude", 60)):
        try:
            LLMCapturer().capture("t", {})
            assert False, "expected error"
        except Exception:
            pass
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_capture.py -v` → new tests FAIL

- [ ] **Step 3: 在 capture.py 追加 LLMCapturer + helpers**

```python
import json
import subprocess

class CaptureError(Exception):
    pass

_EXTRACT_PROMPT = (
    "You extract durable memories from an AI coding session transcript. "
    "Output ONLY a JSON array. Each item: "
    '{"content": <one concise memory>, "kind": <"decision"|"fact"|"convention"|"snippet">, '
    '"tags": <string list>, "scope": <"current"|"global">}. '
    "scope=global means reusable across projects; current means project-specific. "
    "No prose, no markdown fences, only the JSON array."
)

def _extract_json_array(text: str) -> list[dict]:
    # tolerate ```json fences or surrounding prose: grab first [ ... last ]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise CaptureError(f"no JSON array in claude output: {text[:120]!r}")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise CaptureError(f"failed to parse JSON: {e}") from e
    if not isinstance(data, list):
        raise CaptureError("parsed JSON is not a list")
    return data

class LLMCapturer:
    """Primary: use `claude -p` to extract structured memories."""
    def __init__(self, timeout: int = 120, model_cmd: str = "claude"):
        self.timeout = timeout
        self.model_cmd = model_cmd

    def capture(self, transcript: str, meta: dict) -> list[dict]:
        proc = subprocess.run(
            [self.model_cmd, "-p", _EXTRACT_PROMPT],
            input=transcript, text=True, capture_output=True, timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise CaptureError(f"claude exited {proc.returncode}: {proc.stderr[:200]}")
        items = _extract_json_array(proc.stdout)
        # normalize: ensure required keys, drop malformed entries
        out = []
        for it in items:
            if isinstance(it, dict) and it.get("content"):
                out.append({
                    "content": str(it["content"]),
                    "kind": it.get("kind", "fact"),
                    "tags": it.get("tags", []) if isinstance(it.get("tags"), list) else [],
                    "scope": "global" if it.get("scope") == "global" else "current",
                })
        if not out:
            raise CaptureError("no valid memory items extracted")
        return out
```

- [ ] **Step 4: 跑测试确认通过** — `./.venv/bin/pytest tests/test_capture.py -v` → all pass

- [ ] **Step 5: 提交** — `git add src/memhub/capture.py tests/test_capture.py && git commit -m "feat: LLMCapturer via claude -p with JSON parsing"`

---

## Task 4: worker.py(process_pending,降级 + 存储)

**Files:** Create `src/memhub/worker.py`; Test `tests/test_worker.py`

- [ ] **Step 1: 写 tests/test_worker.py**

```python
from memhub import worker, queue, db as db_mod

class StubCapturer:
    def __init__(self, items=None, fail=False):
        self.items, self.fail = items or [], fail
    def capture(self, transcript, meta):
        if self.fail:
            raise RuntimeError("boom")
        return self.items

def test_process_pending_stores_and_marks_done(conn):
    queue.enqueue(conn, {"transcript": "t", "project": "p1", "agent": "claude-code"})
    primary = StubCapturer(items=[{"content": "use JWT", "kind": "decision", "tags": [], "scope": "global"}])
    n = worker.process_pending(conn, primary=primary, fallback=StubCapturer())
    assert n == 1
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    assert queue.claim_pending(conn) == []  # marked done

def test_process_pending_falls_back_on_primary_failure(conn):
    queue.enqueue(conn, {"transcript": "raw text here", "project": "p1", "agent": "x"})
    primary = StubCapturer(fail=True)
    fallback = StubCapturer(items=[{"content": "raw text here", "kind": "raw", "tags": [], "scope": "current"}])
    worker.process_pending(conn, primary=primary, fallback=fallback)
    assert conn.execute("SELECT count(*) FROM memories WHERE kind='raw'").fetchone()[0] == 1

def test_process_pending_marks_failed_when_both_fail(conn):
    qid = queue.enqueue(conn, {"transcript": "t", "project": "p1", "agent": "x"})
    worker.process_pending(conn, primary=StubCapturer(fail=True), fallback=StubCapturer(fail=True))
    row = conn.execute("SELECT status FROM capture_queue WHERE id=?", (qid,)).fetchone()
    assert row[0] == "failed"
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_worker.py -v` → FAIL

- [ ] **Step 3: 写 src/memhub/worker.py**

```python
"""Background worker: drain capture_queue through a Capturer into storage."""
import json
import time
import sqlite3
from . import queue, store, db as db_mod

def process_pending(conn: sqlite3.Connection, primary, fallback, limit: int = 10) -> int:
    """Process up to `limit` queued items. Returns count processed (done)."""
    done = 0
    for qid, payload_json in queue.claim_pending(conn, limit):
        payload = json.loads(payload_json)
        transcript = payload.get("transcript", "")
        meta = {"project": payload.get("project"), "agent": payload.get("agent"),
                "session_id": payload.get("session_id")}
        try:
            items = _capture_with_fallback(transcript, meta, primary, fallback)
        except Exception:
            queue.mark_failed(conn, qid)
            continue
        for it in items:
            store.store_memory(
                conn, content=it["content"], project=meta["project"], agent=meta["agent"],
                kind=it.get("kind", "raw"), tags=it.get("tags", []),
                scope=it.get("scope", "current"), session_id=meta["session_id"],
            )
        queue.mark_done(conn, qid)
        done += 1
    return done

def _capture_with_fallback(transcript, meta, primary, fallback) -> list[dict]:
    try:
        return primary.capture(transcript, meta)
    except Exception:
        return fallback.capture(transcript, meta)  # may raise -> caller marks failed

def run_loop(db_path, primary, fallback, interval: float = 5.0, stop=None) -> None:
    """Poll the queue forever (or until stop() is truthy). Each tick uses its own connection."""
    while not (stop and stop()):
        conn = db_mod.connect(db_path)
        try:
            process_pending(conn, primary, fallback)
        finally:
            conn.close()
        time.sleep(interval)
```

- [ ] **Step 4: 跑测试确认通过** — `./.venv/bin/pytest tests/test_worker.py -v` → 3 passed

- [ ] **Step 5: 提交** — `git add src/memhub/worker.py tests/test_worker.py && git commit -m "feat: worker process_pending with fallback + run_loop"`

---

## Task 5: server.py 改 — /capture 入队 + 起 worker 线程

**Files:** Modify `src/memhub/server.py`; Modify `tests/test_server.py`

- [ ] **Step 1: 改 tests/test_server.py 的 capture 测试为"入队语义"**

把原 `test_capture_then_search` 替换为(capture 现在只入队,不立即可搜):
```python
def test_capture_enqueues(tmp_path):
    client, db_path = _client(tmp_path)
    r = client.post("/capture", json={"transcript": "decided to use JWT", "project": "p1", "agent": "claude-code"})
    assert r.status_code == 200
    assert "queued" in r.json()
    # item is in the queue, not yet in memories
    conn = db_mod.connect(db_path)
    assert conn.execute("SELECT count(*) FROM capture_queue WHERE status='pending'").fetchone()[0] == 1
    conn.close()
```
(保留 `test_health_ok`、`test_capture_malformed_json_returns_400`、`test_search_bad_limit_returns_400`。)

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_server.py -v` → `test_capture_enqueues` FAIL (still returns `stored`)

- [ ] **Step 3: 改 server.py 的 `/capture` 处理器为入队**

把 `capture` custom_route 的 body 替换为(其余 server.py 不变):
```python
    @mcp.custom_route("/capture", methods=["POST"])
    async def capture(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        conn = db_mod.connect(db_path)
        try:
            qid = queue.enqueue(conn, {
                "transcript": body.get("transcript", ""),
                "project": body.get("project"),
                "agent": body.get("agent"),
                "session_id": body.get("session_id"),
            })
        except Exception as e:
            return JSONResponse({"queued": None, "error": str(e)}, status_code=200)
        finally:
            conn.close()
        return JSONResponse({"queued": qid})
```
并在 server.py 顶部 import 增加 `queue`:把 `from . import db as db_mod, store, search, config` 改为 `from . import db as db_mod, store, search, config, queue`。

- [ ] **Step 4: 改 `main()` 起后台 worker 线程**

把 `main()` 替换为:
```python
def main() -> None:
    import threading
    from .capture import LLMCapturer, RawCapturer
    c = db_mod.connect(config.DB_PATH)
    db_mod.init_schema(c)
    c.close()
    from . import worker
    t = threading.Thread(
        target=worker.run_loop,
        args=(config.DB_PATH, LLMCapturer(), RawCapturer()),
        daemon=True,
    )
    t.start()
    build_server(config.DB_PATH).run(transport="http", host=config.HOST, port=config.PORT)
```

- [ ] **Step 5: 跑全量测试** — `./.venv/bin/pytest -v` → all pass (含改写的 capture 测试)

- [ ] **Step 6: 端到端冒烟(真起服务 + 真 worker,但 mock 不了 claude——用 RawCapturer 路径验证)**

手动验证入队→worker→存储闭环(worker 用真 claude 会调订阅,这里只验管道连通):
```bash
cd ~/Code/memhub && rm -f /tmp/mhb.db /tmp/mhb.db-wal /tmp/mhb.db-shm && \
(MEMHUB_DB=/tmp/mhb.db ./.venv/bin/python -m memhub.server >/tmp/mhb.log 2>&1 &) && \
curl -s --retry-connrefused --retry 30 --retry-delay 1 localhost:37650/health && echo " <- health" && \
curl -s -X POST localhost:37650/capture -H "Content-Type: application/json" -d '{"transcript":"we decided to use JWT for auth","project":"smoke","agent":"cli"}' && echo " <- capture(queued)" && \
tail -8 /tmp/mhb.log && pkill -f memhub.server
```
Expected: `/health` ok、`/capture` 返回 `{"queued":N}`;worker 会尝试调 `claude -p`(真订阅)抽取——若环境有 claude 则几秒后入库,否则降级 Raw 入库。**冒烟只需确认服务起、入队返回、worker 线程没崩**(log 无 traceback)。

- [ ] **Step 7: 提交** — `git add src/memhub/server.py tests/test_server.py && git commit -m "feat: /capture enqueues, background worker drains queue"`

---

## 完成标准(计划 B1)

- `pytest` 全绿(新增 queue/capture/worker 测试 + 改写的 capture 入队测试)。
- `/capture` 入队即返回 `{"queued":id}`;后台 worker 线程把队列项经 LLMCapturer(失败降级 RawCapturer)→ store_memory 入库。
- 全程 mock claude 测试,不依赖真订阅;真服务冒烟验证管道连通。

**下一步(计划 B2):** Claude Code 的 SessionEnd hook(读 transcript → POST /capture)+ SessionStart hook(GET /search → 注入,且不覆盖已有 superpowers hook)+ launchd plist 常驻。
