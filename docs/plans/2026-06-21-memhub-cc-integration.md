# memhub Claude Code 集成 Implementation Plan (Phase 1 · 计划 B2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 让 memhub 在 Claude Code 里真正自动工作:SessionEnd 时把会话 transcript 发去捕获,SessionStart 时把相关记忆注入上下文,并用 launchd 让服务常驻。

**Architecture:** 两个 Claude Code command hook(薄 shell)只传 `transcript_path`/`cwd` 给本地服务,**解析在服务端**。`transcript.py` 读 JSONL 提取 user/assistant 文本;`/capture` 接受 `transcript_path`(读+解析后入队);新增 `/inject` 端点把检索结果格式化成 `additionalContext`。launchd plist 常驻服务。安装脚本幂等地把 hooks append 进 `~/.claude/settings.json`(该文件当前无 `hooks` 字段,superpowers hook 是 plugin 级、不受影响)并装载 plist。

**Tech Stack:** 复用 Plan A/B1 栈 + bash hook 脚本 + launchd plist。

**关键事实(已核实):**
- hook stdin JSON 字段:`transcript_path` / `cwd` / `session_id` / `hook_event_name`;SessionEnd 另有 `reason`。
- SessionStart 注入格式:`{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"..."}}`(≤10000 字符,用陈述句)。SessionEnd 不能阻断 → 静默 `exit 0`。
- transcript JSONL:`type` ∈ {user, assistant, queue-operation, attachment, system, ...};user 的 `message.content` 是 **str**,assistant 的是 **list**(取 `{"type":"text"}` 块);其余 type 跳过。
- `settings.json` 当前**无 `hooks` 字段**;append memhub 的 SessionStart/SessionEnd 不与任何现有 user-hook 冲突。
- claude CLI 走 `settings.json` env 的代理认证;launchd 起服务要传 `HOME` 让 `claude -p` 能读到 settings.json。

---

## 文件结构

```
src/memhub/
├── transcript.py   # parse_transcript(path) -> str
└── server.py       # 改:/capture 接受 transcript_path;新增 /inject
hooks/
├── memhub-capture.sh   # SessionEnd: 传 transcript_path 给 /capture
└── memhub-inject.sh    # SessionStart: 取 /inject 注入 additionalContext
deploy/
├── com.memhub.plist    # launchd LaunchAgent 模板
└── install.py          # 幂等装 hooks 进 settings.json + 装 plist + load
tests/
├── test_transcript.py
└── test_inject.py      # /inject 端点 + /capture transcript_path
```

---

## Task 1: transcript.py(JSONL 解析)

**Files:** Create `src/memhub/transcript.py`; Test `tests/test_transcript.py`

- [ ] **Step 1: 写 tests/test_transcript.py**

```python
import json
from memhub.transcript import parse_transcript

def _write(tmp_path, rows):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return str(p)

def test_extracts_user_str_and_assistant_text(tmp_path):
    path = _write(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "how do I add auth"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "..."},
            {"type": "text", "text": "use JWT tokens"},
            {"type": "tool_use", "name": "Bash"},
        ]}},
        {"type": "queue-operation", "content": "ignored"},
        {"type": "system", "content": "ignored"},
    ])
    out = parse_transcript(path)
    assert "how do I add auth" in out
    assert "use JWT tokens" in out
    assert "ignored" not in out

def test_tolerates_bad_lines(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('not json\n{"type":"user","message":{"content":"ok"}}\n{bad}\n')
    out = parse_transcript(str(p))
    assert "ok" in out

def test_empty_returns_empty(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text("")
    assert parse_transcript(str(p)) == ""
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_transcript.py -v`

- [ ] **Step 3: 写 src/memhub/transcript.py**

```python
"""Parse a Claude Code transcript JSONL into plain user/assistant text."""
import json
from pathlib import Path

def parse_transcript(path: str) -> str:
    out = []
    try:
        raw = Path(path).read_text(errors="replace")
    except OSError:
        return ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        if t not in ("user", "assistant"):
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = " ".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        else:
            continue
        text = text.strip()
        if text:
            out.append(f"{t}: {text}")
    return "\n".join(out)
```

- [ ] **Step 4: 跑测试确认通过** — `./.venv/bin/pytest tests/test_transcript.py -v` → 3 passed

- [ ] **Step 5: 提交** — `cd ~/Code/memhub && git add src/memhub/transcript.py tests/test_transcript.py && git commit -m "feat: transcript JSONL parser"`

---

## Task 2: server — /capture 接受 transcript_path + /inject 端点

**Files:** Modify `src/memhub/server.py`; Create `tests/test_inject.py`

- [ ] **Step 1: 写 tests/test_inject.py**

```python
import json
from starlette.testclient import TestClient
from memhub import server, db as db_mod, store

def _client(tmp_path):
    db_path = tmp_path / "i.db"
    c = db_mod.connect(db_path); db_mod.init_schema(c); c.close()
    return TestClient(server.build_app(db_path)), db_path

def test_capture_accepts_transcript_path(tmp_path):
    # write a tiny transcript file
    tp = tmp_path / "t.jsonl"
    tp.write_text(json.dumps({"type": "user", "message": {"content": "we use JWT for auth"}}))
    client, db_path = _client(tmp_path)
    r = client.post("/capture", json={"transcript_path": str(tp), "project": "p1", "agent": "claude-code"})
    assert r.status_code == 200 and "queued" in r.json()
    # the enqueued payload should carry the PARSED text, not the path
    conn = db_mod.connect(db_path)
    payload = json.loads(conn.execute("SELECT payload FROM capture_queue").fetchone()[0])
    conn.close()
    assert "JWT" in payload["transcript"]

def test_inject_formats_memories(tmp_path):
    client, db_path = _client(tmp_path)
    conn = db_mod.connect(db_path)
    store.store_memory(conn, "auth uses JWT tokens", project="p1", agent="x", kind="decision", scope="current")
    conn.close()
    r = client.post("/inject", json={"project": "p1"})
    assert r.status_code == 200
    body = r.json()
    assert "context" in body
    assert "JWT" in body["context"]
    assert "memhub" in body["context"]

def test_inject_empty_when_no_memories(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/inject", json={"project": "nope"})
    assert r.status_code == 200
    assert r.json()["context"] == ""
```

- [ ] **Step 2: 跑测试确认失败** — `./.venv/bin/pytest tests/test_inject.py -v`

- [ ] **Step 3: 改 server.py**

(a) 顶部 import 增加 transcript:把 `from . import db as db_mod, store, search, config, queue` 改为 `from . import db as db_mod, store, search, config, queue, transcript`

(b) 替换 `/capture` 处理器,让它在有 `transcript_path` 时服务端解析:
```python
    @mcp.custom_route("/capture", methods=["POST"])
    async def capture(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        text = body.get("transcript", "")
        tp = body.get("transcript_path")
        if tp:
            text = transcript.parse_transcript(tp)
        conn = db_mod.connect(db_path)
        try:
            qid = queue.enqueue(conn, {
                "transcript": text,
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

(c) 在 `/search` 路由后、`return mcp` 前,新增 `/inject` 端点:
```python
    @mcp.custom_route("/inject", methods=["POST"])
    async def inject(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"context": ""}, status_code=200)
        project = body.get("project")
        conn = db_mod.connect(db_path)
        try:
            results = search.search(conn, query="", project=project,
                                    scope="current,global", limit=6)
        except Exception:
            return JSONResponse({"context": ""}, status_code=200)
        finally:
            conn.close()
        if not results:
            return JSONResponse({"context": ""})
        lines = [f"## 相关记忆 (memhub · {len(results)} 条)"]
        for r in results:
            snippet = r["content"].replace("\n", " ")[:160]
            lines.append(f"- [{r['kind']}] {snippet}")
        return JSONResponse({"context": "\n".join(lines)})
```

> 注:`/inject` 用空 query 做检索 → search 走向量/FTS 时空 query 会落到 FTS 空匹配 + 向量空匹配,可能返回空。MVP 可接受(注入"最近相关"靠后续 query 改进);本 task 只要"有记忆时格式化、无记忆时空串"。若空 query 导致 search 报错,test_inject_empty 会暴露——按需在 search 层兜底空 query 返回最近 N 条(用 `get_recent` 逻辑),但**不在本 task 扩范围**,先让测试通过(空 query 返回空 context 也算通过 test_inject_empty;test_inject_formats 需要至少能召回——若空 query 召不回,改用一个能匹配的非空 query 如 project 名,或在 search 加 "空 query → 返回该 project 最近 N 条" 的兜底,二选一并说明)。

- [ ] **Step 4: 跑测试确认通过(若 /inject 空 query 召回不到,实现 search 的空 query 兜底:空 query 时按 created_at desc 返回 project 内最近 limit 条)** — `./.venv/bin/pytest tests/test_inject.py -v`

- [ ] **Step 5: 全量测试** — `./.venv/bin/pytest -q` → all pass

- [ ] **Step 6: 提交** — `cd ~/Code/memhub && git add src/memhub/server.py src/memhub/search.py tests/test_inject.py && git commit -m "feat: /capture parses transcript_path, /inject formats memories"`

---

## Task 3: Claude Code hook 脚本

**Files:** Create `hooks/memhub-capture.sh`, `hooks/memhub-inject.sh`; Test `tests/test_hooks.sh`

- [ ] **Step 1: 写 hooks/memhub-capture.sh(SessionEnd,静默)**

```bash
#!/bin/bash
# memhub SessionEnd hook: send transcript_path to the local memory service.
# Never blocks the agent: all failures swallowed, always exit 0.
{
  INPUT=$(cat)
  TP=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty')
  CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
  SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty')
  [ -z "$TP" ] && exit 0
  curl -sS -X POST http://127.0.0.1:37650/capture \
    -H "Content-Type: application/json" \
    -d "$(jq -nc --arg tp "$TP" --arg p "$CWD" --arg s "$SID" \
        '{transcript_path:$tp, project:$p, agent:"claude-code", session_id:$s}')" \
    --max-time 5 >/dev/null 2>&1
} >/dev/null 2>&1 || true
exit 0
```

- [ ] **Step 2: 写 hooks/memhub-inject.sh(SessionStart,快、静默)**

```bash
#!/bin/bash
# memhub SessionStart hook: inject relevant memories as additionalContext.
# Fast + silent: short timeout, any failure -> no output, exit 0.
INPUT=$(cat)
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && exit 0
RESP=$(curl -sS -X POST http://127.0.0.1:37650/inject \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg p "$CWD" '{project:$p}')" \
  --max-time 3 2>/dev/null) || exit 0
CTX=$(printf '%s' "$RESP" | jq -r '.context // empty' 2>/dev/null)
[ -z "$CTX" ] && exit 0
jq -nc --arg ctx "$CTX" \
  '{hookSpecificOutput:{hookEventName:"SessionStart", additionalContext:$ctx}}'
exit 0
```

- [ ] **Step 3: chmod + 写一个冒烟测试 tests/test_hooks.sh**

```bash
#!/bin/bash
# Verify hooks don't crash and stay silent when the service is down.
set -e
chmod +x hooks/memhub-capture.sh hooks/memhub-inject.sh
# capture hook: bad/empty input -> exit 0, no output
echo '{}' | ./hooks/memhub-capture.sh
echo '{"transcript_path":"/nonexistent","cwd":"/tmp","session_id":"s"}' | ./hooks/memhub-capture.sh
# inject hook with service down -> exit 0, empty stdout
OUT=$(echo '{"cwd":"/tmp"}' | ./hooks/memhub-inject.sh)
test -z "$OUT" || { echo "inject should be silent when service down, got: $OUT"; exit 1; }
echo "hooks smoke OK"
```

- [ ] **Step 4: 跑冒烟** — `cd ~/Code/memhub && chmod +x hooks/*.sh tests/test_hooks.sh && bash tests/test_hooks.sh`
Expected: `hooks smoke OK`(需要 `jq`/`curl`,macOS 默认有 curl;jq 若缺用 `brew install jq`——若环境无 jq,报 DONE_WITH_CONCERNS 说明)

- [ ] **Step 5: 提交** — `cd ~/Code/memhub && git add hooks tests/test_hooks.sh && git commit -m "feat: Claude Code capture/inject hook scripts"`

---

## Task 4: launchd plist + 安装脚本

**Files:** Create `deploy/com.memhub.plist`, `deploy/install.py`; Test `tests/test_install.py`

- [ ] **Step 1: 写 deploy/com.memhub.plist(模板,`__PYTHON__`/`__HOME__` 占位由 install 替换)**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.memhub.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>__PYTHON__</string>
    <string>-m</string>
    <string>memhub.server</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>HOME</key><string>__HOME__</string></dict>
  <key>WorkingDirectory</key><string>__HOME__/Code/memhub</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>__HOME__/.memhub/memhub.log</string>
  <key>StandardErrorPath</key><string>__HOME__/.memhub/memhub.err</string>
</dict>
</plist>
```

- [ ] **Step 2: 写 tests/test_install.py(测 settings.json merge 逻辑,幂等)**

```python
import json
from memhub_install import merge_hooks  # install.py exposes merge_hooks

def test_merge_adds_hooks_to_empty(tmp_path):
    settings = {}
    out = merge_hooks(settings, "/x/capture.sh", "/x/inject.sh")
    assert any("inject.sh" in h["hooks"][0]["command"] for h in out["hooks"]["SessionStart"])
    assert any("capture.sh" in h["hooks"][0]["command"] for h in out["hooks"]["SessionEnd"])

def test_merge_preserves_existing_hooks(tmp_path):
    settings = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "other.sh"}]}]}}
    out = merge_hooks(settings, "/x/capture.sh", "/x/inject.sh")
    cmds = [h["hooks"][0]["command"] for h in out["hooks"]["SessionStart"]]
    assert "other.sh" in cmds        # preserved
    assert any("inject.sh" in c for c in cmds)  # added

def test_merge_is_idempotent(tmp_path):
    settings = {}
    once = merge_hooks(settings, "/x/capture.sh", "/x/inject.sh")
    twice = merge_hooks(json.loads(json.dumps(once)), "/x/capture.sh", "/x/inject.sh")
    assert len(twice["hooks"]["SessionStart"]) == len(once["hooks"]["SessionStart"])  # no dup
```

> Note: test imports `memhub_install`; add `conftest.py` sys.path insert for `deploy/`, OR place install.py importably. Simplest: in test file do `import sys; sys.path.insert(0, "deploy")` before importing, and name the module `install.py` → `import install as memhub_install`. Adjust the import line to whatever works; the 3 behaviors above are what matter.

- [ ] **Step 3: 跑测试确认失败**

- [ ] **Step 4: 写 deploy/install.py**

```python
"""Idempotently install memhub hooks into ~/.claude/settings.json and load launchd."""
import json
import shutil
import sys
import subprocess
from pathlib import Path

HOME = Path.home()
SETTINGS = HOME / ".claude" / "settings.json"
HOOKS_DIR = HOME / "Code" / "memhub" / "hooks"
CAPTURE = str(HOOKS_DIR / "memhub-capture.sh")
INJECT = str(HOOKS_DIR / "memhub-inject.sh")

def _has(entries, needle):
    return any(needle in h.get("command", "")
               for e in entries for h in e.get("hooks", []))

def merge_hooks(settings: dict, capture: str, inject: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    ss = hooks.setdefault("SessionStart", [])
    se = hooks.setdefault("SessionEnd", [])
    if not _has(ss, "memhub-inject.sh"):
        ss.append({"matcher": "startup|resume", "hooks": [{"type": "command", "command": inject}]})
    if not _has(se, "memhub-capture.sh"):
        se.append({"hooks": [{"type": "command", "command": capture}]})
    return settings

def install_settings() -> None:
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    if SETTINGS.exists():
        shutil.copy(SETTINGS, str(SETTINGS) + ".memhub-bak")
    merged = merge_hooks(settings, CAPTURE, INJECT)
    SETTINGS.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    print(f"hooks installed into {SETTINGS} (backup: {SETTINGS}.memhub-bak)")

def install_launchd() -> None:
    (HOME / ".memhub").mkdir(exist_ok=True)
    py = str(HOME / "Code" / "memhub" / ".venv" / "bin" / "python")
    tmpl = (Path(__file__).parent / "com.memhub.plist").read_text()
    plist = tmpl.replace("__PYTHON__", py).replace("__HOME__", str(HOME))
    dst = HOME / "Library" / "LaunchAgents" / "com.memhub.server.plist"
    dst.write_text(plist)
    subprocess.run(["launchctl", "unload", str(dst)], capture_output=True)
    subprocess.run(["launchctl", "load", str(dst)], check=True)
    print(f"launchd loaded: {dst}")

if __name__ == "__main__":
    install_settings()
    if "--with-launchd" in sys.argv:
        install_launchd()
        print("memhub service loaded. Verify: curl -s localhost:37650/health")
    else:
        print("Skipped launchd (pass --with-launchd to load the service).")
```

- [ ] **Step 5: 跑测试确认通过 + 全量** — `./.venv/bin/pytest -q` → all pass

- [ ] **Step 6: 提交** — `cd ~/Code/memhub && git add deploy tests/test_install.py && git commit -m "feat: launchd plist + idempotent install script"`

---

## Task 5: 真实安装 + 端到端验证(动全局环境——必须用户确认后执行)

> 这一步会改 `~/.claude/settings.json` 并加载 launchd 服务。**不要自动跑;由控制器在用户确认后手动执行,逐步验证。**

- [ ] **Step 1: 备份并安装 hooks(不带 launchd 先)** — `cd ~/Code/memhub && ./.venv/bin/python deploy/install.py`,然后 `diff ~/.claude/settings.json.memhub-bak ~/.claude/settings.json` 确认只 append 了 memhub 两个 hook、其余不变。
- [ ] **Step 2: 装 launchd 服务** — `./.venv/bin/python deploy/install.py --with-launchd`,然后 `curl -s localhost:37650/health` 期望 `{"status":"ok"}`。
- [ ] **Step 3: 端到端** — 在某项目开一个新 Claude Code 会话(触发 SessionStart inject)、聊几句、结束(触发 SessionEnd capture),等 worker 一轮后 `curl "localhost:37650/search?query=...&project=<该项目>&scope=all"` 确认捕获到了;下次该项目开会话时看 SessionStart 是否注入了"## 相关记忆"。
- [ ] **Step 4: 提交任何安装产生的文档/脚本微调**(settings.json 不进 repo)。

---

## 完成标准(计划 B2)

- `transcript.py` 解析、`/capture` 接受 transcript_path、`/inject` 格式化均有测试且全绿。
- hook 脚本服务挂时静默不阻断(冒烟验证)。
- install.py 幂等 merge settings.json(保留现有 hook)+ 装 launchd,有单测。
- 真实安装后:SessionEnd 自动捕获、SessionStart 自动注入、launchd 常驻——端到端验证通过。

**Phase 1 完成后:** Plan B2 完则 P1(Claude Code 全链路自动记忆)交付。后续 Phase 2 = Codex/Gemini hook(服务零改动,各写一对 hook 脚本),Phase 3 = Ollama 离线 capturer / 管理 CLI / consolidation。
