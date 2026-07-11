@echo off
echo ================================
echo   AI 视频知识平台 - 启动中...
echo ================================
echo.

set PROJECT_ROOT=%~dp0
set BACKEND_DIR=%PROJECT_ROOT%backend
set VENV_DIR=%PROJECT_ROOT%.venv

REM 检查 .venv 是否存在
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [!] 未找到 .venv，正在创建虚拟环境...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [X] 创建虚拟环境失败，请确保 Python 3.12 已安装
        pause
        exit /b 1
    )
    echo [*] 安装核心依赖...
    "%VENV_DIR%\Scripts\pip.exe" install -r "%BACKEND_DIR%\requirements-core.txt"
    echo.
    echo [!] 核心依赖已安装。如需 AI/Whisper 功能，请运行：
    echo     %VENV_DIR%\Scripts\pip.exe install -r "%BACKEND_DIR%\requirements.txt"
    echo.
)

set PYTHON_PATH=%VENV_DIR%\Scripts\python.exe

echo [1/2] 启动后端服务 (FastAPI)...
cd /d "%BACKEND_DIR%"
start "Backend" "%PYTHON_PATH%" -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

echo [2/2] 启动前端开发服务器 (Vite)...
cd /d "%PROJECT_ROOT%frontend"
start "Frontend" npm run dev

echo.
echo ================================
echo   启动完成!
echo   前端: http://localhost:5173
echo   后端: http://localhost:8000
echo   API文档: http://localhost:8000/docs
echo   能力状态: http://localhost:8000/api/capabilities
echo ================================
echo.
pause
