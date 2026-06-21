# memhub 服务核心 Implementation Plan (Phase 1 · 计划 A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 memhub 服务核心——一个本地优先、能存能搜的共享记忆服务(REST + MCP 双口,混合检索,写入脱敏)。

**Architecture:** Python 单进程服务,FastMCP 提供 MCP(streamable HTTP)+ custom routes 提供 REST(`/health` `/search` `/capture`);SQLite(sqlite-vec 向量 + FTS5 关键词)存储;fastembed 本地 384 维 embedding;检索用 RRF 融合向量与关键词。核心逻辑(`db`/`embedding`/`redact`/`store`/`search`)与接口层(`server`)解耦,各自单测。

**Tech Stack:** Python 3.12 · FastMCP · sqlite-vec · fastembed(all-MiniLM-L6-v2 / 384) · pytest · httpx · 项目 venv

**范围说明:** 本计划只做"能存能搜的服务"。LLM 抽取、异步队列 worker、Claude Code hook、launchd 在计划 B。本计划的 `/capture` 先做**同步、原文切片**版本(RawCapturer),验证写入链路;异步队列留给计划 B。

---

## 文件结构

```
~/Code/memhub/
├── pyproject.toml              # 项目元信息 + 依赖
├── src/memhub/
│   ├── __init__.py
│   ├── config.py               # 端口/db路径/常量
│   ├── db.py                   # SQLite 连接 + sqlite-vec 加载 + schema
│   ├── embedding.py            # fastembed 封装(单例)
│   ├── redact.py               # 脱敏正则
│   ├── store.py                # 写入:去重 + embedding + 三表
│   ├── search.py               # 检索:向量 + FTS + RRF + scope 过滤
│   └── server.py               # FastMCP:MCP 工具 + REST custom routes + 启动入口
└── tests/
    ├── conftest.py             # 临时 db fixture
    ├── test_db.py
    ├── test_embedding.py
    ├── test_redact.py
    ├── test_store.py
    ├── test_search.py
    └── test_server.py
```

每文件单一职责;`store`/`search` 依赖 `db`+`embedding`,`server` 组装它们。

---

## Task 1: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `src/memhub/__init__.py`
- Create: `src/memhub/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "memhub"
version = "0.1.0"
description = "Local-first shared memory hub for CLI AI agents"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=2.0",
    "fastembed>=0.4",
    "sqlite-vec>=0.1.6",
    "numpy>=1.26",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: 写 config.py**

```python
"""Central config: paths, port, constants."""
import os
from pathlib import Path

DB_PATH = Path(os.environ.get("MEMHUB_DB", Path.home() / ".memhub" / "memhub.db"))
HOST = os.environ.get("MEMHUB_HOST", "127.0.0.1")
PORT = int(os.environ.get("MEMHUB_PORT", "37650"))
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
RRF_K = 60  # reciprocal-rank-fusion constant
DEFAULT_LIMIT = 10
```

- [ ] **Step 3: 写空的 `src/memhub/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: 创建 venv 并安装**

Run:
```bash
cd ~/Code/memhub && python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
```
Expected: 安装成功,结尾 `Successfully installed ... memhub-0.1.0 ...`

- [ ] **Step 5: 写 tests/test_config.py(冒烟测试)**

```python
from memhub import config

def test_config_defaults():
    assert config.EMBED_DIM == 384
    assert config.PORT == 37650
    assert config.RRF_K == 60
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
cd ~/Code/memhub && git add pyproject.toml src tests && git commit -m "chore: scaffold memhub project"
```

---

## Task 2: 存储层 db.py (schema 初始化)

**Files:**
- Create: `src/memhub/db.py`
- Create: `tests/conftest.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 写 tests/conftest.py(临时 db fixture)**

```python
import pytest
from memhub import db as db_mod

@pytest.fixture
def conn(tmp_path):
    c = db_mod.connect(tmp_path / "test.db")
    db_mod.init_schema(c)
    yield c
    c.close()
```

- [ ] **Step 2: 写 tests/test_db.py(失败测试)**

```python
def test_init_schema_creates_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "memories" in names
    assert "memories_fts" in names
    assert "capture_queue" in names

def test_vec_table_usable(conn):
    # vec0 virtual table accepts a 384-dim insert
    import struct
    vec = struct.pack("%sf" % 384, *([0.1] * 384))
    conn.execute("INSERT INTO memories_vec(memory_id, embedding) VALUES (1, ?)", (vec,))
    conn.commit()
    n = conn.execute("SELECT count(*) FROM memories_vec").fetchone()[0]
    assert n == 1
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_db.py -v`
Expected: FAIL (`AttributeError: module 'memhub.db' has no attribute 'connect'`)

- [ ] **Step 4: 写 db.py**

```python
"""SQLite connection + sqlite-vec loading + schema."""
import sqlite3
from pathlib import Path
import sqlite_vec
from . import config

def connect(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY,
        content TEXT NOT NULL,
        content_hash TEXT UNIQUE NOT NULL,
        kind TEXT NOT NULL DEFAULT 'raw',
        project TEXT,
        agent TEXT,
        tags TEXT DEFAULT '[]',
        scope TEXT NOT NULL DEFAULT 'current',
        session_id TEXT,
        created_at INTEGER NOT NULL
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
        memory_id INTEGER PRIMARY KEY,
        embedding float[{config.EMBED_DIM}]
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        content, tokenize='porter unicode61'
    );
    CREATE TABLE IF NOT EXISTS capture_queue (
        id INTEGER PRIMARY KEY,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL
    );
    """)
    conn.commit()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_db.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: 提交**

```bash
cd ~/Code/memhub && git add src/memhub/db.py tests/conftest.py tests/test_db.py && git commit -m "feat: sqlite schema with vec + fts tables"
```

---

## Task 3: embedding.py (fastembed 封装)

**Files:**
- Create: `src/memhub/embedding.py`
- Test: `tests/test_embedding.py`

- [ ] **Step 1: 写 tests/test_embedding.py(失败测试)**

```python
from memhub import embedding, config

def test_embed_returns_correct_dim():
    vec = embedding.embed("hello world")
    assert len(vec) == config.EMBED_DIM

def test_embed_is_deterministic():
    a = embedding.embed("same text")
    b = embedding.embed("same text")
    assert a == b
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_embedding.py -v`
Expected: FAIL (`AttributeError: module 'memhub.embedding' has no attribute 'embed'`)

- [ ] **Step 3: 写 embedding.py**

```python
"""Local embedding via fastembed (lazy singleton)."""
from functools import lru_cache
from fastembed import TextEmbedding
from . import config

@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(model_name=config.EMBED_MODEL)

def embed(text: str) -> list[float]:
    vec = next(iter(_model().embed([text])))
    return [float(x) for x in vec]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_embedding.py -v`
Expected: PASS (首次会下载 ~90MB 模型,可能慢)

- [ ] **Step 5: 提交**

```bash
cd ~/Code/memhub && git add src/memhub/embedding.py tests/test_embedding.py && git commit -m "feat: local fastembed embedding wrapper"
```

---

## Task 4: redact.py (脱敏)

**Files:**
- Create: `src/memhub/redact.py`
- Test: `tests/test_redact.py`

- [ ] **Step 1: 写 tests/test_redact.py(失败测试)**

```python
from memhub.redact import redact

def test_redacts_openai_key():
    assert "sk-" not in redact("token is sk-abc123DEF456ghi789jkl012mno345")

def test_redacts_github_token():
    assert "ghp_" not in redact("ghp_1234567890abcdefABCDEF1234567890abcd")

def test_redacts_password_assignment():
    assert "hunter2" not in redact("password=hunter2")

def test_keeps_normal_text():
    assert redact("we chose JWT for auth") == "we chose JWT for auth"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_redact.py -v`
Expected: FAIL (`ModuleNotFoundError` / no attribute `redact`)

- [ ] **Step 3: 写 redact.py**

```python
"""Redact secret-like strings before persisting."""
import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)(password|passwd|secret|token)\s*[=:]\s*\S+"),
]
_REPL = "[REDACTED]"

def redact(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub(_REPL, text)
    return text
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_redact.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 提交**

```bash
cd ~/Code/memhub && git add src/memhub/redact.py tests/test_redact.py && git commit -m "feat: secret redaction before persistence"
```

---

## Task 5: store.py (写入)

**Files:**
- Create: `src/memhub/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: 写 tests/test_store.py(失败测试)**

```python
from memhub import store

def test_store_inserts_one(conn):
    mid = store.store_memory(conn, content="use JWT for auth", project="p1", agent="claude-code")
    row = conn.execute("SELECT content, kind, project, scope FROM memories WHERE id=?", (mid,)).fetchone()
    assert row[0] == "use JWT for auth"
    assert row[2] == "p1"
    # vec + fts rows exist
    assert conn.execute("SELECT count(*) FROM memories_vec WHERE memory_id=?", (mid,)).fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM memories_fts WHERE rowid=?", (mid,)).fetchone()[0] == 1

def test_store_dedupes_identical_content(conn):
    a = store.store_memory(conn, content="same fact", project="p1", agent="x")
    b = store.store_memory(conn, content="same fact", project="p1", agent="x")
    assert a == b  # returns existing id, no duplicate
    assert conn.execute("SELECT count(*) FROM memories").fetchone()[0] == 1

def test_store_redacts_secret(conn):
    mid = store.store_memory(conn, content="key sk-abcdefghijklmnopqrstuvwx", project="p", agent="x")
    content = conn.execute("SELECT content FROM memories WHERE id=?", (mid,)).fetchone()[0]
    assert "sk-" not in content
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL (no attribute `store_memory`)

- [ ] **Step 3: 写 store.py**

```python
"""Write path: redact -> dedupe -> embed -> insert into 3 tables."""
import hashlib
import json
import struct
import time
import sqlite3
from . import embedding
from .redact import redact

def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def _pack(vec: list[float]) -> bytes:
    return struct.pack("%sf" % len(vec), *vec)

def store_memory(
    conn: sqlite3.Connection,
    content: str,
    project: str | None = None,
    agent: str | None = None,
    kind: str = "raw",
    tags: list[str] | None = None,
    scope: str = "current",
    session_id: str | None = None,
) -> int:
    content = redact(content)
    h = _hash(content)
    existing = conn.execute("SELECT id FROM memories WHERE content_hash=?", (h,)).fetchone()
    if existing:
        return existing[0]

    cur = conn.execute(
        """INSERT INTO memories (content, content_hash, kind, project, agent, tags, scope, session_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (content, h, kind, project, agent, json.dumps(tags or []), scope, session_id, int(time.time())),
    )
    mid = cur.lastrowid
    conn.execute(
        "INSERT INTO memories_vec(memory_id, embedding) VALUES (?, ?)",
        (mid, _pack(embedding.embed(content))),
    )
    conn.execute("INSERT INTO memories_fts(rowid, content) VALUES (?, ?)", (mid, content))
    conn.commit()
    return mid
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_store.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
cd ~/Code/memhub && git add src/memhub/store.py tests/test_store.py && git commit -m "feat: store_memory with dedupe, embedding, redaction"
```

---

## Task 6: search.py (混合检索)

**Files:**
- Create: `src/memhub/search.py`
- Test: `tests/test_search.py`

- [ ] **Step 1: 写 tests/test_search.py(失败测试)**

```python
from memhub import store, search

def _seed(conn):
    store.store_memory(conn, "authentication uses JWT tokens", project="p1", agent="x", scope="current")
    store.store_memory(conn, "we deploy with docker compose", project="p1", agent="x", scope="current")
    store.store_memory(conn, "python list comprehension tips", project="p2", agent="x", scope="global")

def test_semantic_search_ranks_relevant_first(conn):
    _seed(conn)
    results = search.search(conn, query="how do we log users in", project="p1", scope="all")
    assert results, "expected at least one result"
    assert "JWT" in results[0]["content"]

def test_scope_filter_excludes_other_project(conn):
    _seed(conn)
    results = search.search(conn, query="anything", project="p1", scope="current")
    projects = {r["project"] for r in results}
    assert projects <= {"p1"}

def test_global_scope_included(conn):
    _seed(conn)
    results = search.search(conn, query="python tips", project="p1", scope="current,global")
    contents = " ".join(r["content"] for r in results)
    assert "comprehension" in contents
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_search.py -v`
Expected: FAIL (no attribute `search`)

- [ ] **Step 3: 写 search.py**

```python
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
    if "current" in parts and project:
        conds.append("project = ?")
        params.append(project)
    if "global" in parts:
        conds.append("scope = 'global'")
    clause = "(" + " OR ".join(conds) + ")" if conds else "1=1"
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_search.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
cd ~/Code/memhub && git add src/memhub/search.py tests/test_search.py && git commit -m "feat: hybrid search (vector + fts, RRF) with scope filter"
```

---

## Task 7: server.py (REST + MCP 接口)

**Files:**
- Create: `src/memhub/server.py`
- Test: `tests/test_server.py`

- [ ] **Step 1: 写 tests/test_server.py(失败测试,用 Starlette TestClient 测 REST routes)**

```python
from starlette.testclient import TestClient
from memhub import server, db as db_mod

def _client(tmp_path):
    conn = db_mod.connect(tmp_path / "srv.db")
    db_mod.init_schema(conn)
    app = server.build_app(conn)        # returns the Starlette ASGI app
    return TestClient(app), conn

def test_health_ok(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_capture_then_search(tmp_path):
    client, _ = _client(tmp_path)
    cap = client.post("/capture", json={
        "transcript": "decided to use JWT for authentication",
        "project": "p1", "agent": "claude-code", "session_id": "s1"})
    assert cap.status_code == 200
    res = client.get("/search", params={"query": "auth login", "project": "p1", "scope": "all"})
    assert res.status_code == 200
    assert any("JWT" in m["content"] for m in res.json()["results"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_server.py -v`
Expected: FAIL (no attribute `build_app`)

- [ ] **Step 3: 写 server.py**

```python
"""FastMCP server: MCP tools + REST custom routes + startup entry."""
import sqlite3
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastmcp import FastMCP
from . import db as db_mod, store, search, config

def build_server(conn: sqlite3.Connection) -> FastMCP:
    mcp = FastMCP("memhub")

    @mcp.tool
    def search_memories(query: str, scope: str = "current,global",
                        kind: str | None = None, project: str | None = None,
                        limit: int = config.DEFAULT_LIMIT) -> list[dict]:
        """Search shared memory (hybrid vector + keyword)."""
        return search.search(conn, query, project=project, scope=scope, kind=kind, limit=limit)

    @mcp.tool
    def store_note(content: str, tags: list[str] | None = None,
                   scope: str = "current", project: str | None = None) -> dict:
        """Store a memory note explicitly."""
        mid = store.store_memory(conn, content=content, project=project,
                                 agent="manual", kind="note", tags=tags, scope=scope)
        return {"id": mid}

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/capture", methods=["POST"])
    async def capture(request: Request) -> JSONResponse:
        body = await request.json()
        transcript = body.get("transcript", "")
        # MVP: synchronous raw capture (RawCapturer); async LLM queue is Plan B.
        mid = store.store_memory(
            conn, content=transcript, project=body.get("project"),
            agent=body.get("agent"), kind="raw", scope="current",
            session_id=body.get("session_id"),
        )
        return JSONResponse({"stored": [mid]})

    @mcp.custom_route("/search", methods=["GET"])
    async def search_route(request: Request) -> JSONResponse:
        q = request.query_params
        results = search.search(
            conn, q.get("query", ""), project=q.get("project"),
            scope=q.get("scope", "current,global"),
            kind=q.get("kind"), limit=int(q.get("limit", config.DEFAULT_LIMIT)),
        )
        return JSONResponse({"results": results})

    return mcp

def build_app(conn: sqlite3.Connection):
    """ASGI app for testing and embedding."""
    return build_server(conn).http_app()

def main() -> None:
    conn = db_mod.connect()
    db_mod.init_schema(conn)
    build_server(conn).run(transport="http", host=config.HOST, port=config.PORT)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest tests/test_server.py -v`
Expected: PASS (2 passed)

> 若 `http_app()` / `custom_route` 的方法名与当前 FastMCP 版本不符,查 `./.venv/bin/python -c "import fastmcp; help(fastmcp.FastMCP)"` 对齐(FastMCP 2.x:`http_app()` 返回 Starlette app;`@mcp.custom_route` 注册 REST 路由)。

- [ ] **Step 5: 全量测试 + 手动起服务冒烟**

Run: `cd ~/Code/memhub && ./.venv/bin/pytest -v`
Expected: 全部 PASS

Run: `cd ~/Code/memhub && ./.venv/bin/python -m memhub.server &` 然后 `curl -s localhost:37650/health`
Expected: `{"status":"ok"}`;冒烟后 `kill %1`

- [ ] **Step 6: 提交**

```bash
cd ~/Code/memhub && git add src/memhub/server.py tests/test_server.py && git commit -m "feat: FastMCP server with MCP tools + REST routes"
```

---

## 完成标准(计划 A)

- `pytest` 全绿;`python -m memhub.server` 起得来,`/health` 返回 ok。
- 能 `POST /capture` 存一段文本、`GET /search` 搜回来(REST);MCP `search_memories` / `store_note` 可用。
- 纯本地、零 key、写入脱敏。

**下一步(计划 B):** LLM 抽取(`claude -p`)替换同步 RawCapturer、异步队列 worker、Claude Code SessionEnd/SessionStart hook、launchd 常驻。
