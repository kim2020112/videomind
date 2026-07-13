import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(__file__))

from core.logging_config import setup_logging, get_logger
setup_logging()

from config import DOWNLOAD_DIR, TEMP_DIR
from core.features import get_capabilities
from core.spa import SpaStaticFiles
from core.storage import initialize_storage

logger = get_logger(__name__)
from api.routes import router as api_router
from api.summary_routes import router as summary_router
from api.subtitle_text_routes import router as subtitle_text_router
from api.stream_routes import router as stream_router
from api.task_routes import router as task_router
from api.knowledge_routes import router as knowledge_router
from api.auth_routes import router as auth_router
from api.admin_routes import router as admin_router
from api.health_routes import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 初始化运行目录与 SQLite 表
    initialize_storage()
    # 2. 初始化认证
    from core.auth import ensure_admin, cleanup_expired_sessions
    ensure_admin()
    cleanup_expired_sessions()
    # 3. 日志
    logger.info(f"下载目录: {DOWNLOAD_DIR}")
    logger.info(f"临时目录: {TEMP_DIR}")
    logger.info(f"API 文档: http://localhost:8000/docs")
    # 4. 功能能力日志
    caps = get_capabilities()
    for feat, avail in caps.items():
        status = "enabled" if avail else "disabled"
        logger.info(f"Feature {feat}: {status}")
    from core.background_pipeline import finalize_whisper_job, update_terminal_history
    from core.job_scheduler import JobScheduler

    scheduler = JobScheduler(
        on_completed=finalize_whisper_job,
        on_terminal=update_terminal_history,
    )
    app.state.job_scheduler = scheduler
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="AI 视频知识平台",
    description="将视频转化为结构化知识：字幕提取、AI 总结、笔记与问答",
    version="2.0.0",
    lifespan=lifespan,
)

_cors_origins = os.getenv("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()] if _cors_origins != "*" else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(summary_router)
app.include_router(subtitle_text_router)
app.include_router(stream_router)
app.include_router(task_router)
app.include_router(knowledge_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(health_router)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIST = os.path.join(os.path.dirname(BASE_DIR), "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/", SpaStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    logger.info(f"生产模式: 前端已挂载 ({FRONTEND_DIST})")
else:
    logger.info(f"开发模式: 前端未构建，请单独启动 npm run dev")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
