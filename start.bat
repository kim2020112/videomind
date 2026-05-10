@echo off
echo ================================
echo   万能视频下载器 - 启动中...
echo ================================
echo.

set PYTHON_PATH=C:\Users\liu_j\AppData\Local\Programs\Python\Python314\python.exe

echo [1/2] 启动后端服务 (FastAPI)...
start "Backend" %PYTHON_PATH% -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

echo [2/2] 启动前端开发服务器 (Vite)...
cd frontend
start "Frontend" npm run dev
cd ..

echo.
echo ================================
echo   启动完成!
echo   前端: http://localhost:5173
echo   后端: http://localhost:8000
echo   API文档: http://localhost:8000/docs
echo ================================
echo.
pause