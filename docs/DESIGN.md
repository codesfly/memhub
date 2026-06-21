# memhub 设计文档

> 状态:草案(待实现) · 日期:2026-06-21 · 仓库:`codesfly/memhub`

## 1. 目标

memhub 是一个**本地优先的共享记忆中枢**,让多个 CLI AI agent(Claude Code、Codex CLI、Gemini CLI)**跨会话、跨 agent 共享同一份记忆**:会话结束时**自动捕获**对话要点,会话开始时**自动注入**相关上下文,会话中也能主动检索。

**解决的问题:** 每个 CLI agent 会话结束即失忆;多个 agent 各自为政、记忆不互通。memhub 提供一个中立的、自动维护、纯本地的记忆层。

## 2. 非目标(YAGNI)

- 不做云同步 / 多机共享(本地单机)。
- 不做用户 / 权限系统(单用户本机)。
- 不做 Web 管理界面(MVP 阶段;Phase 3 可选)。
- 不替代各 agent 的项目级 `CLAUDE.md` / 人工策展记忆——memhub 管"会话级自动记忆",与人工策展**互补**。
- 不做实时每轮注入(只在 SessionStart 注入一次,控 token)。

## 3. 架构

```
┌─ memhub 服务 (常驻, Python + FastMCP, 127.0.0.1:37650) ────────┐
│  接口层                                                          │
│   ├─ MCP (streamable HTTP)  → search / store_note,给 agent 连   │
│   └─ REST  → POST /capture · GET /search · GET /health         │
│  捕获器 (可插拔 Capturer 接口)                                   │
│   ├─ LLMCapturer   claude -p 抽取结构化记忆  (主)               │
│   └─ RawCapturer   原文切片                   (兜底)            │
│  处理:  脱敏 → embedding (fastembed all-MiniLM-L6-v2 / 384)     │
│  存储:  SQLite + sqlite-vec(向量) + FTS5(关键词)               │
│  检索:  向量 + 关键词 RRF 混合排序                              │
└────────────────────────────────────────────────────────────────┘
        ▲ POST /capture          ▲ MCP search           ▲ GET /search(注入)
        │                        │                       │
   各端 hook(薄 shell 脚本,只碰 REST):
   ├─ Claude Code  SessionEnd→捕获   SessionStart→注入   ← P1 先做
   ├─ Codex CLI    Stop→捕获         SessionStart→注入   ← P2
   └─ Gemini CLI   SessionEnd→捕获   SessionStart→注入   ← P2
```

**三条数据流:**

1. **捕获(写):** 会话结束 → hook 读 transcript → `POST /capture {transcript, project, agent, session_id}` → 服务写入 `capture_queue`(pending)、**立即 200 返回**(不阻塞 agent) → 后台 worker 抽取 → 脱敏 → embedding → 存库。
2. **注入(读·自动):** 会话开始 → hook `GET /search?project=X&scope=current,global&limit=6` → 格式化成简短块打印 → agent 把 SessionStart 输出纳入上下文。
3. **检索(读·主动):** 会话中 agent 调 MCP `search` 工具深挖。

设计原则:**核心逻辑(存储 / 检索 / 捕获)与接口层(MCP / REST)解耦**,各为独立单元、可单测。

## 4. 存储 schema (SQLite)

| 表 | 关键字段 | 作用 |
|---|---|---|
| `memories` | `id` PK, `content`, `content_hash` UNIQUE(去重), `kind`(decision/fact/convention/snippet/raw), `project`, `agent`, `tags`(JSON), `scope`(current/global), `session_id`, `created_at` | 记忆本体 |
| `memories_vec` (sqlite-vec) | `memory_id` → `embedding`(384 float) | 语义检索 |
| `memories_fts` (FTS5) | `content` (tokenize: porter unicode61) | 关键词检索 |
| `capture_queue` | `id`, `payload`(transcript+meta), `status`(pending/done/failed), `attempts`, `created_at` | 异步捕获队列,服务重启不丢 |

## 5. 捕获管道(写路径)

1. hook `POST /capture {transcript, project=cwd, agent, session_id}`。
2. 服务写入 `capture_queue`(pending)→ **立即 200 返回**,不阻塞 agent。
3. 后台 worker 取 pending:
   - **LLMCapturer:** `claude -p "<抽取prompt>"` 喂 transcript → 产出**强制 JSON 数组**,每条 `{content, kind, tags, scope}`。
   - 失败 / 超时 / JSON 解析失败 → **RawCapturer** 原文切片兜底。
   - 每条:**脱敏**(正则)→ `content_hash` 去重 → embedding → 写 `memories` + `memories_vec` + `memories_fts`。
   - 成功标 `done`;失败重试 N 次(指数退避)后标 `failed` + 记日志,不静默吞。
4. `scope` 由 LLM 抽取时顺带判定(通用经验=global / 项目特定=current),用户可后期手改。

## 6. 检索与注入(读路径)

**检索逻辑(REST 与 MCP 共用):**
- **混合排序** = 向量(sqlite-vec KNN)+ 关键词(FTS5),用 **RRF** 融合两路。
- **默认过滤:** 当前 `project` + `scope=global`;可显式 `scope=all` 跨项目。
- 入参:`query, project, scope(current/global/all), kind?, limit`。

**注入(SessionStart,自动):** hook 拿 `cwd` 当 project → `GET /search` → 格式化:
```
## 相关记忆 (memhub · N 条)
- [decision] 本项目认证用 JWT,不用 session …
- [convention] commit 用 conventional commits …
```
默认 **top-6**、每条截断 ~1-2 行,只在会话开始注入一次。

## 7. 接口规格

| 口 | 端点 / 工具 | 谁用 | 读写 |
|---|---|---|---|
| REST | `POST /capture` | 各端捕获 hook | 写(入队) |
| REST | `GET /search` | 各端注入 hook | 读 |
| REST | `GET /health` | 监控 / launchd | — |
| MCP | `search(query, scope?, kind?, limit?)` | agent 会话中主动 | 读 |
| MCP | `store_note(content, tags?, scope?)` | agent 主动补记 | 写 |

hook 走 REST(`curl` 最省事),MCP 留给 agent 在会话里智能调用。

## 8. 安全与隐私

- **纯本地:** SQLite 文件 + 本地 embedding(fastembed),无云、无第三方 key。
- **脱敏:** 抽取后、入库前,正则扫描密钥类字符串(`sk-` / `ghp_` / `AKIA` / `PRIVATE KEY` / `password=` 等)→ 替换为 `[REDACTED]`。
- **认证:** claude 抽取走宿主订阅认证(服务在宿主,直接调 `claude -p`)。
- **网络:** 服务仅监听 `127.0.0.1`,不对外暴露。

## 9. 错误处理与降级

**核心原则:memhub 是"增强"不是"依赖"。**
- **服务挂了 agent 照常:** hook POST 失败 / 服务没起 → hook 静默跳过 + 写本地日志,**绝不阻断 agent 会话**。
- **捕获逐级降级:** `claude -p` 失败/超时 → RawCapturer;JSON 解析失败 → 兜底;embedding 失败 → 跳过该条不崩整批;worker 重试 N 次(指数退避)后标 `failed` + 日志。
  > 注:重试/退避(retry N 次)在 B1 暂未实现——当前 `mark_failed` 为终态、`attempts` 仅自增未读取;留待 Phase 3。失败项不会自动重试,但 `content_hash` 去重保证手动重灌安全。
- 服务内用 typed errors + 结构化日志,REST 标准状态码,外部调用(claude CLI)带超时。

## 10. 测试策略(TDD,先写测试)

- **单元:** capturer(mock `claude -p`)、脱敏正则、去重、RRF 混合排序、scope 过滤。
- **集成:** `capture → 队列 → worker → 存 → search` 全链路(临时 SQLite)。
- **hook:** 样例 transcript 测 POST 行为 + **服务没起时的静默降级**。
- 测试**不依赖真 claude 调用**(全 mock),可离线 CI。

## 11. 部署

- 宿主 Python 服务,依赖装在**项目 venv**(`~/Code/memhub/.venv`),不污染全局(符合"库走项目 venv"习惯)。
- **launchd** LaunchAgent plist:开机自起 + 崩溃重启,plist 指向 venv 里的 python。
- 服务监听 `127.0.0.1:37650`(可配)。

## 12. 分阶段交付

| 阶段 | 内容 |
|---|---|
| **Phase 1 (MVP)** | memhub 服务(存储 / 检索 / 队列 / REST + MCP)→ RawCapturer 先跑通管道 → 接 LLMCapturer → **Claude Code hook(SessionEnd 捕获 + SessionStart 注入)** → launchd 常驻 |
| **Phase 2** | Codex CLI hook + Gemini CLI hook(服务零改动) |
| **Phase 3 (可选)** | Ollama 离线 capturer、记忆管理 CLI、衰减 / 合并 consolidation |

## 13. 关键决策记录

| 维度 | 决策 |
|---|---|
| 语言 / 栈 | Python · FastMCP · fastembed(all-MiniLM-L6-v2/384) · sqlite-vec · 项目 venv |
| 部署 | launchd 宿主常驻,直接调 claude CLI(不用 Docker——claude 订阅认证绑宿主 Keychain,容器进不去) |
| 捕获 | `claude -p` 抽取(主)+ 原文兜底,可插拔 Capturer 接口 |
| 隔离 | 全局一池 + project/agent/tag,默认 current+global,可 all |
| 注入 | SessionStart 自动 top-6 + MCP `search` 主动 |
| embedding | all-MiniLM-L6-v2 / 384 维(与 self-reflect、doobidoo 同源,便于将来互通) |
