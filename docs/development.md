# 开发指南

> 架构说明见 `docs/architecture.md`。安装、更新和备份总览见根目录 `README.md`。

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.12 | 后端运行时（仓库 `.python-version`） |
| Node.js | 22 | 前端开发与构建（仓库 `.nvmrc`） |
| FFmpeg | 任意 | yt-dlp 合并音视频、Whisper 音频处理 |

Windows 可从 [FFmpeg Builds](https://github.com/BtbN/FFmpeg-Builds/releases) 下载，并把 `bin/` 加入 PATH。

## 本地安装

Linux / macOS：

```bash
python3.12 -m venv .venv

# 最小可启动（认证 / 解析 / 下载 / 历史）
.venv/bin/pip install -r backend/requirements-core.txt

# 可选能力
.venv/bin/pip install -r backend/requirements-ai.txt
.venv/bin/pip install -r backend/requirements-whisper.txt

# 或一次装全量
.venv/bin/pip install -r backend/requirements.txt

npm --prefix frontend install
cp backend/.env.example backend/.env
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv

# 最小可启动
.\.venv\Scripts\python -m pip install -r backend\requirements-core.txt

# 可选能力，或改为安装 requirements.txt 一次装全量
.\.venv\Scripts\python -m pip install -r backend\requirements-ai.txt
.\.venv\Scripts\python -m pip install -r backend\requirements-whisper.txt

npm --prefix frontend install
Copy-Item backend\.env.example backend\.env
```

## 环境变量

复制 `backend/.env.example` 为 `backend/.env` 后按需修改。关键项：

```env
# 功能开关
FEATURE_AI=true
FEATURE_WHISPER=true

# AI
AI_PROVIDER=deepseek
AI_API_KEY=
AI_BASE_URL=https://api.deepseek.com/anthropic
AI_MODEL=deepseek-v4-flash

# 管理员（密码为空则不会自动创建 admin）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=

# 游客与限额
GUEST_SECRET=请改成随机字符串
GUEST_DAILY_LIMIT=3
USER_DAILY_LIMIT=20
REGISTRATION_ENABLED=true

# 可选路径覆盖
# DB_PATH=...
# AI_CONFIG_PATH=...
# TEMP_DIR=...
# DOWNLOAD_DIR=...
# WHISPER_MODELS_DIR=...
# BACKUP_DIR=...
```

兼容旧变量：`DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` 仍可读，但优先使用 `AI_*`。

`.env` 不要提交到 Git。

## 启动

### 方式一：脚本

- Windows：`start.bat`
- Linux / macOS：`start.sh`

### 方式二：手动

以下命令均从仓库根目录执行，并在两个终端分别运行：

```bash
# 后端（Linux / macOS）
.venv/bin/python -m uvicorn main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

# 前端（第二个终端）
npm --prefix frontend run dev
```

Windows 后端命令：

```powershell
.\.venv\Scripts\python -m uvicorn main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

默认地址：

| 服务 | 地址 |
|------|------|
| 前端 | http://127.0.0.1:5173 |
| 后端 | http://127.0.0.1:8000 |
| API 文档 | http://127.0.0.1:8000/docs |
| 能力状态 | http://127.0.0.1:8000/api/capabilities |

如果 5173 被占用，可临时：

```bash
npm --prefix frontend run dev -- --port 5174
```

## Whisper 模型（可选）

默认目录：

```text
backend/data/whisper_models/faster-whisper-small/
  config.json
  model.bin
  tokenizer.json
  vocabulary.txt
```

模型或 `faster-whisper` 缺失时，只禁用本地转录，不影响网站启动。

不要把模型权重提交到 Git；仓库根目录的 `faster-whisper-small/` 仅供本机临时使用，已被忽略。

## 目录结构（当前）

```text
videomind/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── .env.example
│   ├── requirements.txt              # 引用 core + ai + whisper
│   ├── requirements-core.txt
│   ├── requirements-ai.txt
│   ├── requirements-whisper.txt
│   ├── api/
│   │   ├── routes.py                 # 解析 / 下载 / 字幕下载
│   │   ├── stream_routes.py          # AI 流式总结 / 问答
│   │   ├── summary_routes.py
│   │   ├── subtitle_text_routes.py
│   │   ├── knowledge_routes.py       # 历史 / 标签
│   │   ├── task_routes.py            # 后台任务查询 / 取消
│   │   ├── auth_routes.py
│   │   ├── admin_routes.py
│   │   ├── health_routes.py
│   │   └── security.py
│   ├── core/
│   │   ├── auth.py
│   │   ├── cache.py
│   │   ├── features.py               # 能力检测与降级
│   │   ├── storage.py                # 运行目录与库初始化入口
│   │   ├── job_store.py              # background_jobs 持久化
│   │   ├── job_scheduler.py          # 单并发调度
│   │   ├── background_pipeline.py    # 任务完成后的业务收尾
│   │   ├── whisper.py
│   │   ├── ai_client.py
│   │   ├── downloader.py
│   │   └── pipeline/                 # 字幕 / 摘要 / 笔记 / 导图
│   ├── workers/
│   │   └── whisper_worker.py         # 短生命周期转录子进程
│   ├── tests/
│   ├── prompts/
│   ├── db/                           # 本地数据库（运行时，不提交）
│   ├── temp/                         # 本地临时文件（不提交）
│   ├── downloads/                    # 本地下载文件（不提交）
│   └── data/                         # 本地 AI 配置与模型（不提交）
├── frontend/
│   ├── src/
│   │   ├── App.vue
│   │   ├── components/
│   │   ├── composables/
│   │   │   ├── useAuth.js
│   │   │   ├── useDownloader.js
│   │   │   ├── useSummary.js
│   │   │   ├── useTaskPoller.js
│   │   │   └── useCapabilities.js
│   │   └── utils/
│   └── package.json
├── deploy/
│   ├── install.sh
│   ├── update.sh
│   ├── backup.sh
│   ├── cleanup.sh
│   ├── videomind.service
│   └── Caddyfile.example
├── docs/
│   ├── architecture.md
│   └── development.md
├── start.bat
├── start.sh
└── README.md
```

## 开发时该改哪里

| 目标 | 优先文件 |
|------|----------|
| 视频解析 / 下载 | `backend/core/downloader.py`、`backend/api/routes.py` |
| AI 总结 / 问答 | `backend/core/ai_client.py`、`backend/api/stream_routes.py`、`backend/prompts/` |
| 字幕与 Whisper | `backend/core/pipeline/subtitle.py`、`backend/core/whisper.py`、`backend/workers/whisper_worker.py` |
| 后台任务 | `backend/core/job_store.py`、`backend/core/job_scheduler.py`、`backend/api/task_routes.py` |
| 历史与搜索 | `backend/api/knowledge_routes.py`、`backend/core/cache.py` |
| 认证与权限 | `backend/core/auth.py`、`backend/api/auth_routes.py`、`backend/api/security.py` |
| 能力降级 | `backend/core/features.py`、`frontend/src/composables/useCapabilities.js` |
| 前端学习页 | `frontend/src/components/AiSummary.vue`、`HistoryPage.vue` |
| 任务轮询 UI | `frontend/src/composables/useTaskPoller.js` |

## 测试

```bash
.venv/bin/python -B -m unittest discover -s backend/tests -v
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python -B -m unittest discover -s backend/tests -v
```

当前测试覆盖任务存储、调度、存储初始化、无 RAG 约束和任务路由等核心行为。

## 生产构建

```bash
npm --prefix frontend run build
cd backend
../.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

生产环境下 FastAPI 会托管 `frontend/dist`。更完整的服务器安装请用 `deploy/install.sh`。

## 常见问题

**Q: 为什么没有默认 admin？**

A: 只有 `.env` 中配置了 `ADMIN_PASSWORD` 时才会自动创建。密码为空则不创建。

**Q: 登录后历史是空的？**

A: 本地历史保存在本机 `backend/db/knowledge.db`，不会从 GitHub 或服务器自动同步。新环境或新数据库本来就是空的。

**Q: AI / Whisper 不可用，网站还能开吗？**

A: 可以。核心能力（认证、解析、下载、历史）只依赖 `requirements-core.txt`。

**Q: 更新代码会不会丢历史？**

A: 生产历史默认保存在代码目录外的 `/var/lib/videomind/db/knowledge.db`。正常 `git pull` / `deploy/update.sh` 不会删除它。危险操作包括删除数据目录、覆盖数据库、修改 `DB_PATH` 或执行 `git clean -fdx`。

**Q: bcrypt / passlib 报错？**

A: 使用 `requirements-core.txt` 中的 `bcrypt==4.0.1`。`bcrypt 5.x` 与当前 passlib 不兼容。

**Q: 端口 5173 被占用？**

A: 前端可换端口，例如 `npm run dev -- --port 5174`。后端默认 8000。
