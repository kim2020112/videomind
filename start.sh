#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$PROJECT_ROOT/.venv"

echo "================================"
echo "  AI 视频知识平台 - 启动中..."
echo "================================"
echo ""

# 检查 .venv 是否存在
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "[!] 未找到 .venv，正在创建虚拟环境..."
    python3.12 -m venv "$VENV_DIR"
    echo "[*] 安装核心依赖..."
    "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements-core.txt"
    echo ""
    echo "[!] 核心依赖已安装。如需 AI/Whisper 功能，请运行："
    echo "    $VENV_DIR/bin/pip install -r \"$BACKEND_DIR/requirements.txt\""
    echo ""
fi

PYTHON_PATH="$VENV_DIR/bin/python"

echo "[1/2] 启动后端服务 (FastAPI)..."
cd "$BACKEND_DIR"
"$PYTHON_PATH" -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "[2/2] 启动前端开发服务器 (Vite)..."
cd "$PROJECT_ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "================================"
echo "  启动完成!"
echo "  前端: http://localhost:5173"
echo "  后端: http://localhost:8000"
echo "  API文档: http://localhost:8000/docs"
echo "  能力状态: http://localhost:8000/api/capabilities"
echo "================================"
echo ""

# 捕获 Ctrl+C 退出
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
