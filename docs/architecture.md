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

普通 HTTP 请求只从 `Authorization: Bearer <session_id>` 读取登录凭据。Cookie 和普通 HTTP 查询参数不参与认证，`/api/auth/me` 也不会回传凭据。视频流和下载 WebSocket 因浏览器原生元素不能设置自定义请求头，P0 期间仍允许显式 `session_id` 查询参数；后续由短期 ticket 替换。

访客设备 ID 与签名保存在 `localStorage`，只有配置了非默认 `GUEST_SECRET` 时才开放访客能力。普通 HTTP 使用 `X-Guest-Id` / `X-Guest-Sig`，视频流和 WebSocket 可使用对应查询参数。显式 Bearer 或 query Session 一旦出现就必须独立验证成功；格式错误、过期或不存在时直接拒绝，不能降级到另一组 Session 或访客身份。

迁移 `20260713_invalidate_legacy_auth_sessions` 在一个 `BEGIN IMMEDIATE` 事务中删除旧 Session 并写入版本标记，只执行一次。部署 P0 后所有已登录用户必须重新登录。

## 媒体代理安全

缩略图和视频代理共用统一媒体安全层：底层只接受 HTTPS，并按完整域名标签匹配已知平台 CDN。缩略图入口会先用结构化 URL 解析把平台返回的旧 HTTP 地址升级为 HTTPS，再进入同一安全层；视频代理仍直接拒绝 HTTP。每次重定向都会重新解析并校验公网 IP，最多跟随 3 跳；连接固定到已校验 IP，同时保留原域名用于 TLS SNI 和证书验证。

缩略图只接受 JPEG、PNG、WebP、GIF 和 AVIF，响应上限 10 MiB；HTML、SVG、未知 MIME 和超限内容会被拒绝。视频只接受 `video/*`、`audio/*` 和 `application/octet-stream`。代理响应带 `X-Content-Type-Options: nosniff` 和隔离 CSP，服务不启用通配 CORS。未知平台仍可解析和下载，但不提供代理缩略图或在线播放。

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

完整生成、部分 AI 产物和后台 Whisper 完成统一使用 generate-then-swap。摘要完整非空、结果可 JSON 序列化后，才在单个 `BEGIN IMMEDIATE` 事务中替换视频信息、字幕、Whisper、AI 缓存、当前身份历史和 `SUCCESS` 用量。空结果、异常或任一 SQL 失败都会保留旧共享缓存且不消耗额度。

## 后台任务

任务状态流：

```text
queued -> downloading -> transcribing -> generating -> done
                                         `-> failed / cancelled
```

- `core/job_store.py`：任务持久化、原子领取、查询与取消。
- `core/job_scheduler.py`：一次运行一个 Whisper 子进程。
- `workers/whisper_worker.py`：通过 JSON Lines 报告进度和结果。
- `core/background_pipeline.py`：生成后台结果，成功后交给原子提交层保存。
- `core/generation_commit.py`：验证生成结果并原子替换缓存、字幕、历史和用量。

服务启动时会恢复被中断的任务；取消会终止当前子进程并清理临时结果。业务失败进入终态，不无限重试。

视频解析结果会分别保留播放流和最佳音频流。提交 Whisper 任务时，解析信息随任务 payload 持久化；仍有效的音频直链通过 `--audio-url` 传给 worker。worker 优先直接下载音频 CDN，避免 B 站在短时间内重复抓取视频页面触发 `412`；直链缺失或失效时才回退到原视频 URL。旧缓存没有音频直链时，B 站任务会先刷新解析信息再入队。

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
