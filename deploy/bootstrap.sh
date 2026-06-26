#!/usr/bin/env bash
# memhub bootstrap — 在一台新 mac 上从零拉起 memhub（代码 + 服务 + hooks + 注入）。
# 幂等：重复运行安全。可单独 curl 运行，会自行 clone 仓库：
#   curl -fsSL https://raw.githubusercontent.com/codesfly/memhub/main/deploy/bootstrap.sh | bash
set -euo pipefail

REPO_URL="${MEMHUB_REPO:-https://github.com/codesfly/memhub}"
REPO_DIR="${MEMHUB_DIR:-$HOME/Code/memhub}"   # 路径写死约定：install.py 与 launchd plist 都依赖它
MEMHUB_URL="${MEMHUB_URL:-http://127.0.0.1:37650}"

say() { printf '\033[1;34m▸ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# 1) 前置检查
[ "$(uname)" = "Darwin" ] || die "目前只支持 macOS（服务基于 launchd）"
command -v git     >/dev/null || die "需要 git"
command -v python3 >/dev/null || die "需要 python3 (>=3.12)"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
  || die "需要 Python 3.12+，当前 $(python3 -V 2>&1)"

# 2) 代码就位（不存在则 clone，存在则尽量更新）
if [ -d "$REPO_DIR/.git" ]; then
  say "更新已有仓库 $REPO_DIR"
  git -C "$REPO_DIR" pull --ff-only || say "pull 跳过（本地有改动），沿用现有代码"
else
  say "克隆 $REPO_URL → $REPO_DIR"
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone "$REPO_URL" "$REPO_DIR"
fi

# 3) 依赖
say "创建 venv + 安装依赖"
[ -d "$REPO_DIR/.venv" ] || python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install -q -e "$REPO_DIR"

# 4) hooks + launchd 服务（install.py 幂等：已挂的不重复加）
say "安装 hooks + launchd 服务"
"$REPO_DIR/.venv/bin/python" "$REPO_DIR/deploy/install.py" --with-launchd

# 5) 等服务就绪（launchd 异步拉起进程）
say "等待服务就绪 $MEMHUB_URL"
ready=
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$MEMHUB_URL/health" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ -n "$ready" ] || die "服务 30s 内未就绪，排查日志：~/.memhub/memhub.err"

# 6) 开启注入（新机器默认 off —— 这是大多数人换机后"装了却不注入"的坑，替你打开）
say "开启记忆注入"
curl -fsS -X PATCH "$MEMHUB_URL/settings" \
  -H 'Content-Type: application/json' -d '{"inject_enabled": true}' >/dev/null

# 7) 收尾
say "完成 ✅"
echo "  健康  : $(curl -fsS "$MEMHUB_URL/health")"
echo "  设置  : $(curl -fsS "$MEMHUB_URL/settings")"
echo "  仓库  : $REPO_DIR"
echo
echo "下一步 — 同步记忆："
echo "  首台（有记忆要发布）: $REPO_DIR/deploy/memory-sync.sh init <私有仓库-git-url>"
echo "  其它机（接入已有库）: $REPO_DIR/deploy/memory-sync.sh link <私有仓库-git-url>"
echo "  日常同步           : $REPO_DIR/deploy/memory-sync.sh push  /  pull"
