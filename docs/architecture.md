# VideoMind 架构说明

> 本文档描述当前代码实际采用的架构。若其他说明与本文冲突，以代码和本文为准。

## 设计约束

- 目标环境：4 核 CPU、4GB 内存的 Linux 云服务器
- 使用场景：单人、低并发
- 部署形态：模块化单体，单个 FastAPI / Uvicorn worker
- 唯一数据库：SQLite WAL，同时保存业务数据和后台任务
- 不依赖 Redis、PostgreSQL、ChromaDB、跨视频语义 RAG 或常驻任务 Worker
- AI 通过外部 Anthropic 兼容 API 调用
- Whisper 只在需要时启动一个短生命周期子进程
- Node.js 仅用于构建前端，生产请求由 FastAPI 托管 `frontend/dist`

## 运行结构

```text
浏览器
  -> Caddy（可选，负责 HTTPS）
  -> FastAPI / Uvicorn（1 worker）
       -> API + frontend/dist
       -> SQLite WAL（业务数据 + background_jobs）
       -> 外部 AI API
       -> 最多 1 个 Whisper 子进程
```

这是一个模块化单体。API、认证、历史、任务调度和静态前端在同一后端进程中运行，便于个人服务器部署和维护；Whisper 单独使用子进程，是为了在任务结束后让操作系统完整回收模型内存。

## 启动生命周期

`backend/main.py` 的 FastAPI lifespan 按以下顺序启动：

1. 创建运行目录
2. 初始化 SQLite 业务表、缓存表和 `background_jobs` 表
3. 按配置创建管理员并清理过期 Session
4. 恢复服务重启时中断的后台任务
5. 启动一个轻量调度协程

模块导入阶段不会创建数据库或运行数据库初始化。可选 AI、Whisper 或 FFmpeg 缺失时，核心网站仍应能够启动。

## 数据与目录

本地开发默认把运行数据放在仓库内，并由 Git 忽略：

| 内容 | 本地默认路径 |
|------|--------------|
| SQLite 数据库 | `backend/db/knowledge.db` |
| AI 服务商配置 | `backend/data/ai_config.json` |
| 临时任务文件 | `backend/temp` |
| 下载文件 | `backend/downloads` |
| Whisper 模型 | `backend/data/whisper_models` |

生产环境统一放在代码目录外的 `/var/lib/videomind`：

| 内容 | 生产路径 |
|------|----------|
| SQLite 数据库 | `/var/lib/videomind/db/knowledge.db` |
| AI 服务商配置 | `/var/lib/videomind/ai_config.json` |
| 临时任务文件 | `/var/lib/videomind/temp` |
| 下载文件 | `/var/lib/videomind/downloads` |
| Whisper 模型 | `/var/lib/videomind/whisper_models` |
| SQLite 备份 | `/var/lib/videomind/backups` |

对应环境变量是 `DB_PATH`、`AI_CONFIG_PATH`、`TEMP_DIR`、`DOWNLOAD_DIR`、`WHISPER_MODELS_DIR` 和 `BACKUP_DIR`。`deploy/install.sh` 会写入尚未显式配置的路径，但不会覆盖用户已有配置。

首次从旧版升级时，如果 `.env` 没有显式 `DB_PATH` 且旧数据库仍在 `backend/db/knowledge.db`，安装脚本会使用 SQLite Backup API 迁移到生产数据目录。目标数据库已经存在时绝不覆盖。

正常 `git pull` 和 `deploy/update.sh` 不会删除历史。历史丢失通常只可能来自删除数据目录、覆盖数据库、修改 `DB_PATH`、使用 `git clean -fdx`，或重新克隆后没有恢复生产数据。

## SQLite 与搜索

SQLite 保存视频、字幕、AI 结果、用户、Session、历史、缓存和后台任务。当前采用 WAL、`busy_timeout` 和单 Uvicorn worker，适合低并发单机使用。

历史搜索统一使用 `GET /api/history?q=关键词` 的 SQLite 关键词查询。跨视频向量索引和语义检索已经删除；单视频总结、笔记、思维导图和问答不受影响。

## 后台任务

`background_jobs` 的主要状态为：

```text
queued -> downloading -> transcribing -> generating -> done
                                            +-> failed
queued / active ---------------------------> cancelled
```

- `backend/core/job_store.py`：任务持久化、查询、取消和恢复
- `backend/core/job_scheduler.py`：原子领取任务并保证单任务执行
- `backend/workers/whisper_worker.py`：加载模型并通过 JSON Lines 报告进度
- `backend/core/background_pipeline.py`：转录结束后的字幕保存和 AI 流程

调度器使用 SQLite 原子领取最早任务。Whisper 子进程固定使用 CPU 友好的低并发参数；取消时先 terminate，超时后 kill，并清理任务临时目录。服务重启后，中断任务重新排队并从头执行；视频失效、模型缺失等业务错误直接失败，不无限重试。

## 能力降级与健康检查

| 能力缺失 | 行为 |
|----------|------|
| AI SDK 或有效配置缺失 | AI 接口不可用，解析、下载和历史仍可用 |
| Faster-Whisper 或模型缺失 | 仅禁用无字幕视频的本地转录 |
| FFmpeg 缺失 | 禁用 Whisper，并影响需要音视频合并的下载 |

健康端点：

- `GET /api/health/live`：只表示进程存活
- `GET /api/health/ready`：检查 SQLite 和必要运行目录
- `GET /api/capabilities`：报告 AI、Whisper 和 FFmpeg 状态

## 部署与运维

- `deploy/install.sh`：创建运行用户和数据目录、安装依赖、构建前端、安装 systemd
- `deploy/update.sh`：先在线备份数据库，再拉取代码、安装依赖、构建并重启
- `deploy/backup.sh`：使用 SQLite Backup API 创建一致性备份
- `deploy/cleanup.sh`：清理过期临时文件和下载文件
- `videomind.service`：单 worker、`MemoryMax=3G`、异常退出自动拉起、日志进入 journald
- `videomind-maintenance.timer`：每日执行备份和清理

4GB 内存服务器建议配置 2GB swap，防止偶发内存峰值导致服务被系统直接终止。生产环境不运行 Vite 或其他 Node.js 常驻进程。

## 明确不做

- 不引入微服务或独立任务集群
- 不引入 Redis、PostgreSQL、ChromaDB 或跨视频 RAG
- 不常驻加载 Whisper 模型
- 不把数据库、密钥、模型、下载文件、备份或临时计划提交到 Git
