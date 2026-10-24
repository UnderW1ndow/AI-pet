#!/bin/bash
set -euo pipefail

APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PYTHON_BIN="$APP_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "请先在项目目录运行：bash setup-macos.command" >&2
  exit 1
fi
export DSH_HOME="$APP_DIR/data"
cd "$APP_DIR"
exec "$PYTHON_BIN" "$APP_DIR/ai_pet.py" "$@"
