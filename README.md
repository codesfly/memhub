# memhub

[English](README.md) | [简体中文](README.zh-CN.md)

> Local-first shared memory hub for CLI AI agents — controlled capture, optional injection, hybrid retrieval. No cloud, no extra API keys by default.

memhub gives your CLI coding agents a shared, persistent memory. When a session ends it can capture durable memories from the transcript; when a session starts it can inject relevant ones back into context. Everything runs locally on SQLite + local embeddings unless you explicitly enable LLM extraction. Claude Code is wired up today; Codex / Gemini CLI are designed for but not yet shipped.

## Why

Every CLI agent forgets everything when a session ends, and multiple agents never share what they learned. Existing tools each miss a corner: some are heavy (Docker + a vector DB), some bind you to OpenAI, some only serve one agent, some only do manual notes. memhub is a neutral, auto-maintained, fully-local memory layer that aims to fill that gap. See [docs/COMPARISON.md](docs/COMPARISON.md).

## Features

- **Controlled capture** — SessionEnd can capture raw transcript chunks by default, stay off entirely, or explicitly use LLM extraction (`claude -p`) when you switch it on.
- **Optional injection** — SessionStart injection is off by default and can be enabled from the web UI or settings API.
- **Hybrid retrieval** — vector search (sqlite-vec) + keyword search (FTS5) fused with Reciprocal Rank Fusion, scope-filtered.
- **Local-first, zero-key by default** — SQLite + local `fastembed` (all-MiniLM-L6-v2 / 384-dim). No cloud, no third-party API key unless you explicitly enable LLM extraction, which reuses your existing `claude` CLI auth.
- **Secret redaction** — API keys / tokens / passwords are stripped before anything is persisted.
- **Multi-agent ready** — a neutral REST + MCP interface; any agent can read and write the same pool. Memories carry `project` / `agent` / `scope` tags, not an owner.
- **Resilient** — the service is an enhancement, never a dependency: if it is down, hooks stay silent and never block your agent. A failing capture item is isolated and the worker survives.
- **Pluggable capture** — the LLM extractor is one implementation of a `Capturer` interface; an offline Ollama extractor drops in without touching the pipeline.

## Architecture

```
┌─ memhub service (Python + FastMCP, 127.0.0.1:37650) ───────────────┐
│  Interface   MCP (search_memories, store_note)                      │
│              REST (/capture · /search · /inject · /health)          │
│  Capturers   RawCapturer (fixed-size chunks)        →  default       │
│              LLMCapturer (claude -p, JSON extract)  →  opt-in        │
│  Pipeline    redact → embed (fastembed 384) → dedupe → store         │
│  Storage     SQLite + sqlite-vec (vector) + FTS5 (keyword) + queue   │
│  Retrieval   vector + keyword, RRF-fused, scope-filtered             │
└─────────────────────────────────────────────────────────────────────┘
      ▲ POST /capture            ▲ MCP search          ▲ POST /inject
      │ (SessionEnd hook)        │ (agent, in-session)  │ (SessionStart hook)
   Claude Code hooks → ~/.claude/settings.json (append-only, never overwrites)
   launchd service   → starts on boot, restarts on crash
```

Three data flows — **capture** (write, async via a persistent queue), **inject** (optional read at session start), **search** (active-read during a session). Core logic (`db` / `embedding` / `redact` / `store` / `search` / `capture` / `worker`) is decoupled from the interface layer (`server`), so every unit is testable on its own. Full design rationale and decision record: **[docs/DESIGN.md](docs/DESIGN.md)**.

## Requirements

- macOS (the service is launchd-based; Linux works with a systemd unit — not yet scripted)
- Python 3.12+
- `claude` CLI available on `PATH` (used for LLM extraction; reuses whatever auth your Claude Code already uses)

## Install

```bash
git clone https://github.com/codesfly/memhub ~/Code/memhub
cd ~/Code/memhub
python3 -m venv .venv && ./.venv/bin/pip install -e .

# 1) install Claude Code hooks — backs up settings.json (0600), appends, never overwrites
./.venv/bin/python deploy/install.py

# 2) load the always-on service (starts on boot, restarts on crash)
./.venv/bin/python deploy/install.py --with-launchd

curl -s localhost:37650/health    # -> {"status":"ok"}
```

Safe defaults after install: capture mode is `raw`, injection is off, and `claude -p` is never called unless you switch capture mode to `llm`.

## Sync across machines

memhub is local-first — each machine has its own SQLite db. To share memories, sync the **source `.md` files** (never the db) through a private git repo. Two helper scripts in `deploy/`:

**New machine — one-shot install** (clones repo, installs service + hooks, turns injection on; idempotent):

```bash
curl -fsSL https://raw.githubusercontent.com/codesfly/memhub/main/deploy/bootstrap.sh | bash
```

**Memory sync over a private git repo.** Only `*/memory/*.md` is ever pushed — session transcripts (`.jsonl`) and the SQLite db never leave the machine, enforced by a whitelist `.gitignore` plus a pre-push staging guard that aborts if anything else is staged:

```bash
deploy/memory-sync.sh init <git-url>   # first machine: create repo at ~/.claude/projects, push memories
deploy/memory-sync.sh link <git-url>   # other machines: attach to the existing repo, keep local memories
deploy/memory-sync.sh push             # local memories -> remote
deploy/memory-sync.sh pull             # remote -> local, then rebuild the index (zero-LLM, idempotent)
```

After `link` / `pull` the db (vectors + FTS) is rebuilt locally from the `.md` files, so nothing binary is ever transferred.

> **Caveat — cross-machine project scope.** A memory's `project` tag is the real cwd, resolved by reading that project's `*.jsonl` transcript, which is deliberately not synced. On a machine that has never opened a given project locally, that project's *project-local* memories fall back to the encoded directory name and may miss session-start injection. Global (user-identity) memories are unaffected; any project you actually work on has local transcripts there and resolves correctly. Keep the same home path (`/Users/<you>`) on both machines.

## How it works

- **Capture** — session ends → hook POSTs the `transcript_path` → server checks capture mode. `off` skips, `raw` enqueues fixed-size raw chunks, and `llm` runs `claude -p` for structured extraction with raw fallback. The hook returns immediately.
- **Inject** — session starts → hook asks `/inject` for memories for `cwd`; the route returns context only when injection is enabled.
- **Search** — during a session an agent calls the `search_memories` MCP tool for on-demand recall.

## Usage

```bash
# search memories (REST)
curl -s "http://127.0.0.1:37650/search?query=auth&scope=all"

# inspect / change runtime settings
curl -s http://127.0.0.1:37650/settings
curl -s -X PATCH http://127.0.0.1:37650/settings \
  -H 'Content-Type: application/json' \
  -d '{"capture_mode":"off","inject_enabled":false}'

# clear unprocessed captures
memhub clear-pending --yes

# web UI
open http://127.0.0.1:37650/ui

# service logs
tail -f ~/.memhub/memhub.log        # errors: ~/.memhub/memhub.err

# restart / stop
launchctl unload ~/Library/LaunchAgents/com.memhub.server.plist
launchctl load   ~/Library/LaunchAgents/com.memhub.server.plist
```

**MCP tools** (for agents): `search_memories(query, scope?, kind?, project?, limit?)` and `store_note(content, tags?, scope?, project?)`.

**Scopes:** `current` (this project), `global` (reusable across projects), `all`. Default retrieval is `current,global`, and fails closed — a `current` query with no project returns nothing rather than leaking across projects.

## Comparison

| | memhub | claude-mem | claude-self-reflect | mem0 / OpenMemory | basic-memory |
|---|---|---|---|---|---|
| Auto-capture | ✅ raw default / LLM opt-in | ✅ | ✅ | ✅ | ❌ manual |
| Auto-inject | ✅ opt-in | ✅ | ✅ | partial | ❌ |
| Multi-agent | ✅ REST + MCP | Claude Code only | Claude Code only | ✅ | ✅ MCP |
| Local, zero-key | ✅ | ✅ | ✅ | needs OpenAI/Docker | ✅ |
| Dependencies | SQLite + sqlite-vec (light) | Bun + uv + Chroma + worker | single Rust binary | Docker + vector DB | Python + SQLite |
| LLM extraction | opt-in `claude -p` | yes | optional (paid) | yes (OpenAI) | LLM writes Markdown |
| Status | new | active | active | OpenMemory sunset | active |

Full detail and sourcing: **[docs/COMPARISON.md](docs/COMPARISON.md)**.

## Roadmap

- [x] **Phase 1** — service core + async capture pipeline + Claude Code integration (hooks + launchd)
- [ ] **Phase 2** — Gemini CLI / Codex hooks (service unchanged — neutral REST/MCP)
- [ ] **Phase 3** — Ollama offline extractor, memory-management CLI, decay / consolidation

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.memhub.server.plist
rm ~/Library/LaunchAgents/com.memhub.server.plist
# then remove the two memhub hooks from ~/.claude/settings.json
# (a pre-install backup is at ~/.claude/settings.json.memhub-bak)
```

## Security notes

- The service binds `127.0.0.1` only and trusts any local caller (single-user local tool). Do not expose the port to a LAN/public network.
- `/capture` reads the `transcript_path` it is given — only the local hooks send it.
- Secrets are redacted before persistence, but treat `~/.memhub/memhub.db` as you would any local cache.

## License

[MIT](LICENSE)
