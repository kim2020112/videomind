# VideoMind 架构说明

本文描述当前代码实际采用的架构。VideoMind 是面向单机、低并发场景的模块化单体：FastAPI 负责 API、认证、SQLite 数据访问和后台调度；Vue 负责浏览器交互；Whisper 只在任务执行期间运行独立子进程。

## 运行结构

开发模式：

```text
浏览器 -> Vite :5173 -> /api、/ws 代理 -> FastAPI :8000
```

生产模式：

```text
浏览器 -> 反向代理（可选） -> FastAPI :8000
                                  |- frontend/dist
                                  |- SQLite WAL
                                  |- 外部 AI / 视频平台 API
                                  `- Whisper 子进程（按需）
```

`backend/main.py` 在 `frontend/dist` 存在时直接挂载静态前端。Vue Router 的工作区与历史深链回退到 `index.html`，缺失的静态资源仍返回 404。后台任务调度器和 API 运行在同一 FastAPI 进程中，因此生产环境使用单个 Uvicorn worker。

## 前端结构

- `frontend/src/App.vue`：认证、能力、路由和工作台状态编排。
- `frontend/src/router.js`：`/`、`/workspace`、`/history` 和历史详情路由。
- `frontend/src/components/`：页面区域、Dialog、下载、视频和 AI 结果组件。
- `frontend/src/composables/`：认证、能力、总结、下载和后台任务状态。

工作台 URL 保存当前视频链接、标签页和分 P。刷新、前进后退或打开历史详情时，前端从路由查询参数恢复状态。History、管理员设置、视频播放器和 markmap 等较重功能按需加载。

## 身份与会话

登录和注册会创建不透明的 `session_id`。前端将它保存在 `sessionStorage`，使登录状态在刷新后保留，同时隔离不同浏览器窗口。

尚未迁移的旧窗口可以先通过共享 Cookie 调用 `/api/auth/me`；响应会返回当前会话 ID，前端随即将它固化为该窗口的显式凭据。此后其他窗口改写共享 Cookie 不会再改变该窗口的身份。

受保护请求的会话解析顺序：

1. `Authorization: Bearer <session_id>`
2. `session_id` 查询参数（WebSocket、`<video src>` 等不能设置普通请求头的场景）
3. 当前窗口退出后发送的 `X-Session-Mode: guest` 或 `session_mode=guest`
4. 兼容旧客户端的 `vm_session` Cookie

只要请求显式携带窗口凭据或 guest 模式，即使凭据无效、过期或页面刷新，也不能回退到共享 Cookie。访客设备 ID 与签名仍保存在 `localStorage`；只有配置了非默认 `GUEST_SECRET` 时才开放访客解析能力。

## 字幕管线

字幕获取顺序为：

1. SQLite 已缓存字幕。
2. B 站 CC 或其他平台原生字幕。
3. yt-dlp 可用字幕。
4. Whisper 本地转录。

B 站 CC 查询使用三态语义：

- `available`：已取得可用字幕。
- `absent`：平台成功响应并明确没有字幕。
- `unavailable`：限流、网络、登录要求或无效响应导致无法可靠判断。

只有 `absent` 才允许进入 Whisper 或无字幕回退；`unavailable` 返回可重试错误，避免把平台故障误判为视频没有字幕。多分 P 视频使用所选分 P 的精确 `cid`，不会静默回退到 P1。

短链解析完成后，缓存、字幕和学习状态统一使用 yt-dlp 返回的规范 `webpage_url`，并保留原始 `p` 参数。基础多分 P URL 可展示全集总时长；明确选择分 P 后，Whisper 时长上限、ETA 和进度使用该分 P 自身时长。

## SQLite、缓存与学习状态

SQLite 保存用户、会话、视频、字幕、AI 输出、学习历史、缓存和 `background_jobs`。连接启用 WAL、`busy_timeout` 和外键。

主要缓存：

- `video_info_cache`：按精确 URL 哈希保存视频与分 P 元数据。
- `ai_cache`：按精确 URL 哈希保存完整 AI 学习结果。
- `whisper_cache`：按精确 URL 哈希保存本地转录结果。

同一 B 站视频的分组指纹只用于保留策略和非分 P 旧链接兼容，不是缓存唯一身份。读取缓存不会批量改写 URL、哈希或用户历史，删除一个分 P 也不会删除相邻分 P。

“已学习”是当前身份的派生状态，不写入共享视频元数据。只有当前用户或访客的 `user_history.status = done`，并且同一 URL 存在非空 AI 缓存时，对应分 P 才显示为已学习。成功重试会把该身份原有的失败历史更新为 `done`。

## 后台任务

任务状态流：

```text
queued -> downloading -> transcribing -> generating -> done
                                         `-> failed / cancelled
```

- `core/job_store.py`：任务持久化、原子领取、查询与取消。
- `core/job_scheduler.py`：一次运行一个 Whisper 子进程。
- `workers/whisper_worker.py`：通过 JSON Lines 报告进度和结果。
- `core/background_pipeline.py`：保存字幕、AI 结果和用户历史状态。

服务启动时会恢复被中断的任务；取消会终止当前子进程并清理临时结果。业务失败进入终态，不无限重试。

## 启动与能力降级

FastAPI lifespan 依次完成：

1. 创建运行目录并初始化 SQLite 表。
2. 创建可选管理员并清理过期 Session。
3. 检测 AI、Whisper、FFmpeg 与访客能力。
4. 恢复并启动后台任务调度器。

模块导入阶段不创建数据库。AI SDK/配置、Whisper 模型或 FFmpeg 缺失时，只关闭对应能力，核心网站、认证、解析和历史功能仍可运行。

## 运行数据

默认路径均位于 `backend/` 下并被 Git 忽略：

| 内容 | 默认路径 | 可覆盖变量 |
|---|---|---|
| SQLite 数据库 | `backend/db/knowledge.db` | `DB_PATH` |
| AI 服务商配置 | `backend/data/ai_config.json` | `AI_CONFIG_PATH` |
| 临时文件 | `backend/temp/` | `TEMP_DIR` |
| 下载文件 | `backend/downloads/` | `DOWNLOAD_DIR` |
| Whisper 模型 | `backend/data/whisper_models/` | `WHISPER_MODELS_DIR` |

数据库、密钥、模型、下载内容、旧向量索引和会话交接文件不得提交到 Git。
