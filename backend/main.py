import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 确保 backend 目录在 Python 路径中
sys.path.insert(0, os.path.dirname(__file__))

from api.routes import router as api_router

app = FastAPI(
    title="万能视频下载器",
    description="基于 yt-dlp 的万能视频下载 API，支持 1800+ 平台",
    version="1.0.0",
)

# CORS 配置（开发模式）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(api_router)

# 创建下载目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 生产模式：托管前端静态文件
FRONTEND_DIST = os.path.join(os.path.dirname(BASE_DIR), "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    print(f"[启动] 生产模式: 前端已挂载 ({FRONTEND_DIST})")
else:
    print(f"[启动] 开发模式: 前端未构建，请单独启动 npm run dev")


@app.on_event("startup")
async def startup():
    print(f"[启动] 下载目录: {DOWNLOAD_DIR}")
    print(f"[启动] API 文档: http://localhost:8000/docs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )