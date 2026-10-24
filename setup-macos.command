#!/bin/bash
set -euo pipefail

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="${AI_PET_PYTHON:-python3}"

for program in "$PYTHON_BIN" node npm ffmpeg; do
  if ! command -v "$program" >/dev/null 2>&1; then
    echo "缺少 $program。请先安装 Python 3.11+、Node.js 22.12+ 和 FFmpeg。" >&2
    exit 1
  fi
done

"$PYTHON_BIN" -c 'import sys, tkinter; assert sys.version_info >= (3, 11), "需要 Python 3.11 或更新版本"'
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 12)) { throw new Error("需要 Node.js 22.12 或更新版本") }'

"$PYTHON_BIN" -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
npm ci --prefix "$APP_DIR/runtime"

echo "依赖安装完成。运行 bash start-pet.command 启动桌宠，运行 bash start.command 打开制作界面。"
