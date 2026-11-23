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

需要保留独立前端端口时，可由 Vite Preview 在 `:5173` 提供同一份 `frontend/dist`，并代理 `/api`、`/ws` 到 FastAPI。长期运行环境不使用 Vite 开发服务器，避免 HMR WebSocket 重连触发整页刷新。

`backend/main.py` 在 `frontend/dist` 存在时直接挂载静态前端。Vue Router 的工作区、历史和博主深链回退到 `index.html`，缺失的静态资源仍返回 404。后台任务调度器和 API 运行在同一 FastAPI 进程中，因此生产环境使用单个 Uvicorn worker。

## 前端结构

- `frontend/src/App.vue`：认证、能力、路由和工作台状态编排。
- `frontend/src/router.js`：`/`、`/workspace`、`/history`、历史详情、`/bloggers` 和博主详情路由。
- `frontend/src/components/`：页面区域、Dialog、下载、视频和 AI 结果组件。
- `frontend/src/composables/`：认证、能力、学习工作区、下载、后台任务和管理员连接状态。

工作区先展示独立的字幕面板，再提供摘要、导图、笔记和精选问答四个可选模块。字幕加载后默认展开；手动收起只隐藏正文，复制和下载始终保留在外层。格式说明仅在悬停或键盘聚焦时显示，支持 Esc 关闭及视口边缘避让。字幕 TXT 下载不依赖时间轴；仅在每条字幕都有有效起止时间时提供 SRT/VTT。历史页和分 P 切换只读取快照，不自动触发生成。字幕操作和 AI 模块工具按钮共用 `toolbars.css` 的高度、圆角、颜色、边框及交互状态。摘要、导图、笔记和精选问答使用「页签 → 顶部工具栏 → 正文」布局；工具栏与页签随页面滚动保持可用，手机自动换行。已有资料在生成中仍可复制、导出，生成按钮遵循任务互斥；精选问答支持全部展开/收起。清空字幕后仍可阅读和导出已有问答。导图全屏内保留退出按钮。

工作台 URL 保存当前视频链接、标签页和分 P。刷新、前进后退或打开历史详情时，前端从路由查询参数恢复状态。History、管理员设置、视频播放器和 markmap 等较重功能按需加载。导图仅在标签页可见时渲染，页面离开后不再执行异步缩放。

博主列表使用真实分页，每页 10/20/50 条（默认 20）；顶部和底部均可翻页、跳转及调整每页数量，多选仅作用于本页。搜索或筛选变化回到第一页，每页数量变化尽量保留原先第一项所在位置，并按身份记住偏好；URL 的 `pageSize` 优先。翻页定位列表起点，浮动按钮可回到本页顶部。

进入工作区时，URL 的 `returnTo` 保存站内博主路径、搜索、整理/字幕筛选、`page`、`pageSize` 和视频锚点。桌面返回工具栏固定在导航栏下，手机固定在底部并留出安全区；AI 工具栏的固定偏移来自导航栏实际高度，后台任务浮层避让底部返回入口。

列表独立负责滚动恢复，路由不竞争滚动。sessionStorage 按身份、博主、筛选、每页数量保存原卡片视口偏移、相邻项和展开分 P；内存 LRU 最多保留 5 页快照，键额外包含页码。同页返回先绘制缓存和恢复位置，随后后台刷新标签，不等待博主元数据或批量任务请求，也不在刷新完成后再次拉动视口。刷新工作区或冷启动时，`GET /api/bloggers/{id}/videos` 通过 `anchor_id` + `locate_anchor=1` 一次定位并返回目标页，无需请求前面的页。接口保留 `offset`、`limit`、`anchor_index`，新增实际 `offset`、`limit` 返回值；目标在当前排序/筛选中的索引先解析为页对齐偏移，再取行。同步新增投稿后仍按锚点定位；越界页回到最后一页，旧锚点链接也适用。原视频离开筛选时保留筛选并提示，可一键查看原视频。

`core/content_state.py` 统一字幕和四种已保存模块的判定，任务失败不覆盖已有内容状态；空 JSON、空模块及简介摘要不计入已整理数。博主卡片、视频列表、分 P 和历史共用此口径，字幕筛选可以与整理筛选叠加。`POST /api/workspace/visit` 在读到共享缓存后幂等登记身份记录，不更新已有状态或收藏，不创建任务或消耗额度；GET 快照保持只读。字幕访问记录仅用于当前身份的列表标记；公开学习历史在查询、分 P 合并和分页之前过滤为至少有一种有效正文 AI 模块，字幕或简介摘要记录不展示。

`DELETE /api/workspace/subtitle` 清空当前身份的字幕关联：`user_history.subtitle_cleared` 持久化清空状态，并同步处理基础 URL 与 P1 别名；共享字幕缓存、已有 AI 资料、收藏和其他身份均保留。后台任务进行中禁止清空。工作台快照返回 `subtitle_cleared`，前端据此停止自动获取，显式点击获取字幕或提交整理任务后恢复关联。管理员的全局内容视图也优先应用当前身份的清空状态。

视频解析和播放地址刷新通过 Starlette 的受限线程池执行，包括同步短链解析、DNS、yt-dlp 与数据库读取，避免外部平台慢请求阻塞 API 事件循环。下载器统一使用 `DOWNLOAD_DIR`。

## AI 连接与文本客户端

`core/ai_config.py` 将管理员配置持久化为版本 3 的 `connections` 结构。每个连接保存 `api_format`、Base URL、可选模型发现地址、`primary_model_id` 和模型目录；模型的来源/发现状态与测试状态分别保存，避免刷新目录覆盖手动模型或历史测试结果。旧的单模型与服务商分组格式在读取时兼容归一化。

运行时连接优先于 `.env` 兜底。首个可用连接会自动成为全局 active；编辑非当前连接只修改其连接级主力模型；显式切换会在一次持久化操作中同时更新连接主力模型和全局 active。管理员 API 只返回脱敏后的 API Key，删除当前连接时会回退到另一个连接的主力模型或 `.env` 兜底。

`core/text_client.py` 为 OpenAI 与 Anthropic 兼容接口提供统一的生成、流式输出、模型发现和连通性测试。模型发现会按协议尝试兼容端点，并为 Anthropic 路径的中转站回退到 OpenAI 风格的 `/models` 端点；既有 AI 流水线通过一个 Anthropic 形状的兼容层继续调用该客户端。

## 身份与会话

登录和注册会创建不透明的 `session_id`。前端将它保存在 `sessionStorage`，使登录状态在刷新后保留，同时隔离不同浏览器窗口。

普通 HTTP 请求只从 `Authorization: Bearer <session_id>` 读取登录凭据。Cookie 和普通 HTTP 查询参数不参与认证，`/api/auth/me` 也不会回传凭据。视频流和下载 WebSocket 因浏览器原生元素不能设置自定义请求头，目前允许显式 `session_id` 查询参数。

访客设备 ID 与签名保存在 `localStorage`，只有配置了非默认 `GUEST_SECRET` 时才开放访客能力。普通 HTTP 使用 `X-Guest-Id` / `X-Guest-Sig`，视频流和 WebSocket 可使用对应查询参数。显式 Bearer 或 query Session 一旦出现就必须独立验证成功；格式错误、过期或不存在时直接拒绝，不能降级到另一组 Session 或访客身份。

迁移 `20260713_invalidate_legacy_auth_sessions` 在一个 `BEGIN IMMEDIATE` 事务中删除旧 Session 并写入版本标记，只执行一次。该迁移首次执行后，旧登录会话失效，用户需重新登录。

## 媒体代理安全

缩略图和视频代理共用统一媒体安全层：底层只接受 HTTPS，并按完整域名标签匹配已知平台 CDN。缩略图入口会先用结构化 URL 解析把平台返回的旧 HTTP 地址升级为 HTTPS，再进入同一安全层；视频代理仍直接拒绝 HTTP。每次重定向都会重新解析并校验公网 IP，最多跟随 3 跳；连接固定到已校验 IP，同时保留原域名用于 TLS SNI 和证书验证。

缩略图只接受 JPEG、PNG、WebP、GIF 和 AVIF，响应上限 10 MiB；HTML、SVG、未知 MIME 和超限内容会被拒绝。视频只接受 `video/*`、`audio/*` 和 `application/octet-stream`。代理响应带 `X-Content-Type-Options: nosniff` 和隔离 CSP，服务不启用通配 CORS。未知平台仍可解析和下载，但不提供代理缩略图或在线播放。

## 字幕管线

独立字幕任务和学习资料任务共用字幕获取管线，顺序为：

1. SQLite 已缓存字幕。
2. B 站 CC 或其他平台原生字幕。
3. yt-dlp 可用字幕。
4. 用户确认后的 Whisper 本地转录。

后台调度提供两个独立单槽：仅获取平台字幕的 `learning` 任务使用字幕通道；AI 整理、批量任务和已确认的 Whisper 使用长任务通道。不同 URL 可并行，同一 URL hash 的任务跨通道互斥；被同视频阻塞的队列项不阻止其他视频执行。确认转录后任务回到长任务通道。两个调度器各自持有 worker 状态，启动只恢复一次中断任务。

任务完成提交初始化后才允许领取；初始化被重启打断的任务标记失败并释放预留额度。任务入队、状态提交和字幕事件落库后通过线程安全的本地订阅立即唤醒调度器或 SSE；每秒检查保留为其他进程写入及通知遗漏的兜底。SSE 仍使用持久事件游标重放并校验身份，读取终态前保证最后一批事件可交付。

B 站 CC 查询使用三态语义：

- `available`：已取得可用字幕。
- `absent`：B 站主、备字幕目录均返回有效的空结果，且未要求登录。工作台随后可按需探测 yt-dlp 提供的字幕轨道。
- `unavailable`：限流、网络、登录要求或无效响应导致无法可靠判断。

工作台在缺少平台字幕或字幕接口暂时失败时，可以请求 Whisper 确认。遇到 B 站访问保护且没有有效音频直链时，直接显示错误和重试提示。转录在用户确认后才开始，并继续遵守访问保护。无法获取正文时，简介足够长的视频可由用户明确选择生成独立简介摘要。多分 P 查询使用所选分 P 的精确 `cid`。

短链解析完成后，缓存、字幕和学习状态统一使用 yt-dlp 返回的规范 `webpage_url`，并保留原始 `p` 参数。基础多分 P URL 可展示全集总时长；明确选择分 P 后，Whisper 时长上限、ETA 和进度使用该分 P 自身时长。

## SQLite、缓存与学习状态

SQLite 保存用户、会话、视频、字幕、AI 输出、学习历史、缓存和 `background_jobs`。连接启用 WAL、`busy_timeout` 和外键。

主要缓存：

- `video_info_cache`：按精确 URL 哈希保存视频与分 P 元数据。
- `ai_cache`：按精确 URL 哈希保存已成功的各学习模块及其独立来源和版本元数据。
- `learning_events`：保存后台任务事件，供刷新和 SSE 游标续读。
- `learning_usage`：按任务保留一次额度预留/成功扣费记录，支持任务恢复时防重复扣费。
- `whisper_cache`：按精确 URL 哈希保存本地转录结果。

同一 B 站视频的分组指纹只用于保留策略和非分 P 旧链接兼容，不是缓存唯一身份。读取缓存不会批量改写 URL、哈希或用户历史，删除一个分 P 也不会删除相邻分 P。

`AI_CACHE_KEEP` 是 AI 缓存的软上限。任何身份的学习历史引用或收藏标记都会保护对应 AI 成果；受保护资料可超过上限。仅淘汰未受保护的旧 AI 缓存，不级联删除字幕、视频、标签或任务事件。成功生成先在同一事务写入历史，再执行淘汰。聊天及纯文本问答结束时按操作 ID 释放预占额度，启动时回收没有可恢复任务的残留预占。

“有字幕”表示缓存中有可读原文；“已整理 · n/4”只统计摘要、导图、笔记和问答的有效内容；“简介摘要”独立标记，不计入视频全文整理。状态由当前身份的历史和该 URL 的实际内容派生，不以任务成功与否作为覆盖依据，也不写入共享视频元数据。普通身份只看自己的记录，管理员沿用跨身份查看已保存内容的权限。每个模块单独记录字幕修订、提示词版本和模型；旧版本仍可阅读，字幕或提示词变化只让相关模块标记为过期。

每个模块独立生成并事务性合并到已有缓存，因此部分失败会保留本次成功模块和之前的成果。读取缓存、字幕获取与 Whisper 转录不收费；生成操作只预留一次额度，在首个新模块成功写入同一事务时扣费，同一操作的后续模块、断线重试和恢复不会重复扣费。用户显式新建的生成或强制重新生成操作在保存新成果时单独计费。空结果、异常或 SQL 失败不会替换该模块旧内容。简介摘要单独保存并注明 `description` 来源，不伪装成基于字幕的结果。

## 博主与批量生成

博主功能拆分「共享目录」与「按身份订阅」：`blogger_creators`/`blogger_videos`/`blogger_video_pages` 全局共享（同一 UP 主只同步一次），`blogger_subs`/`blogger_batches`/`blogger_batch_items` 按 `user_id`/`guest_id` 归属，互不可见。退订只删订阅行，最后一个订阅者离开且无活跃任务时才清理共享目录。

目录同步（`core/blogger/sync.py`）运行在独立线程池，不进重任务队列。所有 B 站入口共享 `core/bilibili_guard.py` 的持久化限速与额度，API 默认至少间隔 5 秒，每分钟 30 次、每小时 120 次、每日 600 次；工作台单次字幕操作最多 5 次 API 请求可按 0.25 秒间隔发出，但仍计入共享额度。每次同步最多 20 页并保留断点。403/412/风控代码仅暂停对应功能 10/20/40/最多60分钟，429短时暂停所有功能，不自动重试或切换接口；`login` / `budget` / `protection` 也暂停。首次分页前的 `network` 错误最多退避 30s/120s，已有进度则暂停。仅列表/字幕等必要API默认使用登录 Cookie，网页和 CDN 默认匿名；重复元数据短期缓存。保留同页签名防死循环、空目录一致性检查，并跳过课堂推广条目。详见 [B 站访问保护](bilibili-access.md)。

批量条目是 `job_type="batch_item"` 的后台任务，每条目一 job：复用 `job_store` 的长任务单槽、取消与崩溃恢复；`JobScheduler` 按 `job_type` 分发到进程内处理器 `core/blogger/batch_runner.py`——缓存命中直接复用，bvid+cid 已知时跳过 yt-dlp 解析快取 CC 字幕，无字幕才跑 Whisper 子进程（处理器内禁止再 create_job，单槽会死锁），AI 生成走 `background_pipeline.generate_full_from_subtitle`（与 Whisper 后完成共用），`generate-then-swap` 原子提交。AI 前有额度闸门，超限条目跳过并暂停整批。批量成果写入所属身份的学习历史后，同样受到缓存淘汰保护。

## 后台任务

`GET /api/workspace?url=...` 返回只读快照。`POST /api/subtitle/prepare` 创建独立字幕任务。`POST /api/learning/generate` 接受 `summary`、`mindmap`、`notes`、`qa` 的所选组合。`GET /api/tasks/{id}/events?after=...` 以持久事件 ID 续读 SSE。取不到平台字幕且满足转录条件时，任务进入 `awaiting_confirmation`。确认接口恢复原任务并继续转录与生成。离开页面后后台工作继续执行。

任务状态流：

```text
queued -> downloading -> transcribing -> generating -> done
            |                                  `-> partial / failed / cancelled
            `-> awaiting_confirmation -> queued（用户确认后恢复）
```

- `core/job_store.py`：任务持久化、原子领取、查询与取消。
- `core/job_scheduler.py`：一次运行一个后台任务；`whisper` 走子进程，其他 `job_type` 由进程内 handler 执行。
- `workers/whisper_worker.py`：通过 JSON Lines 报告进度和结果。
- `core/background_pipeline.py`：生成后台结果，成功后交给原子提交层保存。
- `core/generation_commit.py`：验证生成结果并原子替换缓存、字幕、历史和用量。

学习任务会在每个模块保存后持久化检查点；服务重启后跳过已保存模块并继续未完成的模块。事件记录按保留期清理；取消会终止当前子进程并清理临时结果。模块业务失败进入可单独重试的终态，不无限重试。

视频解析结果会分别保留播放流和最佳音频流。工作台确认转录时保留视频信息，并跳过已完成的平台字幕查询。有效音频直链通过 `--audio-url` 传给 worker。直链缺失时，或直链下载普通失败且访问保护允许时，worker 尝试原视频 URL。

## 启动与能力降级

FastAPI lifespan 依次完成：

1. 创建运行目录并初始化 SQLite 表。
2. 创建可选管理员并清理过期 Session，恢复悬挂的博主目录同步并调和批量批次。
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
| Whisper 模型 | `backend/data/whisper_models/faster-whisper-small/` | `WHISPER_MODEL_PATH` 优先，否则由 `WHISPER_MODELS_DIR` 和 `WHISPER_MODEL` 拼接 |

数据库、密钥、模型、下载内容、旧向量索引和会话交接文件不得提交到 Git。

字幕身份校验集中于 `core/subtitle_identity.py` 与 `core/subtitle_validation.py`，字幕数据库保存来源证明；访问 JSON 与封面分别使用有界缓存和请求合并。工作台轻量解析、下载页按需取得格式。最新边界说明见 [B 站访问说明](bilibili-access.md)。

封面代理使用独立四线程下载队列与四个跨进程下载槽；准入锁仅覆盖额度检查，网络读取不会占用 API 或媒体的请求锁。缓存分为内存（1 小时，256 条/32 MiB）、SQLite 磁盘（7 天，图片内容 256 MiB）和浏览器（1 小时，ETag）。内存命中直接返回，磁盘命中无需远端额度。详细限制与回归记录见 [B 站访问说明](bilibili-access.md)。
