# memhub

[English](README.md) | [简体中文](README.zh-CN.md)

> Local-first shared memory hub for CLI AI agents — automatic capture, automatic injection, hybrid retrieval. No cloud, no extra API keys.

memhub gives your CLI coding agents a shared, persistent memory. When a session ends it automatically extracts durable memories from the transcript; when a session starts it injects the relevant ones back into context. Everything runs locally on SQLite + local embeddings. Claude Code is wired up today; Codex / Gemini CLI are designed for but not yet shipped.

## Why

Every CLI agent forgets everything when a session ends, and multiple agents never share what they learned. Existing tools each miss a corner: some are heavy (Docker + a vector DB), some bind you to OpenAI, some only serve one agent, some only do manual notes. memhub is a neutral, auto-maintained, fully-local memory layer that aims to fill that gap. See [docs/COMPARISON.md](docs/COMPARISON.md).

## Features

- **Automatic capture** — a SessionEnd hook feeds the transcript to an LLM extractor (`claude -p`) that produces structured memories (`decision` / `fact` / `convention` / `snippet`), with raw-chunk fallback if extraction fails.
- **Automatic injection** — a SessionStart hook injects the most relevant memories for the current project as `additionalContext`.
- **Hybrid retrieval** — vector search (sqlite-vec) + keyword search (FTS5) fused with Reciprocal Rank Fusion, scope-filtered.
- **Local-first, zero-key** — SQLite + local `fastembed` (all-MiniLM-L6-v2 / 384-dim). No cloud, no third-party API key. LLM extraction reuses your existing `claude` CLI auth.
- **Secret redaction** — API keys / tokens / passwords are stripped before anything is persisted.
- **Multi-agent ready** — a neutral REST + MCP interface; any agent can read and write the same pool. Memories carry `project` / `agent` / `scope` tags, not an owner.
- **Resilient** — the service is an enhancement, never a dependency: if it is down, hooks stay silent and never block your agent. A failing capture item is isolated and the worker survives.
- **Pluggable capture** — the LLM extractor is one implementation of a `Capturer` interface; an offline Ollama extractor drops in without touching the pipeline.

## Architecture

```
┌─ memhub service (Python + FastMCP, 127.0.0.1:37650) ───────────────┐
│  Interface   MCP (search_memories, store_note)                      │
│              REST (/capture · /search · /inject · /health)          │
│  Capturers   LLMCapturer (claude -p, JSON extract)  →  primary      │
│              RawCapturer (fixed-size chunks)        →  fallback      │
│  Pipeline    redact → embed (fastembed 384) → dedupe → store         │
│  Storage     SQLite + sqlite-vec (vector) + FTS5 (keyword) + queue   │
│  Retrieval   vector + keyword, RRF-fused, scope-filtered             │
└─────────────────────────────────────────────────────────────────────┘
      ▲ POST /capture            ▲ MCP search          ▲ POST /inject
      │ (SessionEnd hook)        │ (agent, in-session)  │ (SessionStart hook)
   Claude Code hooks → ~/.claude/settings.json (append-only, never overwrites)
   launchd service   → starts on boot, restarts on crash
```

Three data flows — **capture** (write, async via a persistent queue), **inject** (auto-read at session start), **search** (active-read during a session). Core logic (`db` / `embedding` / `redact` / `store` / `search` / `capture` / `worker`) is decoupled from the interface layer (`server`), so every unit is testable on its own. Full design rationale and decision record: **[docs/DESIGN.md](docs/DESIGN.md)**.

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

From here it works with zero interaction: every Claude Code session-end is captured, every session-start is injected.

## How it works

- **Capture** — session ends → hook POSTs the `transcript_path` → server parses the transcript and enqueues it → a background worker runs `claude -p` to extract structured memories (raw-chunk fallback on failure) → redact → embed → store. The hook returns immediately; extraction is async, so your agent is never blocked.
- **Inject** — session starts → hook asks `/inject` for the most relevant memories for `cwd` → they are printed as `additionalContext`.
- **Search** — during a session an agent calls the `search_memories` MCP tool for on-demand recall.

## Usage

```bash
# search memories (REST)
curl -s "http://127.0.0.1:37650/search?query=auth&scope=all"

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
| Auto-capture | ✅ LLM extract | ✅ | ✅ | ✅ | ❌ manual |
| Auto-inject | ✅ | ✅ | ✅ | partial | ❌ |
| Multi-agent | ✅ REST + MCP | Claude Code only | Claude Code only | ✅ | ✅ MCP |
| Local, zero-key | ✅ | ✅ | ✅ | needs OpenAI/Docker | ✅ |
| Dependencies | SQLite + sqlite-vec (light) | Bun + uv + Chroma + worker | single Rust binary | Docker + vector DB | Python + SQLite |
| LLM extraction | `claude -p` (reuses auth) | yes | optional (paid) | yes (OpenAI) | LLM writes Markdown |
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
