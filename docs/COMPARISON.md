# memhub vs. the field

This is the survey that led to building memhub instead of adopting an existing tool. Snapshot as of **2026-06**; projects move fast, so re-check before relying on any single row.

## The gap memhub fills

Across the tools below, **no single existing project did all four of these at once**:

1. **Local & light** — no Docker, no separate vector DB, no bundled runtimes.
2. **Multi-agent ready** — a neutral interface (REST + MCP) any CLI agent can share, not a single-agent plugin.
3. **Automatic capture** — extract memories from a session without manual note-taking.
4. **Reuses existing auth** — no extra API key; piggyback on the `claude` CLI you already have.

The closest match (doobidoo/mcp-memory-service) ticked most boxes — and then its GitHub repo and author account vanished. That supply-chain risk on a single-maintainer project, plus the four-way gap, is why memhub is self-built.

## Full table

| | memhub | claude-mem | claude-self-reflect | doobidoo/mcp-memory-service | mem0 / OpenMemory | basic-memory | Letta (MemGPT) | Zep / Graphiti |
|---|---|---|---|---|---|---|---|---|
| **Category** | CLI-agent memory | Claude Code plugin | Claude Code plugin | memory MCP service | general memory layer | Markdown knowledge MCP | stateful agent platform | temporal knowledge graph |
| **Auto-capture** | ✅ LLM extract | ✅ tool-use + summary | ✅ indexes CC transcripts | ✅ (CC hook) | ✅ auto-extract | ❌ manual notes | ✅ self-editing | ✅ auto-extract |
| **Auto-inject** | ✅ SessionStart | ✅ | ✅ | ✅ | partial (retrieve) | ❌ | ✅ | n/a |
| **Multi-agent** | ✅ REST + MCP | ❌ CC only | ❌ CC only | ✅ REST/MCP/CLI | ✅ | ✅ MCP | framework (is the agent) | ✅ MCP (Graphiti) |
| **Local, zero-key** | ✅ | ✅ | ✅ (core) | ✅ | needs OpenAI / Docker | ✅ | self-host w/ local model | Graphiti local; Zep cloud |
| **Heavy deps** | SQLite + sqlite-vec | Bun + uv + Chroma + worker | single Rust binary | Python + ONNX | Docker + vector DB | Python + SQLite | Postgres + pgvector + server | Neo4j + LLM key |
| **LLM extraction** | `claude -p` (reuses auth) | yes | optional (paid Anthropic) | optional | yes (OpenAI default) | LLM writes Markdown | yes | yes |
| **License** | MIT | Apache-2.0 | MIT | Apache-2.0 | Apache-2.0 | AGPL-3.0 | Apache-2.0 | Apache-2.0 |
| **Maintainer** | self | individual | individual | individual (**repo deleted**) | company (YC) | company | company | company |

## Per-project notes

**claude-mem** — Most feature-rich auto-capture for Claude Code, but the heaviest: it pulls in Bun, uv, a Chroma vector database, and a resident worker on port 37777, and it only serves Claude Code. memhub trades some features for a far lighter stack (SQLite + sqlite-vec) and a neutral multi-agent interface.

**claude-self-reflect** — Elegant: a single ~45 MB Rust binary, local `fastembed`, no Docker, MIT. But it is fundamentally a *Claude-Code-private recall* tool — it indexes Claude Code's own transcripts and exposes them over stdio MCP only; there is no HTTP, no neutral write path for other agents. It uses all-MiniLM-L6-v2 / 384 — the model memhub also shipped with before switching to the multilingual 384-dim MiniLM (same dimensionality, so interop stays possible after a re-embed). memhub's difference: a neutral REST + MCP service multiple agents share, plus true structured LLM extraction (self-reflect's enrichment is a paid add-on).

**doobidoo/mcp-memory-service** — The nearest twin in shape: local-first, ONNX local embeddings, REST + MCP + CLI, a Claude Code auto-capture hook. The problem is non-technical: as of this survey its **GitHub repository and the maintainer's account return 404** (the PyPI package still installs). Building a long-lived daemon on a single-maintainer project whose source has disappeared is the risk memhub avoids by being self-owned.

**mem0 / OpenMemory** — A production-grade general memory layer (YC-backed, benchmarked). But it is heavy and OpenAI-leaning: the self-hosted path wants Docker and a vector DB and defaults to OpenAI for both the LLM and embeddings. The local **OpenMemory** MCP component has been **sunset**; the recommended replacement (mem0 self-hosted server) ships with *no auth and `CORS: *`* and carried a cluster of "missing authentication" CVEs. Overkill and a poor security default for a single-user local tool.

**basic-memory** — Closest to memhub in philosophy on storage (plain Markdown + a SQLite index, human-readable, zero lock-in) and the best neutral substrate. But it is **manual-capture**: you prompt the assistant to write notes; it does not automatically harvest a session. memhub's whole point is the automatic SessionEnd → extract → store loop. (Also AGPL-3.0, which has copyleft implications for downstream integration.)

**Letta (MemGPT)** and **Zep / Graphiti** — Different weight class. Letta is a full stateful-agent *platform* (Postgres + pgvector + a running server; it *is* the agent, with no official Claude Code inbound integration). Zep/Graphiti is temporal-knowledge-graph infrastructure (needs a graph DB like Neo4j + an LLM key). Both are excellent if you are building a product's memory backend; both are far too much to "give my CLI agents a shared memory."

## Where memhub lands

memhub is deliberately small: a single local Python service over SQLite + sqlite-vec, a neutral REST/MCP interface, automatic capture that reuses your existing `claude` auth, and automatic injection via thin hooks. It is not the most powerful option in any single column above — it is the one that hits all four corners of the gap at once, on a stack light enough to read in an afternoon and own yourself.
