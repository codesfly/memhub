# memhub 记忆管理(web viewer + CLI)Implementation Plan (Phase 3 · C1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 给 memhub 加查看/管理记忆的两种方式——一个本地 web viewer(列表/搜索/过滤/删除)和一个 `memhub` CLI(list/search/delete)。

**Architecture:** 后端在现有 FastMCP 服务上新增 `GET /memories`(列表+过滤+分页)、`DELETE /memories/{id}`、`GET /ui`(内联 HTML 页);`store.py` 加 `list_memories` + `delete_memory`(删三表)。web viewer 是单页内联 HTML+原生 JS(无构建)。CLI 是服务的瘦 REST 客户端(`urllib`,零新依赖),经 `[project.scripts]` 暴露为 `memhub`。删除=硬删;web 与 CLI 都走 REST,后端是唯一真相;服务核心不改,只新增。

**Tech Stack:** 复用现有栈,无新依赖(HTML/JS 内联,CLI 用标准库 `argparse`+`urllib`)。

**前置:** Plan A/B1/B2 已合 main。本计划在分支 `feat/management` 上做。

---

## 文件结构

```
src/memhub/
├── store.py    # 加:list_memories / delete_memory
├── server.py   # 加:GET /memories · DELETE /memories/{id} · GET /ui
├── ui.py       # 新:web viewer 的 HTML(单页内联 JS)
└── cli.py      # 新:memhub list/search/delete(REST 瘦客户端)
pyproject.toml  # 加:[project.scripts] memhub = "memhub.cli:main"
tests/
├── test_manage.py  # list_memories/delete_memory + /memories + DELETE + /ui
└── test_cli.py     # CLI 命令(mock urllib)
```

---

## Task 1: store — list_memories + delete_memory

**Files:** Modify `src/memhub/store.py`; Test `tests/test_manage.py`

- [ ] **Step 1: 写 tests/test_manage.py**

```python
from memhub import store

def test_list_memories_orders_newest_first(conn):
    a = store.store_memory(conn, "first", project="p1", agent="x")
    b = store.store_memory(conn, "second", project="p1", agent="x")
    items = store.list_memories(conn, project="p1")
    assert [m["id"] for m in items] == [b, a]  # newest first

def test_list_memories_filters_and_paginates(conn):
    store.store_memory(conn, "d1", project="p1", agent="x", kind="decision")
    store.store_memory(conn, "f1", project="p1", agent="x", kind="fact")
    store.store_memory(conn, "d2", project="p2", agent="x", kind="decision")
    assert all(m["kind"] == "decision" for m in store.list_memories(conn, kind="decision"))
    assert all(m["project"] == "p1" for m in store.list_memories(conn, project="p1"))
    assert len(store.list_memories(conn, limit=1)) == 1

def test_delete_memory_removes_from_all_tables(conn):
    mid = store.store_memory(conn, "to delete", project="p1", agent="x")
    assert store.delete_memory(conn, mid) is True
    assert conn.execute("SELECT count(*) FROM memories WHERE id=?", (mid,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM memories_vec WHERE memory_id=?", (mid,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM memories_fts WHERE rowid=?", (mid,)).fetchone()[0] == 0

def test_delete_missing_returns_false(conn):
    assert store.delete_memory(conn, 99999) is False
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_manage.py -v`

- [ ] **Step 3: 在 store.py 末尾加两个函数**

```python
def list_memories(conn, project=None, kind=None, limit=50, offset=0):
    conds, params = [], []
    if project:
        conds.append("project = ?"); params.append(project)
    if kind:
        conds.append("kind = ?"); params.append(kind)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    sql = (f"SELECT id, content, kind, project, agent, scope, created_at "
           f"FROM memories{where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?")
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    return [{"id": r[0], "content": r[1], "kind": r[2], "project": r[3],
             "agent": r[4], "scope": r[5], "created_at": r[6]} for r in rows]

def delete_memory(conn, mid) -> bool:
    cur = conn.execute("DELETE FROM memories WHERE id=?", (mid,))
    conn.execute("DELETE FROM memories_vec WHERE memory_id=?", (mid,))
    conn.execute("DELETE FROM memories_fts WHERE rowid=?", (mid,))
    conn.commit()
    return cur.rowcount > 0
```

- [ ] **Step 4: 跑测试确认通过** — `./.venv/bin/pytest tests/test_manage.py -v` → 4 passed

- [ ] **Step 5: 提交** — `cd ~/Code/memhub && git add src/memhub/store.py tests/test_manage.py && git commit -m "feat: list_memories + delete_memory"`

---

## Task 2: server — GET /memories + DELETE /memories/{id}

**Files:** Modify `src/memhub/server.py`; Modify `tests/test_manage.py`

- [ ] **Step 1: 追加测试到 tests/test_manage.py**

```python
from starlette.testclient import TestClient
from memhub import server, db as db_mod

def _client(tmp_path):
    db_path = tmp_path / "m.db"
    c = db_mod.connect(db_path); db_mod.init_schema(c); c.close()
    return TestClient(server.build_app(db_path)), db_path

def test_memories_endpoint_lists(tmp_path):
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    store.store_memory(conn, "hello world", project="p1", agent="x")
    conn.close()
    r = client.get("/memories", params={"project": "p1"})
    assert r.status_code == 200
    assert any("hello world" in m["content"] for m in r.json()["memories"])

def test_memories_bad_limit_400(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/memories", params={"limit": "abc"}).status_code == 400

def test_delete_endpoint(tmp_path):
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    mid = store.store_memory(conn, "delete me", project="p1", agent="x")
    conn.close()
    assert client.delete(f"/memories/{mid}").status_code == 200
    assert client.delete(f"/memories/{mid}").status_code == 404  # already gone
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_manage.py -v`

- [ ] **Step 3: 在 server.py 的 `/inject` 路由之后、`return mcp` 之前加两个路由**

```python
    @mcp.custom_route("/memories", methods=["GET"])
    async def list_memories_route(request: Request) -> JSONResponse:
        q = request.query_params
        try:
            limit = int(q.get("limit", 50)); offset = int(q.get("offset", 0))
        except (TypeError, ValueError):
            return JSONResponse({"error": "limit/offset must be integers"}, status_code=400)
        conn = db_mod.connect(db_path)
        try:
            items = store.list_memories(conn, project=q.get("project"),
                                        kind=q.get("kind"), limit=limit, offset=offset)
        finally:
            conn.close()
        return JSONResponse({"memories": items})

    @mcp.custom_route("/memories/{mid:int}", methods=["DELETE"])
    async def delete_memory_route(request: Request) -> JSONResponse:
        mid = request.path_params["mid"]
        conn = db_mod.connect(db_path)
        try:
            ok = store.delete_memory(conn, mid)
        finally:
            conn.close()
        return JSONResponse({"deleted": ok}, status_code=200 if ok else 404)
```

- [ ] **Step 4: 跑测试确认通过 + 全量** — `./.venv/bin/pytest -q` → all pass

- [ ] **Step 5: 提交** — `cd ~/Code/memhub && git add src/memhub/server.py tests/test_manage.py && git commit -m "feat: REST /memories list + delete endpoints"`

---

## Task 3: server — GET /ui (web viewer)

**Files:** Create `src/memhub/ui.py`; Modify `src/memhub/server.py`; Modify `tests/test_manage.py`

- [ ] **Step 1: 追加测试到 tests/test_manage.py**

```python
def test_ui_serves_html(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/ui")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "memhub" in r.text and "fetch(" in r.text  # the page + its JS
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_manage.py::test_ui_serves_html -v`

- [ ] **Step 3: 写 src/memhub/ui.py**

```python
"""Single-page web viewer (inline HTML + vanilla JS, no build step)."""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>memhub</title>
<style>
 body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
 header{padding:14px 20px;background:#161a22;border-bottom:1px solid #262b36;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 h1{font-size:16px;margin:0 12px 0 0;color:#7aa2f7}
 input,select{background:#0f1115;color:#e6e6e6;border:1px solid #2a3140;border-radius:6px;padding:6px 9px;font-size:13px}
 input[type=search]{flex:1;min-width:180px}
 main{padding:16px 20px;max-width:900px;margin:0 auto}
 .card{background:#161a22;border:1px solid #262b36;border-radius:8px;padding:12px 14px;margin:10px 0}
 .meta{font-size:12px;color:#8b93a7;display:flex;gap:10px;margin-bottom:6px;align-items:center;flex-wrap:wrap}
 .kind{padding:1px 7px;border-radius:10px;background:#1f2937;color:#9ece6a;font-size:11px}
 .content{white-space:pre-wrap;word-break:break-word}
 .del{margin-left:auto;background:none;border:1px solid #3a2230;color:#f7768e;border-radius:6px;padding:3px 9px;cursor:pointer}
 .del:hover{background:#2a1620}
 .empty{color:#8b93a7;text-align:center;padding:40px}
</style></head>
<body>
<header>
 <h1>memhub</h1>
 <input id="q" type="search" placeholder="search memories…">
 <input id="project" placeholder="project filter">
 <select id="kind">
  <option value="">all kinds</option>
  <option>decision</option><option>fact</option><option>convention</option>
  <option>snippet</option><option>note</option><option>raw</option>
 </select>
</header>
<main id="list"><div class="empty">loading…</div></main>
<script>
const el = id => document.getElementById(id);
const esc = s => (s||"").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function load(){
 const q = el('q').value.trim(), project = el('project').value.trim(), kind = el('kind').value;
 let url, key;
 if(q){ url = `/search?query=${encodeURIComponent(q)}&scope=all&limit=100`; key='results'; }
 else { const p=new URLSearchParams(); if(project)p.set('project',project); if(kind)p.set('kind',kind); p.set('limit','100'); url=`/memories?${p}`; key='memories'; }
 let data; try{ data = await (await fetch(url)).json(); }catch(e){ el('list').innerHTML='<div class="empty">service unreachable</div>'; return; }
 let items = data[key]||[];
 if(q && kind) items = items.filter(m=>m.kind===kind);
 if(q && project) items = items.filter(m=>m.project===project);
 if(!items.length){ el('list').innerHTML='<div class="empty">no memories</div>'; return; }
 el('list').innerHTML = items.map(m=>`<div class="card">
   <div class="meta"><span class="kind">${esc(m.kind)}</span>
     <span>${esc(m.project||'—')}</span><span>${esc(m.agent||'')}</span>
     <span>${new Date((m.created_at||0)*1000).toLocaleString()}</span>
     <button class="del" data-id="${m.id}">delete</button></div>
   <div class="content">${esc(m.content)}</div></div>`).join('');
 document.querySelectorAll('.del').forEach(b=>b.onclick=async()=>{
   if(!confirm('Delete this memory?'))return;
   await fetch(`/memories/${b.dataset.id}`,{method:'DELETE'}); load();
 });
}
['q','project','kind'].forEach(id=>el(id).addEventListener('input',()=>{clearTimeout(window._t);window._t=setTimeout(load,250)}));
load();
</script>
</body></html>"""
```

- [ ] **Step 4: 在 server.py 加 `/ui` 路由 + import**

(a) import 区加:`from starlette.responses import JSONResponse, HTMLResponse` (在已有 `from starlette.responses import JSONResponse` 基础上加 `HTMLResponse`),并 `from . import ... ui`(加入 ui 模块)。
(b) 在 `/memories` 路由附近加:
```python
    @mcp.custom_route("/ui", methods=["GET"])
    async def ui_route(request: Request) -> HTMLResponse:
        return HTMLResponse(ui.PAGE)
```

- [ ] **Step 5: 跑测试确认通过 + 全量** — `./.venv/bin/pytest -q` → all pass

- [ ] **Step 6: 提交** — `cd ~/Code/memhub && git add src/memhub/ui.py src/memhub/server.py tests/test_manage.py && git commit -m "feat: web viewer at /ui"`

---

## Task 4: cli.py + entry point

**Files:** Create `src/memhub/cli.py`; Modify `pyproject.toml`; Test `tests/test_cli.py`

- [ ] **Step 1: 写 tests/test_cli.py(mock urllib)**

```python
import json
from unittest.mock import patch, MagicMock
from memhub import cli

def _resp(obj):
    m = MagicMock(); m.read.return_value = json.dumps(obj).encode()
    m.__enter__ = lambda s: m; m.__exit__ = lambda *a: False
    return m

def test_list_calls_memories_endpoint(capsys):
    with patch("memhub.cli.urlopen", return_value=_resp({"memories": [
        {"id": 1, "content": "hi", "kind": "fact", "project": "p1", "agent": "x", "created_at": 0}]})):
        cli.main(["list", "--project", "p1"])
    assert "hi" in capsys.readouterr().out

def test_search_calls_search_endpoint(capsys):
    with patch("memhub.cli.urlopen", return_value=_resp({"results": [
        {"id": 2, "content": "jwt auth", "kind": "decision", "project": "p1", "agent": "x", "created_at": 0}]})):
        cli.main(["search", "auth"])
    assert "jwt auth" in capsys.readouterr().out

def test_delete_calls_delete(capsys):
    with patch("memhub.cli.urlopen", return_value=_resp({"deleted": True})) as u:
        cli.main(["delete", "5", "--yes"])
    assert "deleted" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_cli.py -v`

- [ ] **Step 3: 写 src/memhub/cli.py**

```python
"""memhub CLI — thin REST client over the local service."""
import argparse
import json
import sys
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
    args = p.parse_args(argv)
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
    except (urllib.error.URLError, OSError):
        print(f"memhub service unreachable at {BASE} (is it running?)", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 在 pyproject.toml 的 `[project]` 表后加 entry point**

加入(若已有 `[project.scripts]` 则并入):
```toml
[project.scripts]
memhub = "memhub.cli:main"
```

- [ ] **Step 5: 跑测试 + 重装以注册命令** — `./.venv/bin/pytest tests/test_cli.py -v` → 3 passed;然后 `./.venv/bin/pip install -e . -q` 使 `memhub` 命令生效。

- [ ] **Step 6: 全量测试 + 提交** — `./.venv/bin/pytest -q` → all pass;`cd ~/Code/memhub && git add src/memhub/cli.py pyproject.toml tests/test_cli.py && git commit -m "feat: memhub CLI (list/search/delete)"`

---

## Task 5: 集成冒烟(真起服务 + web + CLI)

**Files:** none (验证)

- [ ] **Step 1: 起临时服务 + 验证 /ui 与 /memories**
```bash
cd ~/Code/memhub && rm -f /tmp/mhm.db /tmp/mhm.db-wal /tmp/mhm.db-shm && \
(MEMHUB_DB=/tmp/mhm.db ./.venv/bin/python -m memhub.server >/tmp/mhm.log 2>&1 &) && \
curl -s --retry-connrefused --retry 30 --retry-delay 1 localhost:37650/health && echo " <- health" && \
curl -s -X POST localhost:37650/capture -H "Content-Type: application/json" -d '{"transcript":"we use Postgres","project":"smoke","agent":"cli"}' >/dev/null && \
curl -s -o /dev/null -w "ui http=%{http_code}\n" localhost:37650/ui && \
curl -s "localhost:37650/memories?project=smoke" | head -c 200; echo
```
Expected: `/health` ok、`ui http=200`、`/memories` 返回 JSON(worker 抽取后才有内容,空也算端点通)。

- [ ] **Step 2: CLI 冒烟(对真服务)**
```bash
cd ~/Code/memhub && MEMHUB_PORT=37650 ./.venv/bin/memhub list --project smoke; ./.venv/bin/memhub search Postgres
```
Expected: 列出/搜到记忆(或 "(no memories)" 若 worker 还没抽完);命令不报错。

- [ ] **Step 3: 收尾** — `pkill -f memhub.server; rm -f /tmp/mhm.db /tmp/mhm.db-wal /tmp/mhm.db-shm`

---

## 完成标准(Phase 3 · C1)

- `store.list_memories` / `delete_memory`、REST `/memories`(GET)+ `/memories/{id}`(DELETE)+ `/ui`、`memhub` CLI(list/search/delete)均有测试且全绿。
- `localhost:37650/ui` 打开是可用的记忆浏览/删除页;`memhub list/search/delete` 命令可用。
- 服务核心未改动逻辑,仅新增端点 + 两个新模块。

**后续:** Phase 3 还剩 Ollama 离线 capturer、衰减/合并 consolidation。
