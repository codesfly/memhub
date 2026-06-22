# Known Issues

## Issue 1 — LLM extraction (`claude -p`) has no usable auth under the launchd service

**Severity:** High (the headline structured-extraction feature is degraded) · **Status:** mitigated · **Found:** 2026-06-22 · **Mitigated:** 2026-06-22

**Symptom:** The background worker's `claude -p` call times out after 120s when running under the launchd service. Every capture then falls back to `RawCapturer`, so memories are stored as raw text chunks instead of structured `decision` / `fact` / `convention` / `snippet` items.

**Root cause (diagnosed):** The launchd service process has only `HOME` + `PATH` in its environment — **no `ANTHROPIC_*` auth vars**. `claude -p` therefore has no working authentication path:

- Manual/interactive runs succeed only because this machine's shell inherits `ANTHROPIC_*` from **Claude Desktop** (`ANTHROPIC_BASE_URL=https://api.anthropic.com` + a token). That is injected at Desktop runtime — **not persistent**, and unavailable to a launchd background service.
- The persistent config in `~/.claude/settings.json` points `ANTHROPIC_BASE_URL` at an **Aliyun FC proxy** (`a-ocnfniawgw...fcapp.run`). Verified: running `claude -p` with that proxy env **also times out** — the proxy does not serve headless `-p` requests.

→ There is currently **no persistent, working `claude` auth available to a background service** on this machine.

**Mitigation applied:** `claude -p` is no longer the default path. Capture mode now supports `off`, `raw`, and `llm`; the service defaults to `raw`, and `llm` must be explicitly enabled through `/settings` or the Web UI. Pending capture items can be removed through `DELETE /capture/pending` or `memhub clear-pending --yes`.

**Remaining candidate fixes for structured extraction:**
1. **Ollama offline extractor** (Phase 3) — worker uses a local model; bypasses claude auth entirely. Best long-term; costs an Ollama install + a model (~GBs RAM). Also makes Issue 2 disappear.
2. **Give the worker a real `api.anthropic.com` key** via the launchd plist `EnvironmentVariables` (only if/when an official key is available; the current setup is proxy-based).
3. **Keep raw-only** — leave capture mode at `raw`. This avoids external LLM calls and keeps search usable, but does not produce structured `decision` / `fact` / `convention` / `snippet` memories.

## Issue 2 — `claude -p` extraction calls get recorded as their own sessions (self-pollution)

**Severity:** Medium · **Status:** mitigated · **Found:** 2026-06-22 · **Mitigated:** 2026-06-22

**Symptom:** A captured memory's content turned out to be memhub's own extraction prompt (`You extract durable memories from an AI coding session transcript...`). The worker's `claude -p` invocation is itself logged by the claude CLI as a session under `~/.claude/projects/-Users-jiumu-Code-memhub/`, which the SessionEnd hook can then capture — a feedback loop.

**Root cause:** `claude -p` records a session transcript; the worker runs it with a cwd under the memhub project, so the call lands in memhub's own projects dir and looks like a normal session to the capture hook.

**Candidate fixes:**
- Adopting Ollama or raw-only (Issue 1, fixes 1 or 3) means the worker stops calling `claude -p` → this disappears.
- Otherwise: invoke `claude -p` in a way that doesn't record a session (dedicated cwd / a no-history flag if available), and/or have the capture pipeline skip transcripts whose content matches the extraction prompt or that live under the memhub project dir.

**Mitigation applied:** the worker defaults to raw mode, and the hook/server skip transcripts containing the extraction prompt marker. The feedback loop only becomes relevant again if capture mode is deliberately changed to `llm`.

---

**Note on current state:** memhub still functions in degraded mode — it captures raw conversation chunks, which are embedded, searchable (hybrid vector + FTS), and manageable via the web viewer / CLI. The structured-extraction layer is what's currently inert. See [DESIGN.md](DESIGN.md) for the intended pipeline.
