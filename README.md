# VideoMind

面向个人使用的 AI 视频学习网站。支持视频解析与下载、字幕提取、单视频 AI 总结、笔记、思维导图、问答和学习历史。

## 设计目标

- 适合 4C4G 单机云服务器和低并发个人使用
- SQLite 是唯一数据库，同时保存业务数据和后台任务
- 不依赖 Redis、PostgreSQL、ChromaDB、Docker 或独立 Worker 服务
- FastAPI 单进程托管 API 和构建后的 Vue 前端
- Whisper 一次只运行一个短生命周期子进程，结束后释放模型内存
- 服务重启时，进行中的转录任务自动重新排队并从头执行
- 历史搜索使用 SQLite 关键词搜索，不提供跨视频语义 RAG
- 生产数据统一放在 `/var/lib/videomind`，与 Git 代码目录分离

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite |
| 后端 | FastAPI + Uvicorn |
| 数据与任务队列 | SQLite WAL |
| AI | 外部 Anthropic 兼容 API |
| 本地转录 | Faster-Whisper small / CPU int8 子进程 |
| 视频处理 | yt-dlp + FFmpeg |
| 生产运维 | systemd，可选 Caddy |

## 本地开发

环境要求：Python 3.12、Node.js 22、FFmpeg。

Linux / macOS：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements-core.txt
.venv/bin/pip install -r backend/requirements-ai.txt
.venv/bin/pip install -r backend/requirements-whisper.txt
npm --prefix frontend install
cp backend/.env.example backend/.env
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r backend\requirements-core.txt
.\.venv\Scripts\python -m pip install -r backend\requirements-ai.txt
.\.venv\Scripts\python -m pip install -r backend\requirements-whisper.txt
npm --prefix frontend install
Copy-Item backend\.env.example backend\.env
```

分别在两个终端启动后端和前端；以下命令都从仓库根目录执行：

```bash
# 终端 1：后端（Linux / macOS）
.venv/bin/python -m uvicorn main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

# 终端 2：前端
npm --prefix frontend run dev
```

Windows 后端命令：

```powershell
.\.venv\Scripts\python -m uvicorn main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

开发地址：前端 `http://127.0.0.1:5173`，API `http://127.0.0.1:8000/docs`。

## Whisper 模型

模型目录默认为：

```text
backend/data/whisper_models/faster-whisper-small/
  config.json
  model.bin
  tokenizer.json
  vocabulary.txt
```

也可通过 `WHISPER_MODELS_DIR` 指定模型根目录。模型或 FFmpeg 缺失时，仅禁用 Whisper，核心网站仍可启动。

## 生产部署

推荐把代码放在 `/opt/videomind`，把持久化数据放在 `/var/lib/videomind`。首次安装执行：

```bash
sudo APP_DIR=/opt/videomind \
  APP_USER=videomind \
  DATA_DIR=/var/lib/videomind \
  bash deploy/install.sh
```

若 `videomind` 用户不存在，安装脚本会自动创建。脚本还会创建 Python venv、安装三组依赖、构建前端、配置生产数据路径并安装：

- `videomind.service`：单 Uvicorn worker，`MemoryMax=3G`
- `videomind-maintenance.timer`：每日 SQLite 在线备份和文件清理

安装后编辑 `/opt/videomind/backend/.env`，至少配置 `AI_API_KEY`、`ADMIN_PASSWORD` 和随机 `GUEST_SECRET`，然后执行 `sudo systemctl restart videomind`。生产进程只监听 `127.0.0.1:8000`，公网访问建议参考 `deploy/Caddyfile.example` 配置 Caddy 自动 HTTPS。4GB 内存服务器建议额外配置 2GB swap。

旧版若仍使用 `/opt/videomind/backend/db/knowledge.db`，首次运行新版 `install.sh` 时会在不覆盖已有目标库的前提下，通过 SQLite Backup API 迁移历史数据库和 AI 配置。已有显式路径配置始终保留。

更新：

```bash
sudo APP_DIR=/opt/videomind bash deploy/update.sh
```

更新流程固定为：在线备份数据库、`git pull --ff-only`、安装依赖、构建前端、重启 systemd 服务。更新不会运行 Vite 常驻进程。

日志与状态：

```bash
systemctl status videomind
journalctl -u videomind -f
curl http://127.0.0.1:8000/api/health/live
curl http://127.0.0.1:8000/api/health/ready
```

## 关键 API

| 端点 | 说明 |
|---|---|
| `GET /api/health/live` | 进程存活检查 |
| `GET /api/health/ready` | SQLite 与目录可写检查 |
| `GET /api/capabilities` | AI、Whisper、FFmpeg 能力状态 |
| `POST /api/parse` | 解析视频 |
| `POST /api/summarize/stream` | 单视频 AI 流水线 |
| `GET /api/subtitle/text` | 获取字幕；需要 Whisper 时返回 202 后台任务 |
| `GET /api/tasks/active` | 当前用户活跃任务 |
| `GET /api/tasks/{task_id}` | 任务状态、阶段和进度 |
| `POST /api/tasks/{task_id}/cancel` | 取消排队或运行中的任务 |
| `GET /api/history?q=...` | SQLite 关键词历史搜索 |

## 数据与备份

本地开发默认数据库是 `backend/db/knowledge.db`，因此本机首次登录后历史为空是正常现象。本地数据库被 Git 忽略，不会上传到 GitHub，也不会自动与服务器数据库同步。

生产环境默认使用：

| 内容 | 路径 |
|------|------|
| 历史与业务数据库 | `/var/lib/videomind/db/knowledge.db` |
| AI 服务商配置 | `/var/lib/videomind/ai_config.json` |
| 临时文件 | `/var/lib/videomind/temp` |
| 下载文件 | `/var/lib/videomind/downloads` |
| Whisper 模型 | `/var/lib/videomind/whisper_models` |
| 数据库备份 | `/var/lib/videomind/backups` |

`deploy/backup.sh` 使用 Python SQLite Backup API 创建一致性备份，默认保留 14 天。`deploy/cleanup.sh` 默认清理 2 天前临时文件和 14 天前下载文件，保留时间均可通过环境变量配置。

正常 `git pull` 或 `deploy/update.sh` 不会清空服务器历史。不要在生产目录执行 `git clean -fdx`，也不要删除 `/var/lib/videomind`。即使代码目录重新克隆，只要保留生产数据目录和 `.env` 中的路径，历史仍可恢复。

手工恢复数据库前先停止服务：

```bash
sudo systemctl stop videomind
sudo cp /var/lib/videomind/backups/knowledge-YYYYMMDD-HHMMSS.db \
  /var/lib/videomind/db/knowledge.db
sudo chown videomind:videomind /var/lib/videomind/db/knowledge.db
sudo systemctl start videomind
```

仅处理有权访问的内容，并遵守视频平台规则和版权要求。

## 默认管理员

仅在 `backend/.env` 配置了非空 `ADMIN_PASSWORD` 时，启动才会自动创建管理员：

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=请设置强密码
```

若管理员用户已存在，不会覆盖其密码。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 当前架构、数据流和任务模型 |
| [docs/development.md](docs/development.md) | 开发指南 |

版本变化以 Git 提交和 GitHub Release 为准，不再维护重复的手工 changelog。
