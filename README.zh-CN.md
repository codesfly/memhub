# memhub

[English](README.md) | [简体中文](README.zh-CN.md)

> 本地优先的多 CLI AI agent 共享记忆中枢——可控捕获、可选注入、混合检索。默认无云、无额外 API key。

memhub 给你的 CLI 编程 agent 一份共享、持久的记忆:会话结束时可捕获值得留存的记忆,会话开始时可把相关记忆注入回上下文。除非显式开启 LLM 抽取,否则全部跑在本地的 SQLite + 本地 embedding 上。Claude Code 已接通;Codex / Gemini CLI 已设计、尚未交付。

## 为什么

每个 CLI agent 会话一结束就失忆,多个 agent 之间也从不共享学到的东西。现有工具各缺一角:有的重(Docker + 向量库),有的绑死 OpenAI,有的只服务单个 agent,有的只能手动记笔记。memhub 想做的是一个中立、自动维护、纯本地的记忆层来补这个缺口。详见 [docs/COMPARISON.md](docs/COMPARISON.md)。

## 特性

- **可控捕获** —— SessionEnd 默认只做 raw 原文切片,也可以完全关闭;只有显式切到 `llm` 才会调用 LLM 抽取器(`claude -p`)。
- **可选注入** —— SessionStart 注入默认关闭,可在 Web UI 或 settings API 里打开。
- **混合检索** —— 向量(sqlite-vec)+ 关键词(FTS5),用 RRF(Reciprocal Rank Fusion)融合,按 scope 过滤。
- **本地优先、默认零 key** —— SQLite + 本地 `fastembed`(all-MiniLM-L6-v2 / 384 维)。除非显式开启 LLM 抽取,否则无云、无第三方 API key;LLM 抽取会复用你现有的 `claude` CLI 认证。
- **写前脱敏** —— API key / token / 密码在入库前被抹掉。
- **多 agent 就绪** —— 中立的 REST + MCP 接口,任何 agent 都能读写同一个池;记忆带 `project` / `agent` / `scope` 标签,不绑定所有者。
- **韧性** —— 服务是"增强"不是"依赖":它挂了,hook 静默跳过、绝不阻断你的 agent;单条捕获失败被隔离,worker 不会被拖死。
- **可插拔捕获** —— LLM 抽取器只是 `Capturer` 接口的一个实现;离线的 Ollama 抽取器可以无缝替换,不动管道。

## 架构

```
┌─ memhub 服务 (Python + FastMCP, 127.0.0.1:37650) ──────────────────┐
│  接口层    MCP (search_memories, store_note)                        │
│            REST (/capture · /search · /inject · /health)            │
│  捕获器    RawCapturer (定长切片)            →  默认                 │
│            LLMCapturer (claude -p, 抽 JSON)   →  显式开启             │
│  处理      脱敏 → embedding (fastembed 384) → 去重 → 存              │
│  存储      SQLite + sqlite-vec(向量) + FTS5(关键词) + 队列           │
│  检索      向量 + 关键词,RRF 融合,scope 过滤                        │
└─────────────────────────────────────────────────────────────────────┘
      ▲ POST /capture            ▲ MCP search          ▲ POST /inject
      │ (SessionEnd hook)        │ (会话中 agent 调)    │ (SessionStart hook)
   Claude Code hooks → ~/.claude/settings.json (只 append,不覆盖)
   launchd 服务      → 开机自起,崩溃重启
```

三条数据流:**捕获**(写,经持久队列异步处理)、**注入**(会话开始可选读)、**检索**(会话中主动读)。核心逻辑(`db` / `embedding` / `redact` / `store` / `search` / `capture` / `worker`)与接口层(`server`)解耦,每个单元都能独立测试。完整设计与决策记录见 **[docs/DESIGN.md](docs/DESIGN.md)**。

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

安装后的安全默认值:捕获模式为 `raw`,注入关闭,除非切到 `llm`,否则不会调用 `claude -p`。

## 跨机器同步

memhub 是 local-first 的——每台机器各有独立的 SQLite 库。要共享记忆,同步的是**源头 `.md` 文件**(绝不传库),走一个私有 git 仓库。`deploy/` 下两个脚本:

**新机器——一键安装**(clone 仓库、装服务 + hooks、打开注入;幂等):

```bash
curl -fsSL https://raw.githubusercontent.com/codesfly/memhub/main/deploy/bootstrap.sh | bash
```

**记忆走私有 git 仓库同步。**只会推 `*/memory/*.md`——会话日志(`.jsonl`)和 SQLite 库永不离开本机,由白名单 `.gitignore` + push 前的暂存区安全闸双重保证(发现任何别的文件就中止):

```bash
deploy/memory-sync.sh init <git-url>   # 首台:在 ~/.claude/projects 建库并推送记忆
deploy/memory-sync.sh link <git-url>   # 其它机:接入已有仓库,保留本地已有记忆
deploy/memory-sync.sh push             # 本机记忆 -> 远端
deploy/memory-sync.sh pull             # 远端 -> 本机,然后重建检索库(zero-LLM、幂等)
deploy/memory-sync.sh schedule [秒]    # 可选:launchd 定时自动 push(默认每小时,无变化跳过)
```

`link` / `pull` 后,库(向量 + FTS)从 `.md` 在本地重建,不传任何二进制。

> **注意——跨机器的 project 范围。**记忆的 `project` 标签是真实 cwd,靠读该项目的 `*.jsonl` 还原,而 `.jsonl` 故意不同步。在一台从没本地打开过某项目的机器上,该项目的*项目级*记忆会退回用编码目录名,可能匹配不上会话启动注入。全局(用户身份)记忆不受影响;你在某台机器实际工作的项目,本地有 transcript,能正确解析。两台机器保持相同的 home 路径(`/Users/<你>`)。

## 工作原理

- **捕获** —— 会话结束 → hook POST `transcript_path` → 服务检查捕获模式。`off` 跳过,`raw` 存原文切片,`llm` 才调用 `claude -p` 抽结构化记忆并在失败时回退 raw。hook 立即返回。
- **注入** —— 会话开始 → hook 向 `/inject` 要当前 `cwd` 的相关记忆;只有注入开关打开时才会返回 `additionalContext`。
- **检索** —— 会话中 agent 调 `search_memories` MCP 工具按需召回。

## 使用

```bash
# 检索记忆 (REST)
curl -s "http://127.0.0.1:37650/search?query=认证&scope=all"

# 查看 / 修改运行时设置
curl -s http://127.0.0.1:37650/settings
curl -s -X PATCH http://127.0.0.1:37650/settings \
  -H 'Content-Type: application/json' \
  -d '{"capture_mode":"off","inject_enabled":false}'

# 清掉未处理捕获
memhub clear-pending --yes

# Web UI
open http://127.0.0.1:37650/ui

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
| 自动捕获 | ✅ raw 默认 / LLM 可选 | ✅ | ✅ | ✅ | ❌ 手动 |
| 自动注入 | ✅ 可选开启 | ✅ | ✅ | 部分 | ❌ |
| 多 agent | ✅ REST + MCP | 仅 Claude Code | 仅 Claude Code | ✅ | ✅ MCP |
| 本地零 key | ✅ | ✅ | ✅ | 需 OpenAI/Docker | ✅ |
| 依赖 | SQLite + sqlite-vec(轻) | Bun + uv + Chroma + worker | 单 Rust 二进制 | Docker + 向量库 | Python + SQLite |
| LLM 抽取 | 可选 `claude -p` | 有 | 可选(付费) | 有(默认 OpenAI) | LLM 写 Markdown |
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
