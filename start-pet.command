#!/bin/bash
set -euo pipefail

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v node >/dev/null 2>&1; then
  echo "未找到 Node.js。请先安装 Node.js 22.12+。" >&2
  exit 1
fi
if [ ! -d "$APP_DIR/runtime/node_modules" ]; then
  echo "依赖未安装。请先在项目目录运行：bash setup-macos.command" >&2
  exit 1
fi
export DSH_HOME="$APP_DIR/data"
cd "$APP_DIR"
exec node "$APP_DIR/runtime/lib/standalone.js" "$@"
