# memhub

[English](README.md) | [简体中文](README.zh-CN.md)

> 本地优先的多 CLI AI agent 共享记忆中枢——自动捕获、自动注入、混合检索。无云、无额外 API key。

memhub 给你的 CLI 编程 agent 一份共享、持久的记忆:会话结束时自动从对话里抽取值得留存的记忆,会话开始时把相关的注入回上下文。全部跑在本地的 SQLite + 本地 embedding 上。Claude Code 已接通;Codex / Gemini CLI 已设计、尚未交付。

## 为什么

每个 CLI agent 会话一结束就失忆,多个 agent 之间也从不共享学到的东西。现有工具各缺一角:有的重(Docker + 向量库),有的绑死 OpenAI,有的只服务单个 agent,有的只能手动记笔记。memhub 想做的是一个中立、自动维护、纯本地的记忆层来补这个缺口。详见 [docs/COMPARISON.md](docs/COMPARISON.md)。

## 特性

- **自动捕获** —— SessionEnd hook 把 transcript 喂给 LLM 抽取器(`claude -p`),提炼成结构化记忆(`decision` / `fact` / `convention` / `snippet`);抽取失败时回退到原文切片,不丢数据。
- **自动注入** —— SessionStart hook 把当前项目最相关的记忆作为 `additionalContext` 注入。
- **混合检索** —— 向量(sqlite-vec)+ 关键词(FTS5),用 RRF(Reciprocal Rank Fusion)融合,按 scope 过滤。
- **本地优先、零 key** —— SQLite + 本地 `fastembed`(all-MiniLM-L6-v2 / 384 维)。无云、无第三方 API key。LLM 抽取复用你现有的 `claude` CLI 认证。
- **写前脱敏** —— API key / token / 密码在入库前被抹掉。
- **多 agent 就绪** —— 中立的 REST + MCP 接口,任何 agent 都能读写同一个池;记忆带 `project` / `agent` / `scope` 标签,不绑定所有者。
- **韧性** —— 服务是"增强"不是"依赖":它挂了,hook 静默跳过、绝不阻断你的 agent;单条捕获失败被隔离,worker 不会被拖死。
- **可插拔捕获** —— LLM 抽取器只是 `Capturer` 接口的一个实现;离线的 Ollama 抽取器可以无缝替换,不动管道。

## 架构

```
┌─ memhub 服务 (Python + FastMCP, 127.0.0.1:37650) ──────────────────┐
│  接口层    MCP (search_memories, store_note)                        │
│            REST (/capture · /search · /inject · /health)            │
│  捕获器    LLMCapturer (claude -p, 抽 JSON)   →  主                  │
│            RawCapturer (定长切片)            →  兜底                 │
│  处理      脱敏 → embedding (fastembed 384) → 去重 → 存              │
│  存储      SQLite + sqlite-vec(向量) + FTS5(关键词) + 队列           │
│  检索      向量 + 关键词,RRF 融合,scope 过滤                        │
└─────────────────────────────────────────────────────────────────────┘
      ▲ POST /capture            ▲ MCP search          ▲ POST /inject
      │ (SessionEnd hook)        │ (会话中 agent 调)    │ (SessionStart hook)
   Claude Code hooks → ~/.claude/settings.json (只 append,不覆盖)
   launchd 服务      → 开机自起,崩溃重启
```

三条数据流:**捕获**(写,经持久队列异步处理)、**注入**(会话开始自动读)、**检索**(会话中主动读)。核心逻辑(`db` / `embedding` / `redact` / `store` / `search` / `capture` / `worker`)与接口层(`server`)解耦,每个单元都能独立测试。完整设计与决策记录见 **[docs/DESIGN.md](docs/DESIGN.md)**。

## 环境要求

- macOS(服务基于 launchd;Linux 用 systemd unit 也行,但脚本未写)
- Python 3.12+
- `claude` CLI 在 `PATH` 上(用于 LLM 抽取,复用你 Claude Code 已有的认证)

## 安装

```bash
git clone https://github.com/codesfly/memhub ~/Code/memhub
cd ~/Code/memhub
python3 -m venv .venv && ./.venv/bin/pip install -e .

# 1) 装 Claude Code hooks —— 会先备份 settings.json(0600)、只 append、绝不覆盖
./.venv/bin/python deploy/install.py

# 2) 装常驻服务(开机自起、崩溃重启)
./.venv/bin/python deploy/install.py --with-launchd

curl -s localhost:37650/health    # -> {"status":"ok"}
```

装完零交互工作:每次 Claude Code 会话结束被捕获、开始被注入。

## 工作原理

- **捕获** —— 会话结束 → hook POST `transcript_path` → 服务解析 transcript 并入队 → 后台 worker 用 `claude -p` 抽取结构化记忆(失败回退原文切片)→ 脱敏 → embedding → 存。hook 立即返回,抽取异步,绝不阻断 agent。
- **注入** —— 会话开始 → hook 向 `/inject` 要当前 `cwd` 的相关记忆 → 作为 `additionalContext` 打印。
- **检索** —— 会话中 agent 调 `search_memories` MCP 工具按需召回。

## 使用

```bash
# 检索记忆 (REST)
curl -s "http://127.0.0.1:37650/search?query=认证&scope=all"

# 服务日志
tail -f ~/.memhub/memhub.log        # 错误日志: ~/.memhub/memhub.err

# 重启 / 停止
launchctl unload ~/Library/LaunchAgents/com.memhub.server.plist
launchctl load   ~/Library/LaunchAgents/com.memhub.server.plist
```

**MCP 工具**(给 agent 用):`search_memories(query, scope?, kind?, project?, limit?)` 和 `store_note(content, tags?, scope?, project?)`。

**scope:** `current`(当前项目)、`global`(可跨项目复用)、`all`。默认检索 `current,global`,且**fail-closed**——`current` 检索但没传 project 时返回空,而不是泄露到别的项目。

## 同类对比

| | memhub | claude-mem | claude-self-reflect | mem0 / OpenMemory | basic-memory |
|---|---|---|---|---|---|
| 自动捕获 | ✅ LLM 抽取 | ✅ | ✅ | ✅ | ❌ 手动 |
| 自动注入 | ✅ | ✅ | ✅ | 部分 | ❌ |
| 多 agent | ✅ REST + MCP | 仅 Claude Code | 仅 Claude Code | ✅ | ✅ MCP |
| 本地零 key | ✅ | ✅ | ✅ | 需 OpenAI/Docker | ✅ |
| 依赖 | SQLite + sqlite-vec(轻) | Bun + uv + Chroma + worker | 单 Rust 二进制 | Docker + 向量库 | Python + SQLite |
| LLM 抽取 | `claude -p`(复用认证) | 有 | 可选(付费) | 有(默认 OpenAI) | LLM 写 Markdown |
| 状态 | 新 | 活跃 | 活跃 | OpenMemory 已停 | 活跃 |

完整对比与出处见 **[docs/COMPARISON.md](docs/COMPARISON.md)**。

## 路线图

- [x] **Phase 1** —— 服务核心 + 异步捕获管道 + Claude Code 集成(hooks + launchd)
- [ ] **Phase 2** —— Gemini CLI / Codex hook(服务不变——中立 REST/MCP)
- [ ] **Phase 3** —— Ollama 离线抽取器、记忆管理 CLI、衰减 / 合并

## 卸载

```bash
launchctl unload ~/Library/LaunchAgents/com.memhub.server.plist
rm ~/Library/LaunchAgents/com.memhub.server.plist
# 再从 ~/.claude/settings.json 删掉 memhub 那两个 hook
# (安装前的备份在 ~/.claude/settings.json.memhub-bak)
```

## 安全说明

- 服务只绑 `127.0.0.1`,信任任何本地调用者(单用户本地工具)。别把端口暴露到 LAN/公网。
- `/capture` 会读它收到的 `transcript_path` —— 只有本地 hook 会发这个。
- 入库前已脱敏,但仍请把 `~/.memhub/memhub.db` 当本地缓存对待。

## License

[MIT](LICENSE)
