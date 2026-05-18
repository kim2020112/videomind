import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# AI API 配置
AI_PROVIDER = os.getenv("AI_PROVIDER", "deepseek")  # deepseek | openai | openrouter
AI_API_KEY = os.getenv("AI_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
AI_BASE_URL = os.getenv("AI_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic"))
AI_MODEL = os.getenv("AI_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))

# Prompt 版本
PROMPT_VERSION = int(os.getenv("PROMPT_VERSION", "1"))

# 数据库
DB_PATH = BASE_DIR / "db" / "knowledge.db"

# ChromaDB
CHROMA_PATH = BASE_DIR / "data" / "chroma"

# 临时文件（视频/音频处理后删除）
TEMP_DIR = BASE_DIR / "temp"

# 下载目录（保留下载功能）
DOWNLOAD_DIR = BASE_DIR / "downloads"

# Whisper（Faster-Whisper 转录兜底）
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")  # tiny | base | small | medium | large
WHISPER_MODELS_DIR = BASE_DIR / "data" / "whisper_models"

# Whisper 字幕校正（AI 后处理，修正语音识别错误）
SUBTITLE_CORRECTION_ENABLED = os.getenv("SUBTITLE_CORRECTION_ENABLED", "true").lower() == "true"
SUBTITLE_CORRECTION_MAX_CHARS = int(os.getenv("SUBTITLE_CORRECTION_MAX_CHARS", "15000"))

# Whisper 转录最大视频时长（秒），超过则跳过，避免 CPU 转录过久
WHISPER_MAX_DURATION = int(os.getenv("WHISPER_MAX_DURATION", "120"))

# HuggingFace 镜像（国内加速，首次下载 Whisper 模型用）
_HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
if _HF_ENDPOINT:
    os.environ.setdefault("HF_ENDPOINT", _HF_ENDPOINT)

# 任务队列
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "2"))

# 用户体系
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")       # 空则不自动创建 admin
REGISTRATION_ENABLED = os.getenv("REGISTRATION_ENABLED", "true").lower() == "true"
GUEST_SECRET = os.getenv("GUEST_SECRET", "videomind-guest-2026")
GUEST_DAILY_LIMIT = int(os.getenv("GUEST_DAILY_LIMIT", "3"))
USER_DAILY_LIMIT = int(os.getenv("USER_DAILY_LIMIT", "20"))

# 确保目录存在
for d in [DB_PATH.parent, CHROMA_PATH, TEMP_DIR, DOWNLOAD_DIR]:
    d.mkdir(parents=True, exist_ok=True)
