#!/usr/bin/env bash
# memhub 记忆同步 — 把 Claude 的 curated memory/*.md 通过 git 同步到你的私有仓库。
# 只同步 markdown 记忆；绝不碰会话日志(.jsonl)，也不碰 SQLite 库（库是本地派生物，pull 后重建）。
#
#   memory-sync.sh init <git-repo-url>   首台：在 ~/.claude/projects 建库、白名单、首推
#   memory-sync.sh link <git-repo-url>   其它机：接入已有远端库（保留本地已有记忆）
#   memory-sync.sh push                  本机记忆 → 远端
#   memory-sync.sh pull                  远端 → 本机，并立即重建检索库
set -euo pipefail

ROOT="${MEMHUB_MEMORY_ROOT:-$HOME/.claude/projects}"   # = config.MEMORY_PROJECTS_ROOT
MEMHUB_URL="${MEMHUB_URL:-http://127.0.0.1:37650}"

say() { printf '\033[1;34m▸ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# 白名单 .gitignore：默认忽略一切，只放行 memory 目录里的 md。已实测能挡住所有 .jsonl/.json。
GITIGNORE_CONTENT='# memhub 记忆同步：默认忽略 ~/.claude/projects 下一切（含会话 .jsonl）
*
# 允许 git 递归进入子目录，否则下面的放行到不了深层
!*/
# 只放行任意项目 memory 目录里的 markdown
!*/memory/**/*.md
# 保留本文件自身
!.gitignore'

# 安全闸：第二道防线（白名单是第一道）。暂存区只允许 memory 下的 md 和 .gitignore，
# 发现任何别的文件（误加的 .jsonl 等）立即回滚并中止，绝不硬传。
assert_safe_staging() {
  local bad
  bad=$(git -C "$ROOT" diff --cached --name-only | grep -vE '(^|/)memory/.+\.md$|^\.gitignore$' || true)
  if [ -n "$bad" ]; then
    git -C "$ROOT" reset -q
    printf '\033[1;31m✗ 暂存区出现非记忆文件，已中止以防泄露：\033[0m\n%s\n' "$bad" >&2
    exit 1
  fi
}

cmd_init() {
  local url="${1:-}"
  [ -n "$url" ] || die "用法：memory-sync.sh init <git-repo-url>"
  [ -d "$ROOT" ] || die "找不到 $ROOT"
  cd "$ROOT"
  if [ ! -d .git ]; then
    say "在 $ROOT 初始化 git"
    git init -q
    git branch -M main
  fi
  printf '%s\n' "$GITIGNORE_CONTENT" > .gitignore
  git add -A
  assert_safe_staging
  git diff --cached --quiet || git commit -q -m "chore(memory): initial memory snapshot"
  if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$url"
  else
    git remote add origin "$url"
  fi
  say "推送到 $url"
  git push -u origin main
  say "完成 ✅ 之后用 'push' / 'pull' 同步"
}

cmd_link() {
  local url="${1:-}"
  [ -n "$url" ] || die "用法：memory-sync.sh link <git-repo-url>"
  mkdir -p "$ROOT"; cd "$ROOT"
  [ -d .git ] && die "$ROOT 已是 git 仓库，直接用 'pull'"
  say "接入远端记忆仓库 $url"
  git init -q
  git branch -M main
  printf '%s\n' "$GITIGNORE_CONTENT" > .gitignore
  git remote add origin "$url"
  git fetch -q origin main || die "拉取远端 main 失败，确认 url，且首台已先跑过 init"
  git reset -q origin/main                                  # index/HEAD=远端，工作区本地 md 原样保留
  git branch --set-upstream-to=origin/main main >/dev/null 2>&1 || true  # 建立跟踪，之后 push/pull 免参数
  git ls-files --deleted -z | xargs -0 -r git checkout -- 2>/dev/null || true  # 远端有本地缺的→落地，不覆盖本地任何文件
  say "重建本地检索库（zero-LLM，幂等）"
  curl -fsS -X POST "$MEMHUB_URL/sync-memory" || say "服务未响应；后台每 5 分钟会自动同步"
  echo
  say "接入完成 ✅ 本地原有记忆已保留；要把它们也推上去就跑：memory-sync.sh push"
}

cmd_push() {
  cd "$ROOT"
  [ -d .git ] || die "$ROOT 还没初始化，先跑：memory-sync.sh init <url>"
  git add -A
  assert_safe_staging
  if git diff --cached --quiet; then
    say "没有记忆变化，无需同步"; return 0
  fi
  git commit -q -m "chore(memory): sync $(date '+%F %H:%M')"
  git push
  say "已推送 ✅"
}

cmd_pull() {
  cd "$ROOT"
  [ -d .git ] || die "$ROOT 还没初始化，先跑：memory-sync.sh init <url>"
  say "拉取远端记忆"
  git pull --rebase
  say "重建本地检索库（zero-LLM，幂等）"
  curl -fsS -X POST "$MEMHUB_URL/sync-memory" || say "服务未响应；后台每 5 分钟会自动同步"
  echo
  say "已更新 ✅"
}

case "${1:-}" in
  init) shift; cmd_init "$@" ;;
  link) shift; cmd_link "$@" ;;
  push) cmd_push ;;
  pull) cmd_pull ;;
  *)    die "用法：memory-sync.sh {init <url>|link <url>|push|pull}" ;;
esac
