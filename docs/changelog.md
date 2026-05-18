# 变更记录

## [3.0.0] - 2026-05-18

### 新增

- **用户认证系统**（`backend/core/auth.py` + `backend/api/auth_routes.py` + `frontend/src/composables/useAuth.js`）：
  - 基于 Session Cookie（`vm_session`，HttpOnly，SameSite=Lax，7 天有效期）的认证机制
  - 注册/登录/退出/当前用户查询端点
  - 游客体系：HMAC-SHA256 签名的 device_id，无需注册即可使用基础功能
  - 权限矩阵：Guest（3次/天，无历史）→ User（20次/天，个人历史）→ Admin（无限制，全局）
  - 前端 `useAuth()` composable：全局单例状态管理，自动初始化游客身份

- **登录注册 UI**（`frontend/src/components/LoginModal.vue`）：
  - 深色主题弹窗，支持登录/注册切换
  - 用户名+密码表单，前端基础校验
  - 登录成功后自动刷新页面状态

- **用户隔离**（`backend/core/cache.py` + `backend/api/knowledge_routes.py`）：
  - `user_history` 表：按 user_id/guest_id 隔离学习历史
  - 标签按用户过滤：通过 `user_history → ai_cache → videos → video_tags → tags` JOIN 链实现
  - 统计数据按用户过滤：`get_learning_stats()` 和 `get_all_tags()` 支持 user_id/guest_id 参数
  - 管理员可查看全局数据

- **轻量级用量查询端点**（`backend/api/auth_routes.py`）：
  - `GET /api/auth/usage` — 只返回 `{used, limit, allowed}`，不返回用户信息
  - 前端 AI 调用后通过此端点刷新用量，减少网络开销

### 变更

- **auth.py 统一使用 get_db()**（`backend/core/auth.py`）：
  - 所有 DB 操作从手动 `sqlite3.connect()` 改为 `database.get_db()` 上下文管理器
  - 自动获得 WAL 模式、事务管理、异常 rollback
  - 删除死代码：`toggle_favorite(history_id)`、`get_user_history()`、`delete_user_history()`（API 路由使用 cache.py 版本）

- **移除 get_user_by_session 冗余写入**（`backend/core/auth.py`）：
  - 删除每次请求都更新 `last_login_at` 的逻辑，减少无效 DB 写入

- **check_usage_limit 优化**（`backend/core/auth.py`）：
  - admin 用户直接返回无限额度，避免额外查询
  - 消除 `get_user_by_id()` 与 `get_today_usage()` 的重复查询

- **get_today_usage 索引优化**（`backend/core/auth.py`）：
  - 从 `DATE(created_at) = ?` 改为 `created_at >= ?`（当天 00:00 UTC）
  - 可利用 `idx_usage_user_date` / `idx_usage_guest_date` 索引

- **前端 fetchMe 错误处理优化**（`frontend/src/composables/useAuth.js`）：
  - HTTP 非 200（如 401/403）时清除用户状态，不再从 localStorage 恢复过期数据
  - 仅网络故障（catch）时降级恢复 localStorage 缓存

### 修复

- **crypto.randomUUID() HTTP 兼容**（`frontend/src/composables/useAuth.js`）：
  - `crypto.randomUUID()` 在 HTTP 环境下不可用（需 HTTPS secure context）
  - 新增 `_generateId()` 函数，HTTP 时降级为 Math.random() UUID 生成

- **游客身份初始化竞态**（`frontend/src/composables/useAuth.js`）：
  - `ensureGuestId()` 从 fire-and-forget（`.then()`）改为 `async/await`
  - `init()` 等待 guestId 生成完毕后再调用 `fetchMe()`

- **字幕时间戳缓存覆盖**（`backend/api/stream_routes.py`）：
  - 缓存命中时原代码调用 `save_subtitle_to_db` 不带 segments，覆盖了已有时间戳数据
  - 修复：先检查 `get_subtitle_from_db()`，存在则只更新 title/platform

- **标签显示全局而非按用户**（`backend/core/cache.py`）：
  - `get_all_tags()` 原返回所有标签，改为按 user_history 过滤

- **统计数据重复计数**（`backend/core/cache.py`）：
  - `get_learning_stats()` 的 `total_videos` 原直接查 user_history，未关联 ai_cache
  - 孤立 user_history 记录（无对应 ai_cache）被计入，导致计数偏高
  - 修复：JOIN ai_cache 过滤有效记录

- **退出登录后停留在历史页**（`frontend/src/components/NavBar.vue`）：
  - 退出登录后 emit `go-home` 事件，自动返回首页

---

## [2.9.0] - 2026-05-17

### 新增

- **视频在线播放**（`frontend/src/components/VideoPlayerModal.vue` + `backend/api/routes.py`）：
  - 解析视频时自动提取最佳视频流 URL（`stream_url`），30 分钟过期
  - 封面图点击打开全屏播放弹窗（HTML5 原生 `<video>`，`controls autoplay`）
  - Bilibili DASH 视频降级支持：无合并流时使用纯视频流（无声音但可预览画面）
  - 播放链接过期时自动调用 `/api/video/refresh` 轻量级刷新
  - ESC 键 / 遮罩点击关闭弹窗
  - 流式代理 `/api/video/stream`：解决 Bilibili CDN 的 Referer 403 限制，支持 Range 请求（视频 seek）

- **字幕时间点跳转 + 高亮同步**（`frontend/src/components/AiSummary.vue` + `backend/core/summarizer.py` + `backend/api/subtitle_text_routes.py`）：
  - 字幕 segments（含精确 start/end 时间）从后端传递到前端，覆盖所有字幕来源（Bilibili CC / yt-dlp SRT/VTT/JSON3）
  - 字幕时间戳蓝色可点击，点击跳转视频对应位置
  - 当前播放字幕自动高亮（蓝色背景）+ 自动滚动到可见区域
  - 新增 `extract_subtitle_segments()` 函数：从 SRT/VTT/JSON3 原始内容解析 `{start, end, text}` segments
  - segments 持久化到 `subtitles` 表的 `segments_json` 列，DB 缓存命中时一并返回

- **AI 笔记时间点跳转**（`backend/core/ai_client.py` + `backend/api/stream_routes.py` + `backend/prompts/notes/v1.txt` + `frontend/src/components/AiSummary.vue`）：
  - 笔记 section 标题自动注入 `[MM:SS]` 时间戳（后端确定性注入，不依赖 LLM 生成）
  - 匹配策略：LCS（标题）+ bigram（正文），双重匹配取最佳对应字幕段落
  - 前端 `renderNotesMarkdown()` 将 `[MM:SS]` 替换为 Notion 风格的可点击内联标签
  - 事件委托处理点击，跳转视频到对应时间点
  - Prompt 追加第 8 条要求：关键知识点附带 `[MM:SS]` 时间点

- **章节标题跳转**（`frontend/src/App.vue`）：
  - 视频章节（`videoInfo.chapters`）区域可点击，跳转视频到章节起始时间
  - 需视频作者手动添加章节，无章节的视频不显示该区域

### 变更

- **VideoInfo 模型扩展**（`backend/core/models.py`）：新增 `stream_url`（视频流直链）和 `stream_expires_at`（过期时间戳）字段
- **parse_info 提取 stream_url**（`backend/core/downloader.py`）：从 yt-dlp formats 中提取最佳视频流 URL，合并流优先，DASH 降级到纯视频流
- **database.py segments 支持**：`save_subtitle_to_db()` 和 `get_subtitle_from_db()` 支持 `segments_json` 字段的读写

---

## [2.8.0] - 2026-05-17

### 新增

- **学习历史页独立组件**（`frontend/src/components/HistoryPage.vue`）：
  - 从 App.vue（2607 行）提取学习历史页为独立组件，App.vue 缩减至 ~1900 行（-28%）
  - 组件自行管理所有状态（搜索、标签、排序、分页、收藏、删除）
  - 通过 `emit('select-item', item)` 与 App.vue 通信，用户点击历史卡片后跳转首页并自动触发 AI 总结
  - 包含完整 scoped CSS + 移动端 768px 响应式适配

- **智能标签提取**（`backend/core/tag_extractor.py`）：
  - 基于规则匹配的轻量级标签提取器，从标题和摘要中提取 3-5 个标签
  - 100+ 关键词→标签映射：编程语言、AI/ML、前后端、数据库、算法、框架工具、内容类型
  - 平台识别：从 URL 或 yt-dlp extractor 名自动识别 bilibili/youtube/douyin/tiktok/xiaohongshu
  - AI 总结完成后自动提取标签并持久化到 `video_tags` 关联表

- **学习统计仪表盘**（HistoryPage 顶部）：
  - 显示学习视频数、笔记字数、平均时长、覆盖平台数
  - 后端 `GET /api/history/stats` 端点提供统计数据

- **标签过滤与平台过滤**（HistoryPage 搜索栏）：
  - 标签过滤栏显示使用频率最高的 20 个标签，点击筛选
  - 平台下拉筛选：B站/YouTube/抖音/TikTok/小红书
  - 排序切换：最新/最早

- **语义搜索**（HistoryPage AI 搜索模式）：
  - 切换到 AI 模式后可输入自然语言问题（如"哪个视频讲过IK分词器"）
  - 基于 ChromaDB 向量数据库的跨视频语义搜索
  - 后端 `GET /api/search` 端点返回匹配片段 + 来源视频

### 修复

- **Bilibili 字幕下载无换行**（`backend/core/summarizer.py`）：
  - `extract_bilibili_subtitle_by_cid()` 的 `full_text` 原用 `' '.join()` 拼接所有字幕段，导致前端收到的字幕文本为一整行
  - 改为 `'\n'.join()`，每段字幕独立一行，SRT/VTT/TXT 下载格式正确换行

- **多P视频 P0 显示为 P？**（HistoryPage）：
  - `part.part_index || '?'` 中 `0` 为 falsy 值导致 P0 显示为 `P?`
  - 改为 `part.part_index ?? '?'`（nullish coalescing）

- **多P视频展开/关闭文案**（HistoryPage）：
  - 展开后仍显示"点击展开"，改为根据 `expandedGroups` 状态显示"点击关闭"/"点击展开"

- **多P视频 P0 标题显示**（HistoryPage）：
  - P0 的 `part_info` 为空时显示 AI 摘要预览，改为显示"总览"

- **垃圾标签**（`backend/core/tag_extractor.py`）：
  - 原中文词提取正则 `[一-鿿]{2,4}` 盲目切分标题，产生"会被中国"、"车厂吓到"等无意义标签
  - 移除该降级逻辑，关键词匹配无结果时返回空列表

- **删除后标签残留**（`backend/core/cache.py`）：
  - `delete_cache()` 原只删除 `ai_cache` 记录，未清理 `video_tags` 和孤立 `tags`
  - 新增级联删除：先删 `video_tags`，再清理无引用的 `tags`

- **N+1 标签查询**（`backend/core/cache.py`）：
  - `list_history_enhanced()` 原对每条记录单独查询标签（N 次 SQL）
  - 新增 `get_tags_for_urls(urls)` 批量查询函数，一次 SQL 获取所有 URL 的标签

- **空 catch 块**（HistoryPage）：
  - `fetchHistoryPage`、`loadMoreHistory`、`handleSemanticSearch` 的 catch 块原为空，用户操作失败无反馈
  - 改为 `alert()` 提示具体错误信息

- **时长格式**（HistoryPage）：
  - 超过 1 小时的视频原显示 `m:ss`（如 `106:28`），改为 `Xh Ym` 格式

- **删除确认标题截断**（HistoryPage）：
  - `confirm` 弹窗原用 `.slice(0, 30)` 截断标题，长标题显示不完整
  - 移除截断，显示完整标题

- **P4 提取误删 `formatTime`**（`frontend/src/App.vue`）：
  - 提取 HistoryPage 时 `formatTime` 函数被一并移除，但下载历史区域仍在使用
  - 恢复 `formatTime` 函数

### 优化

- **数据库索引**（`backend/core/cache.py`）：
  - `ai_cache` 表新增 `idx_ai_cache_created_at` 索引，加速按时间排序的历史查询

- **错误处理增强**（HistoryPage）：
  - 所有 API 调用添加 try-catch + 用户友好的 alert 提示

---

## [2.7.0] - 2026-05-16

### 新增

- **多P视频 AI 总结**（`backend/api/stream_routes.py` + `backend/core/summarizer.py` + `frontend/src/App.vue` + `frontend/src/components/AiSummary.vue`）：
  - B站多P视频支持按分P独立 AI 总结，每P拥有独立字幕、缓存和总结结果
  - 新增 `extract_bilibili_subtitle_by_cid(bvid, cid, aid)` 函数，通过 B站 CC 字幕 API 按分P的 cid 获取字幕
  - `VideoPart` 模型新增 `cid` 字段，`_fetch_bilibili_parts()` 返回每P的 cid
  - 前端新增分P选择器（`parts-nav`）：水平滚动列表 + 左右箭头按钮，显示 P序号、标题、加载状态
  - `currentSummarizePart` 状态管理 + `summarizeUrl` 计算属性，自动保留 `?p=N` 参数
  - 所有 AI 操作（总结/重新生成摘要/导图/笔记/字幕）均使用 `summarizeUrl.value`，确保操作正确的分P
  - 多P URL 的缓存按 `?p=N` 隔离，跳过指纹匹配避免不同分P命中同一缓存
  - URL 中 `?p=N` 参数在 `canonical_url` 中正确保留

### 修复

- **B站 extractor 大小写匹配**（`backend/api/stream_routes.py`）：
  - `info.extractor` 为 `'BiliBili'`（大写B），原代码 `'bilibili' in extractor` 为 False，导致多P字幕提取被静默跳过
  - 修复为 `'bilibili' in (info.extractor or '').lower()`

- **分P选择器滚动修复**（`frontend/src/components/AiSummary.vue`）：
  - 原 `scrollbar-width: none` 隐藏了滚动条，用户无法发现可滚动内容
  - 改为 `scrollbar-width: thin` + 细滚动条样式
  - 新增左右箭头按钮，根据滚动位置自动显示/隐藏
  - 新增 `updateScrollState()` 和 `scrollParts()` 函数

### 优化

- **移动端响应式适配**（`frontend/src/components/HeroSection.vue` + `frontend/src/components/AiSummary.vue` + `frontend/src/App.vue`）：
  - HeroSection：768px 以下输入框+按钮改为垂直堆叠，按钮全宽，标题/副标题缩小
  - HeroSection：标题 `white-space: nowrap` + `text-overflow: ellipsis`，防止"VideoMind AI 视频学习助手"在窄屏断行成"手"独占一行
  - HeroSection：输入框 `font-size: 1rem`（16px），避免 iOS 自动缩放
  - AiSummary：子 Tab 按钮缩小（padding/font-size），横向滚动显示细滚动条
  - AiSummary：笔记/问答/摘要内容区使用 `vh` 单位，适配手机屏幕高度
  - AiSummary：分P选择器按钮在手机上缩小显示
  - App.vue：视频卡片 padding 缩小，视频标题/元数据字体缩小，格式网格单列，分P列表适配
  - 遵循 ui-ux-pro-max 规范：触控目标 ≥44px、输入框 ≥16px 防缩放、无水平溢出

---

## [2.5.0] - 2026-05-15

### 新增

- **Faster-Whisper 语音转录兜底**（`backend/core/whisper.py`）：
  - 无字幕视频通过 Whisper small 模型转录（CPU/int8 量化，本地加载不联网）
  - 四级字幕 pipeline：B站CC > yt-dlp 原生 > Whisper > OCR（预留）
  - 启动时检查模型文件完整性，缺失只记录日志不阻塞服务
  - Whisper 转录结果缓存到 `whisper_cache` 表，避免重复转录

- **AI 字幕校正 Pipeline**（`backend/core/ai_client.py` + `backend/prompts/subtitle_correction/v1.txt`）：
  - Whisper 转录后利用视频标题/简介作为上下文进行 AI 校正
  - 修正专有名词、同音错字、断句错误，保留时间戳不变
  - 低温输出（temperature=0.1）+ 30% 长度校验防止输出异常
  - 校正失败自动降级到原始文本，不阻塞流水线
  - 环境变量控制：`SUBTITLE_CORRECTION_ENABLED`、`SUBTITLE_CORRECTION_MAX_CHARS`

- **视频时长限制**（所有字幕/总结端点）：
  - `WHISPER_MAX_DURATION=120`（默认 2 分钟），超过则跳过 Whisper
  - 防止长视频在 CPU 上转录过久（13 分钟视频需 40-60 分钟）
  - 无字幕+超长+无简介 → 返回 400 明确提示
  - 无字幕+超长+有简介 → 自动降级到基于简介总结

- **视频信息缓存**（`backend/core/cache.py` + `video_info_cache` 表）：
  - `/api/parse` 结果缓存到 `video_info_cache` 表，同 URL 无需重复解析
  - `/api/summarize/stream` 先查缓存，超长视频直接拦截（跳过 yt-dlp 的 20s+ 解析）
  - 缓存存储完整 VideoInfo JSON，后续可扩展离线查询

### 修复

- **Markdown 渲染修复**（`backend/prompts/summary/v1.txt` + `notes/v1.txt`）：
  - 摘要和学习笔记 prompt 从 JSON 格式改为纯 Markdown 输出
  - 解决 JSON 中未转义换行导致 `json.loads()` 失败、前端显示原始 JSON 的问题

- **笔记复制按钮修复**（`frontend/src/components/AiSummary.vue`）：
  - 新增 `fallbackCopy()` 函数（textarea + `execCommand('copy')`）
  - 解决 `navigator.clipboard.writeText()` 静默失败导致复制无反应

- **字幕文本返回修正**（`backend/api/subtitle_text_routes.py`）：
  - Whisper 校正后的文本正确返回给前端（之前返回了原始转录文本）

### 变更

- **Whisper 缓存表扩展**：`whisper_cache` 新增 `raw_text` 列，分别存储校正后文本和原始转录

---

## [2.6.0] - 2026-05-16

### 新增

- **Chunk Summary 首片优先优化**（`backend/core/ai_client.py` + `backend/api/stream_routes.py`）：
  - 新增 `stream_chunk_summaries()` 生成器，替代阻塞式 `_chunk_summarize()`
  - 长视频（字幕 >60000 字符）分两阶段流式输出：
    - **初步摘要**：首片完成（~15s）即开始流式输出，前端显示"基于视频前段内容"横幅
    - **完整摘要**：全部片完成后再输出全面摘要，覆盖初步摘要
  - 首片使用详细提示词（200-300 字+核心概念），后续片精简（100-150 字），优化等待体验
  - 思维导图和笔记复用合并后的摘要文本，避免重复分片（总计 N+4 次 API 调用 vs 旧版 3N+3 次）
  - 短视频（单一片）走原路径不变

### 修复

- **Tab 布局修复**（`frontend/src/App.vue`）：AI 总结/视频下载两个 tab 按钮改为 `flex: 1` 均分宽度
- **进度条可见性修复**（`frontend/src/components/AiSummary.vue`）：AI 分析步骤条移至子 tab 栏上方，无论切换到哪个子 tab 都可见
- **字幕文本粘连修复**（`backend/api/subtitle_text_routes.py` + `backend/core/summarizer.py`）：
  - B站字幕 DB 缓存改为保存 `\n` 分隔文本，而非空格连接的 `full_text`
  - `_clean_json_subtitle` 改为 `\n` 连接片段（原为空格连接）

---

## [2.4.0] - 2026-05-15

### 新增

- **Prompt 版本化系统**（`backend/prompts/`）：
  - Prompt 从代码中分离为独立文件 `prompts/{name}/v{N}.txt`
  - 通过 `config.py` 中的 `PROMPT_VERSION` 环境变量控制版本
  - 首批 4 个 prompt：`summary`、`notes`、`mindmap`、`flashcard`
  - `_load_prompt(name)` 自动加载对应版本的 prompt 模板

- **SQLite 持久化缓存**（`backend/core/cache.py`）：
  - 新建 `ai_cache` 表，以 URL SHA256 为主键
  - `get_cached(url)` / `save_cache(...)` / `list_history(limit)` / `delete_cache(url)`
  - 命中缓存后直接通过 SSE 重放结果，不消耗 AI token
  - 缓存完整存储 result + mindmap_markdown + notes，支持后续知识查询

- **Chunk Summary Pipeline**（`backend/core/ai_client.py`）：
  - 长视频字幕超过 60000 字符自动分片
  - `_chunk_summarize()`: 逐片生成摘要 → 合并为全局摘要文本
  - 非流式和流式 API 统一使用分片 pipeline

- **标准化字幕获取 Pipeline**（`backend/api/stream_routes.py`）：
  - `_get_subtitle_text()` 三级降级：平台 API（B站 CC）→ yt-dlp 原生字幕 → Whisper fallback（预留）
  - 异步上下文中执行，避免阻塞事件循环

### 变更

- **AI Provider 抽象**（`backend/config.py` + `backend/core/ai_client.py`）：
  - 新增 `AI_PROVIDER` 环境变量（deepseek | openai | openrouter）
  - `AI_BASE_URL` 和 `AI_MODEL` 支持独立配置
  - 底层仍使用 Anthropic SDK（通过兼容端点）

- **AI 输出结构化 JSON**（`backend/core/ai_client.py`）：
  - 所有 prompt 要求 AI 返回结构化 JSON（非纯 Markdown）
  - `_parse_json_response()` 提取 JSON，支持 ` ```json ``` ` 代码块和裸 JSON
  - 解析失败时降级为原始文本

- **`summarizer.py` 瘦身**（`backend/core/summarizer.py`）：
  - 移除与 `ai_client.py` 重复的 AI 调用代码（`_get_client`、`_split_text`、`_extract_text`、prompt 构建等）
  - 保留字幕清洗函数和 B 站 CC 字幕提取
  - 添加兼容别名：`summarize_subtitle`、`generate_mindmap_markdown`

- **SSE 流式端点重构**（`backend/api/stream_routes.py`）：
  - 缓存优先：先查 `get_cached()`，命中则 SSE 重放
  - 字幕获取在 async 上下文中执行
  - 更细粒度的进度阶段：`cache_hit` / `subtitle_loaded` / `summary_generating` / `mindmap_generating` / `notes_generating`
  - 流水线完成后持久化到 SQLite

### 技术细节

- Prompt 模板使用 Python `.format()` 注入变量（`{video_title}`、`{subtitle_text}`、`{content_summary}`）
- Chunk pipeline 每个分片独立调用 AI，最后合并结果
- 缓存表包含完整 AI 结果 JSON，未来可用于知识库检索
- `config.py` 中 `DB_PATH`、`CHROMA_PATH`、`TEMP_DIR`、`DOWNLOAD_DIR` 确保目录自动创建

---

## [2.3.1] - 2026-05-14

### 新增

- **学习笔记流式输出**（`backend/core/ai_client.py` + `backend/api/stream_routes.py` + `frontend/src/composables/useSummary.js`）：
  - 新增 `stream_generate_notes()` 函数，使用 `client.messages.stream()` 流式生成笔记
  - SSE 新增 `notes_text` 事件类型，逐 token 推送笔记内容
  - 笔记标签页实时增量渲染，工具栏显示"生成中..."流式标记

### 优化

- **前端 UI 优化**（`frontend/src/components/AiSummary.vue` + `frontend/src/App.vue`）：
  - 进度指示器移至摘要内容上方，用户第一时间看到 AI 进度
  - 移除字幕标签页骨架屏加载闪烁
  - 标签页新增 SVG 图标，名称优化为：AI 摘要 / 字幕原文 / 思维导图 / 学习笔记 / AI 问答
  - AI 问答标签在无字幕时自动禁用
  - 主标签栏"下载"改为"视频下载"，与"AI 总结"对仗
  - 下载按钮内嵌至格式详情栏，消除突兀感

- **全局样式统一**（`frontend/src/style.css`）：
  - 所有 `<select>` 下拉框统一深色主题（半透明背景 + 自定义箭头 + 深色 option）
  - 全局滚动条深色样式

---

## [2.3.0] - 2026-05-14

### 新增

- **结构化学习笔记**（`api/stream_routes.py` + `frontend/src/components/AiSummary.vue`）：
  - AI 流水线新增 `notes` 阶段，生成标题层级分明的 Markdown 学习笔记
  - 前端 `AiSummary.vue` 新增"学习笔记"标签页（位于思维导图与问答之间）
  - 笔记面板支持一键复制和 Markdown 文件下载
  - SSE 新增 `notes` 事件类型，推送笔记 Markdown 内容

- **渐进式生成 UI**（`frontend/src/components/AiSummary.vue`）：
  - 新增三阶段进度指示器：字幕加载 → AI 总结 → 笔记生成 → 思维导图
  - 每阶段独立显示完成/进行中状态，用户可实时了解 AI 处理进度
  - SSE `progress` 事件驱动阶段状态更新

### 变更

- **产品定位转型**：从"视频下载工具"升级为"AI 视频学习助手"
  - 品牌名：SaveAny → **VideoMind**
  - 项目定位：免费在线视频下载器 → AI 视频学习助手
  - 目标平台：聚焦 5 个核心平台（B站、YouTube、抖音、小红书、TikTok）

- **前端 UI 重构（增量式）**：
  - `HeroSection.vue`：标题/副标题/按钮文案全面更新，平台标签精简为 5 个
  - `NavBar.vue`：Logo 文字更新为 VideoMind
  - `FeaturesSection.vue`：6 张特性卡片全部围绕 AI 学习场景重写
  - `FooterSection.vue`：平台列表精简，品牌/文案更新
  - `App.vue`：默认标签页改为 AI 总结，下载功能弱化为折叠区域+次要按钮

- **下载功能弱化**：
  - 下载标签页从第一位移至第二位
  - 下载区域改为可折叠（默认收起）
  - 下载按钮缩小，不再占据视觉焦点

### 文档更新

- `README.md`：全面重写，突出 AI 学习定位，更新架构图和 API 端点
- `docs/requirements.md`：重写需求分析，V2.0 AI 功能补充完整
- `docs/architecture.md`：更新产品名称和平台描述
- `docs/development.md`：更新项目名称为 VideoMind
- `docs/FRONTEND_REDESIGN.md`：更新品牌名、定位和平台描述
- 所有文档中的 "SaveAny" / "万能下载器" / "1800+ 平台" 替换为 VideoMind / AI 视频学习助手 / 5 平台

---

## [2.2.1] - 2026-05-12

### 修复

- **AI 摘要 Markdown 列表缩进修复**（`frontend/src/components/AiSummary.vue`）：
  - 为摘要区和问答区补充显式 `ul` / `ol` / `li` 样式，避免仅依赖 `prose` 默认样式
  - 修复列表项全部贴左显示的问题，保证多级列表在深色主题下仍有稳定缩进和间距

- **思维导图节点视觉修复**（`frontend/src/components/AiSummary.vue`）：
  - 去掉节点文字后的半透明深色底块，改为透明背景 + 描边 / 阴影增强对比度
  - 解决节点密集时背景块相互叠压，导致部分节点“忽明忽暗”的问题

- **思维导图 SVG / PNG 导出修复**（`frontend/src/components/AiSummary.vue`）：
  - 导出改为基于 `mindmapMarkdown` 离屏重新渲染，不再直接复用当前展示区的缩放和平移状态
  - 在导出阶段仍挂载到 DOM 中测量真实内容边界，避免 `viewBox` 计算错误导致导出图被裁切或只剩背景
  - 导出前将 `foreignObject` 文本节点转换为纯 SVG `text`，提升本地 SVG 打开兼容性，并降低 PNG 转 Canvas 时的兼容风险
  - SVG 导出增加深色背景与响应式根尺寸，直接在浏览器打开本地文件时不再出现明显白边
  - PNG 导出固定长边按 4K 目标生成，避免因页面当前缩放不同而出现尺寸失真或模糊

### 技术细节

- 新增离屏导出阶段：`createExportStage()` / `cleanupExportStage()`
- 内容边界测量统一走 `getContentBBox()`，必须在导图实际挂载到文档时调用
- 导出 SVG 统一通过 `buildExportableSvg()` 将交互态 SVG 转换为更稳定的静态产物
- 后续若修改 markmap 节点 DOM 结构、字体大小或主题样式，必须同步验证 `foreignObject -> text` 转换结果与导出边界计算

---

## [2.2.0] - 2026-05-12

### 修复

- **SSE 实时流式输出修复**（`api/stream_routes.py`）：
  - `_sse_generator` 原先使用 `lambda: list(_run())` 缓冲全部 AI 输出后才发送，导致前端等待 30-60s 无任何反馈
  - 改为 `asyncio.Queue` + `loop.call_soon_threadsafe`，AI 每生成一个 token 即推送至客户端
  - 新增 `progress` 事件，通知前端字幕加载完成、AI 总结开始生成

### 新增

- **B 站 CC 字幕提取**（`core/summarizer.py` `extract_bilibili_subtitle()`）：
  - 通过 `api.bilibili.com/x/v2/dm/view?type=1` 获取 CC 字幕列表（人工字幕优先于自动字幕）
  - 下载字幕 JSON 后解析分段，生成带时间戳的格式化文本和纯文本
  - 返回 `has_subtitle`、`language`、`subtitle_type`、`segments`、`full_text`、`text` 字段
  - `stream_routes.py`、`subtitle_text_routes.py`、`summary_routes.py` 的 AI 总结和字幕文本提取均优先使用此 API

- **字幕文本提取端点**（`api/subtitle_text_routes.py`）：
  - `GET /api/subtitle/text?url=...&lang=...` 返回清洗后的字幕纯文本
  - 优先 Bilibili CC 字幕 API，降级到 yt-dlp 字幕下载
  - 弹幕 XML 用专用解析器（`_clean_danmaku_xml`），其他格式走通用清洗

- **AI 问答功能**（`api/stream_routes.py` + `frontend/src/composables/useChat.js`）：
  - `POST /api/chat/stream` SSE 流式端点，基于字幕内容回答用户问题
  - 支持多轮对话历史（`history` 参数），最多保留最近 10 条
  - 前端 `AiSummary.vue` 新增聊天区域，问答结果支持 Markdown 渲染

### 优化

- **AI prompt 增强**（`core/summarizer.py`）：
  - summary 字段明确要求 Markdown 格式输出（`##` 标题、`**加粗**`、`-` 列表）
  - 思维导图层级从 3 层提升至 3-4 层，每分支最多 6 个子节点
  - 强调提取具体概念/技术/工具名称作为节点，避免"要点1"等无信息量标题
  - `summarize_from_description()` 同步应用 enhanced prompt

- **Markdown 渲染**（`frontend/src/components/AiSummary.vue`）：
  - 引入 `marked` + `dompurify`，AI 输出的摘要、流式文本、聊天消息均渲染为 HTML
  - 添加 `:deep()` CSS 样式覆盖（h1-h4、ul、ol、code、blockquote、strong、a）
  - `streamingText`、`result.summary`、`chat content` 三处改为 `v-html="renderMarkdown(...)"`

- **字幕与弹幕区分**（`core/downloader.py` + `frontend/src/components/AiSummary.vue`）：
  - `parse_info()` 过滤 `lang == 'danmaku'` 的字幕轨道，不展示在字幕列表
  - 前端字幕空状态改为"该视频无可用的字幕文本"，提示弹幕不等于字幕

### 新增依赖

- `frontend/package.json`：`marked`、`dompurify`（Markdown 渲染 + XSS 防护）、`markmap-lib`、`markmap-view`（思维导图渲染）、`@tailwindcss/typography`（Markdown 排版）

### 技术细节

- `_sse_generator` 跨线程流式实现：sync generator 在 thread executor 中运行，每 yield 一个事件就通过 `call_soon_threadsafe` 推入 `asyncio.Queue`；async generator 从队列中取出并立即 yield SSE 字节
- `extract_bilibili_subtitle()` 强制 HTTPS，解决字幕 URL 可能为 `//` 或 `http://` 开头的问题
- 弹幕 XML 解析回退到通用清洗方案（`_clean_plain_text`），而非直接失败
- AI 问答问答截取字幕后 80000 字符，保留足够上下文

---

## [2.1.0] - 2026-05-12

### 修复

- **ThinkingBlock 兼容性**（`core/summarizer.py`）：
  - DeepSeek 思考模型（如 `deepseek-v4-pro`）返回的响应中第一个 block 是 `ThinkingBlock`，无 `.text` 属性，直接访问会抛 `AttributeError`
  - 新增 `_extract_text(response)` 函数，遍历 `response.content`，跳过无 `.text` 属性的 block，返回第一个文本 block 的内容
  - 同时兼容思考模型（`ThinkingBlock` + `TextBlock`）和非思考模型（仅 `TextBlock`）

- **bilibili.com URL 规范化**（`api/routes.py`）：
  - 手机分享链接解析后可能得到 `bilibili.com`（无 www），yt-dlp 访问该域名返回 HTTP 403
  - 在 `_resolve_short_url()` 中新增正则检测，自动将 `bilibili.com/` 替换为 `www.bilibili.com/`

- **思维导图 CJK 文字溢出**（`frontend/src/components/AiSummary.vue`）：
  - 原 `measureText()` 用 `text.length * fontSize * 0.65 + 24` 估算宽度，对中文字符严重低估
  - 改为逐字符计算：CJK 字符（Unicode 范围检测）宽度 = `fontSize * 1.0`，ASCII 字符宽度 = `fontSize * 0.7`，padding 从 28 增至 32
  - `nodeGapX` 从 180 增至 220，节点间距更宽松

### 优化

- **AI 总结提速**（`backend/.env`、`core/summarizer.py`）：
  - 默认模型从 `deepseek-v4-pro`（思考模型，耗时 60s+）切换为 `deepseek-v4-flash`（非思考模型，约 11s）
  - 通过环境变量 `DEEPSEEK_MODEL` 可随时切换回思考模型

### 新增

- **无字幕视频 AI 总结降级方案**（`core/summarizer.py`、`api/summary_routes.py`）：
  - Bilibili 等平台无法通过 yt-dlp 获取自动生成字幕
  - 新增 `summarize_from_description(title, description)` 函数，基于视频标题和简介生成基础总结
  - 两种触发条件：① `info.subtitles` 为空；② 字幕内容 < 50 字符（如弹幕 XML 格式）
  - 前端展示时在总结顶部显示 `⚠️` 警告，说明总结基于简介而非字幕

### 技术细节

- `core/summarizer.py` 新增 `summarize_from_description()` 函数，`_call_deepseek()` 和多分片路径均改用 `_extract_text()` 提取文本
- `api/summary_routes.py` 新增 `from core.summarizer import summarize_from_description` 导入，路由中加入无字幕降级逻辑
- `DEEPSEEK_MODEL` 默认值改为 `deepseek-v4-flash`

---

## [2.0.0] - 2026-05-11

### 新增

- **AI 视频总结功能**：
  - 新增 `/api/summarize` 端点，输入视频 URL 即可生成 AI 总结
  - 集成 DeepSeek API（Anthropic 兼容端点），通过环境变量 `DEEPSEEK_API_KEY` 配置
  - 字幕获取策略：优先中文 → 其次英文 → 自动选择第一个可用字幕
  - 字幕清洗支持 SRT、VTT、JSON3 等多种格式
  - 长视频自动分片处理（超过 60000 字符分片摘要后再合并）

- **前端 AI 总结标签页**（`AiSummary.vue`）：
  - 视频信息卡片新增"下载 / AI 总结"标签栏切换
  - **内容摘要**：AI 生成的视频核心内容概要（200-500 字）
  - **章节大纲**：带时间戳的章节列表，展示各章节核心要点
  - **思维导图**：静态 SVG 树状图渲染，支持缩放（+/-/重置）
  - 加载状态：shimmer 骨架屏动画
  - 重新生成功能

- **免费限制机制**：
  - 每日 3 次免费 AI 总结（内存计数，重启清零）
  - 超出次数后显示 Pro 升级提示卡片

### 技术细节

- 新增 `core/summarizer.py`：DeepSeek API 调用模块，含字幕清洗、文本分片、prompt 工程、JSON 解析
- 新增数据模型：`SummarizeRequest`、`SummaryResult`、`ChapterItem`、`MindMapNode`
- 新增依赖：`anthropic>=0.40.0`（通过 DeepSeek 的 Anthropic 兼容端点调用）
- 新增 `core/summary_models.py`：AI 总结相关 Pydantic 模型（`SummarizeRequest`、`SummaryResult`、`ChapterItem`、`MindMapNode`）
- 新增 `api/summary_routes.py`：AI 总结路由，挂载到主应用
- 新增 `composables/useSummary.js`：AI 总结状态管理（`summarizeVideo()`、`summaryResult`、`isSummarizing`、`summarizeError`、`resetSummary`）
- 思维导图使用 `markmap-lib` + `markmap-view` 渲染（v2.2.0 起；v2.0.0 原为纯 SVG 渲染）

### 配置

需设置环境变量（`backend/.env`）：
- `DEEPSEEK_API_KEY`：DeepSeek API 密钥（必需）
- `DEEPSEEK_BASE_URL`：API 地址（默认 `https://api.deepseek.com/anthropic`，使用 Anthropic 兼容端点）
- `DEEPSEEK_MODEL`：模型名称（默认 `deepseek-v4-flash`，v2.1.0 起；v2.0.0 原默认为 `deepseek-chat`）

---

## [1.9.0] - 2026-05-11

### 修复

- **多P视频标题清理**（`downloader.py`）：
  - yt-dlp 对 B 站多P视频会在标题后追加 ` pNN 分P名称`，前端显示多余
  - 解析时用正则 `\s+p\d{2,}\s+.*$` 去掉该后缀，标题只保留原始视频名

- **文件大小估算算法重写**（`downloader.py`）：
  - 旧方案：直接用 yt-dlp 返回的 `filesize`/`filesize_approx` → Bilibili 数据严重不准
  - 新方案：用码率 `tbr` × 全视频时长 计算，`tbr` 是视频流真实属性，精度从 ~50% 误差降至 ~3%
  - 核心问题：yt-dlp 用 `noplaylist=True` 只解析第一P，`info['duration']` 是 P1 时长而非全视频时长
  - 修复：用分P列表时长之和作为总时长，同时修正返回给前端的 `duration` 字段
  - "最佳画质"选项：用最佳视频流码率 + 最佳音频流码率之和估算
  - 分P文件大小：用参考格式的每秒字节数 × 分P时长估算

- **清晰度区域动态大小**（`App.vue`）：
  - 选中分P后，清晰度列表中的文件大小按 `filesize ÷ 全视频时长 × 选中分P总时长` 动态调整
  - 未选中时默认显示当前分P（URL 中 `?p=` 参数）的大小
  - 标签中的单P大小描述（如 "，约 3.2 MB"）始终去掉，避免与动态总大小重复

- **下载按钮行为修正**（`App.vue`）：
  - 主下载按钮现在尊重分P选择：选中分P → 下载选中的（合并）；未选中 → 下载当前分P
  - 之前只下载第一P，忽略用户选择

### 优化

- **分P列表交互改进**（`App.vue`）：
  - 分P信息区域从 `<button>` 改为 `<div>`，点击不再触发页面刷新/重新解析
  - 只有点击左侧勾选框才触发选中操作，避免手机端误触
  - 移除 `cursor: pointer` 和 hover 变色效果

- **VideoPart 模型扩展**（`models.py`）：
  - 新增 `filesize`（估算字节数）和 `filesize_str`（人类可读大小）字段
  - 分P列表每行显示估算大小，方便用户判断下载量

---

## [1.8.0] - 2026-05-11

### 优化

- **视频信息区**（`App.vue`）：
  - 封面图增加播放图标叠加层（hover 显示）和时长角标
  - 元数据改为标签行展示：平台、上传者、播放量（万为单位自动换算）
  - 新增"查看原视频"链接（新窗口打开）

- **格式选择区**（`App.vue`）：
  - 视频/音频格式合并展示，去掉分组标签，音频格式用"仅音频"标签区分
  - 布局改为 2 列等宽网格（`grid-template-columns: repeat(2, 1fr)`），卡片更宽敞
  - 卡片内部：第一行格式名（加粗），第二行格式类型 + 文件大小（灰色小字）
  - 推荐标识从 emoji（⭐）改为 SVG 星标图标
  - 选中格式后显示详细信息栏（格式、编码、帧率、码率）
  - 移动端自动变为 1 列

- **字幕区**（`App.vue`）：
  - 字幕语言名颜色从 `#94A3B8` 提亮为 `#F1F5F9`，解决深色主题下看不清的问题
  - 分组标签（"手动字幕"/"自动生成字幕"）颜色从 `#64748B` 提亮为 `#94A3B8`
  - 翻译目标语言提示文字提亮
  - `<select>` 下拉框适配深色主题（自定义箭头 + option 背景色）

- **分P选择器**（`App.vue`）：
  - 每行增加时长显示（`mm:ss` 格式）
  - checkbox 尺寸从 18px 加大到 20px，圆角从 4px 调整为 5px

- **下载进度**（`App.vue`）：
  - 进度条增加 shimmer 动画效果（下载中状态）
  - 完成状态增加绿色对勾图标，失败状态增加红色叉号图标
  - 进度卡片边框随状态变色（完成=绿，失败=红）
  - 完成/失败状态进度条颜色同步变化

- **下载记录**（`App.vue`、`useDownloader.js`）：
  - 每条记录增加状态图标（成功/失败）
  - 增加下载时间戳（今天只显示时间，非今天显示日期+时间）
  - "保存"按钮增加下载图标
  - 历史记录数据新增 `time` 字段

---

## [1.7.0] - 2026-05-11

### 变更

- **前端 UI 深色主题改造**（全局）：
  - 整体视觉从白色浅色风格改为深蓝黑渐变主题（`#0F172A`），提升工具质感
  - 新增 CSS 变量体系（`--bg-primary`、`--text-primary`、`--accent-blue` 等），统一管理颜色
  - 字体新增 `Plus Jakarta Sans`（英文/品牌），中文继续使用 `Noto Sans SC`

- **NavBar.vue**：
  - 白色背景改为毛玻璃效果（`backdrop-filter: blur(16px)` + 半透明深色背景）
  - 文字颜色适配深色主题

- **HeroSection.vue**：
  - 标题改为"SaveAny 视频下载器"，品牌名用蓝青渐变色突出
  - 副标题精简为"粘贴链接，一键下载高清视频"
  - 按钮文案从"解析视频"改为"免费下载"
  - 新增信任标签行：无需注册 · 完全免费 · 支持 4K
  - 平台展示从 4 个静态圆形图标改为 10 个横向标签流，国内平台优先排列（B站、抖音、小红书、快手、微博、西瓜视频在前）
  - 背景新增蓝色光晕效果（`radial-gradient`）
  - 输入框 placeholder 更新为"粘贴视频链接，支持 B站、抖音、小红书、YouTube 等平台"

- **App.vue（Results 区域）**：
  - 所有卡片、按钮、进度条、字幕区域适配深色主题
  - 卡片使用半透明背景 + 毛玻璃边框（`backdrop-filter: blur(12px)`）
  - 进度条改为蓝青渐变

- **FeaturesSection.vue**：
  - 4 个现有卡片文案优化，突出具体数字和国内平台覆盖
  - 新增 2 个 Pro 专属卡片：字幕翻译、批量下载（带粉色 Pro badge）
  - 布局从 4 列改为 3 列（6 卡片 = 2 行）
  - 背景色改为 `var(--bg-secondary)`，与 Hero 区域形成层次

- **FooterSection.vue**（新增）：
  - 品牌区 + 产品/支持/法律三组链接
  - 支持平台列表（国内平台优先排列）
  - 版权信息

### 设计决策

- 目标用户以国内为主（B站、抖音、小红书等），平台展示国内优先
- 深色主题更符合年轻用户审美，提升"专业工具"质感
- Pro 卡片提前布局，为后续付费功能做视觉铺垫

---

## [1.6.0] - 2026-05-11

### 新增

- **字幕提取与翻译**：
  - 解析视频时自动获取可用字幕列表（手动字幕 + 自动生成字幕）
  - 前端在视频信息卡片中展示字幕列表，按"手动字幕"和"自动生成字幕"分组
  - 每个字幕轨道提供"下载"按钮（下载 SRT/VTT 原始字幕文件）
  - 每个字幕轨道提供"翻译"按钮，支持选择目标语言（中文、English、日本語、한국어 等 7 种）
  - 后端 `/api/subtitle` 端点：使用 yt-dlp 下载字幕文件
  - 后端 `/api/subtitle/translate` 端点：下载字幕 + 使用 deep-translator（Google Translate）翻译
  - SRT 格式按时间轴逐段翻译，保留时间码；其他格式逐行翻译

### 技术细节

- 新增 `SubtitleTrack` 数据模型（`core/models.py`）
- `VideoInfo` 新增 `subtitles` 字段
- `parse_info()` 新增 `listsubtitles: True` 提取字幕信息
- YouTube 翻译字幕：利用 yt-dlp 的 `automatic_captions` 中已有的翻译条目（带 `tlang` 参数），直接从 YouTube 服务器获取翻译结果，无需外部 API
- 其他平台翻译：降级到 MyMemory 翻译服务（免费、无需 API Key、国内可访问）
- 依赖新增 `deep-translator==1.11.4`

---

## [1.5.0] - 2026-05-11

### 新增

- **分P多选下载**（`core/downloader.py`、`api/routes.py`、`composables/useDownloader.js`、`App.vue`）：
  - 分P列表改为 checkbox 多选模式，每行左侧有勾选框，点击勾选/取消
  - 点击分P标题区域仍触发重新解析（切换预览），行为不变
  - 新增"全选/取消全选"切换按钮
  - 勾选 1 个及以上分P后出现"下载选中(N)"按钮，只下载并合并勾选的分P
  - 重新解析时自动清空勾选状态
  - 后端 `_download_concat_parts(selected_indices)` 支持按索引过滤，只下载指定分P
  - WebSocket 消息新增 `selected_parts: [1,2,3]` 字段传递选中列表

## [1.4.0] - 2026-05-11

### 新增

- **B 站分P视频支持**（`core/downloader.py`、`core/models.py`、`App.vue`）：
  - 解析时自动调用 `api.bilibili.com/x/player/pagelist` 获取分P列表，附加到 `VideoInfo.parts[]`
  - 前端在视频信息卡片中展示分P列表（可滚动），点击任意一P触发重新解析，高亮当前选中P
  - 新增"合并下载全部"按钮：逐P下载到独立子目录，再用 ffmpeg `-f concat -c copy` 拼接为单文件
  - 解析和下载均加 `noplaylist=True`，避免 yt-dlp 将多P视频当作 playlist 处理（修复解析慢/失败/只有一个清晰度的问题）

- **下载文件路径可靠性**（`core/downloader.py`）：
  - 每次下载使用独立的 `downloads/{task_id}/` 子目录，下载完成后扫描目录找最大视频文件
  - 替代原来的 `prepare_filename()` 方案（对 playlist info dict 不可靠，会导致"文件已被删除"错误）

- **分P合并下载**（`core/downloader.py` `_download_concat_parts()`）：
  - 每个分P下载到 `downloads/{task_id}/p{N:03d}/` 独立子目录，避免同名文件互相覆盖
  - 所有分P下载完成后生成 `concat_list.txt`，调用 ffmpeg 合并为 `merged.mp4`
  - 进度推送：每完成一P推送一次进度（0→90%），合并完成后推送 100%

- **前端新增 `startDownloadAll()`**（`composables/useDownloader.js`）：
  - 通过 WebSocket 消息携带 `concat_parts: true` 标志触发合并下载

### 修复

- **合并下载只保存最后一P**：原 `concat_playlist='always'` 方案中，所有分P输出到同一目录且文件名相同（均为视频标题），后P覆盖前P，最终只剩最后一P。改为逐P独立子目录下载后手动 ffmpeg 合并，彻底解决

- **"文件已被删除"错误**：`ydl.prepare_filename(info)` 在 playlist info dict 下返回错误路径，改为扫描任务目录找最大视频文件



### 新增

- **平台兼容层**：在 `core/downloader.py` 中新增两个 monkey-patch，解决特定平台在服务器环境下的解析问题，对上层代码完全透明：
  - `_patch_bilibili_extractor()`：
    - **412 补丁**：B 站网页在部分云服务器 IP 上返回 412，补丁在 412 时通过 `api.bilibili.com/x/web-interface/view` 获取视频数据，构造含 `window.__INITIAL_STATE__` 的假网页，让 yt-dlp 提取器正常运行
    - **画质补丁**：yt-dlp 默认使用 WBI 签名接口，未登录时限制到 480p；改用非 WBI 接口 `api.bilibili.com/x/player/playurl` + `try_look=1`，未登录可获取 1080p/720p
  - `_patch_douyin_extractor()`：抖音 web API 需要 JavaScript 生成的 `s_v_web_id` cookie（yt-dlp 自身有 TODO 未实现），补丁在 web API 报 cookie 错误时，降级到 `api.amemv.com` 移动端 API（Android 设备参数，无需 cookie）

- **短链与富文本 URL 解析**（`api/routes.py`）：
  - 从手机分享文本中提取 URL（如 `【标题-哔哩哔哩】 https://b23.tv/xxx`）
  - `b23.tv` 短链 → 解析 302 重定向，提取 BV ID，转为标准 `bilibili.com/video/BVxxx` URL
  - `v.douyin.com` 短链 → 解析 302 重定向，提取视频 ID，转为标准 `douyin.com/video/{id}` URL

- **缩略图代理通用化**（`api/routes.py`）：
  - 前端所有缩略图统一走 `/api/thumbnail?url=...` 代理，解决 HTTP 图片在 HTTPS 页面被浏览器拦截（Mixed Content）的问题
  - 代理根据 CDN 域名自动匹配正确的 `Referer`（如 `xhscdn.com` → `https://www.xiaohongshu.com/`），解决各平台 CDN 防盗链问题
  - 支持的 CDN 映射：xhscdn.com、hdslb.com、bilivideo.com、douyinvod.com、365yg.com、amemv.com、pstatp.com、ixigua.com、ytimg.com、googlevideo.com

### 修复

- **B 站清晰度**：修复未登录时只能获取 480p/360p 的问题，现在可获取 1080p/720p/480p/360p
- **小红书缩略图**：修复封面图无法显示的问题（Mixed Content + CDN 防盗链双重问题）
- **抖音解析**：修复 `Fresh cookies are needed` 错误，无需登录即可解析抖音视频

---



### 修复
- **缩略图防盗链**：新增 `/api/thumbnail` 代理端点，自动将 `http://` 升级为 `https://`，携带正确的 `Referer` 和 `User-Agent` 头，解决 B站等平台封面图无法显示的问题
- **格式选择为空**：重构格式构建逻辑，参考 yt-dlp 设计，始终提供"最佳画质（bestvideo+bestaudio/best）"选项；对视频流自动附加 `+bestaudio` 实现音视频合并；B站等无合并流的平台也能正常展示清晰度选项
- **WebSocket 路由不匹配**：移除 `APIRouter(prefix="/api")`，改为每个路由手动加前缀，使 WebSocket 路由 `/ws/download/{task_id}` 正确注册，进度条不再卡在 0%
- **文件名前缀**：移除下载文件名中的 `{task_id}_` 前缀，文件名直接使用视频标题
- **缩略图代理阻塞**：将 `urllib.request.urlopen` 改为在线程池（`run_in_executor`）中执行，避免阻塞 async 事件循环

### 新增
- `FormatOption` 模型新增 `is_best`（是否为最佳画质选项）和 `label`（前端展示标签）字段
- 格式列表结构：最佳画质 → 各分辨率视频流（自动合并音频）→ 音频流
- 前端格式按钮区分样式：最佳画质（蓝色渐变 + ⭐ 推荐标记）、音频（绿色）
- `HeroSection.vue` 输入框改为 `v-model` 双向绑定，修复浏览器自动填充不触发 Vue 响应式的问题

---

## [1.1.0] - 2026-05-10

### 变更
- **前端 UI 全面重新设计**，依据设计图（image/ 目录）重构页面布局和视觉风格
  - 品牌名称从"万能视频下载器"更新为 **SaveAny**
  - 主色调从紫蓝渐变改为 **蓝色系**（#3b82f6 / #2563eb）
  - 背景从深色渐变改为**白色 + 浅蓝渐变**，整体更简洁明亮
- **NavBar.vue** 重构：
  - 新增 SaveAny Logo（图标 + 文字）
  - 新增导航菜单：功能特性、使用教程、工具箱、常见问题
  - 新增登录和立即使用按钮
- **HeroSection.vue** 重构：
  - 标题改为"免费在线视频下载器，一键保存"
  - 副标题列出支持的主流平台（抖音、快手、小红书、YouTube、Bilibili、TikTok 等）
  - **输入框和解析按钮内嵌到 Hero 区域**，移除原来独立的下载入口区块
  - 新增平台品牌图标展示（YouTube、TikTok、Bilibili、抖音）
- **FeaturesSection.vue** 新增：
  - 标题"为什么选择 SaveAny 视频下载器"
  - 4 个特性卡片（支持1000+平台、极速解析下载、任意格式、永久免费）
  - **强制一行排列**（`grid-template-columns: repeat(4, 1fr)`），平板降为 2 列，移动端 1 列
- **App.vue** 重构：
  - 移除独立的下载区块（download-section），结果区域改为按需显示（有解析结果或错误时才出现）
  - 输入状态（url、loading）提升到 App.vue，通过 props 传入 HeroSection
  - 样式全部改为 Scoped CSS，不再依赖 Tailwind 原子类

### 不变
- 后端 API 接口、数据模型、WebSocket 协议均无变化
- `useDownloader.js` 逻辑无变化
- 页面标题更新为"SaveAny - 免费在线视频下载器 | 支持1000+平台"

---

## [1.0.0] - 2026-05-10

### 新增
- 项目初始化：创建前后端项目骨架
- 后端核心：`VideoDownloader` 类封装 yt-dlp 能力
  - `parse_info()` 解析视频链接获取元数据和格式列表
  - `download()` 下载视频并支持进度回调
  - 自动选择下载模式（合并流优先）
- 后端 API：
  - `POST /api/parse` - 解析视频链接
  - `POST /api/download` - 创建下载任务
  - `WS /ws/download/{task_id}` - WebSocket 实时进度推送
  - `GET /api/files/{task_id}` - 下载已完成文件
  - `GET /api/health` - 健康检查
- 前端页面：Vue 3 + Vite + Tailwind CSS
  - 7 个核心组件：NavBar, HeroSection, UrlInput, VideoInfo, FormatSelector, DownloadProgress, DownloadHistory
  - `useDownloader.js` composable 封装 API/WebSocket 对接
  - 渐变紫蓝主题，对标 ai.codefather.cn/painting UI 风格
- 开发工具：
  - `start.bat` 一键启动脚本
  - Vite 开发代理配置
  - 项目文档（需求、架构、开发指南）

### 技术栈
- 前端：Vue 3 + Vite + Tailwind CSS 4
- 后端：FastAPI + yt-dlp (Python)
- 视频引擎：yt-dlp 2026.3.17
- 字体：Noto Sans SC (Google Fonts)

### 支持的平台
通过 yt-dlp 支持 1800+ 视频平台，包括：
YouTube, Bilibili, TikTok, Instagram, Twitter/X, Vimeo, Facebook 等

### 已知限制
- 无数据库持久化，任务状态重启后丢失
- 未实现字幕提取和翻译功能
- 未实现视频 AI 总结功能
- 未实现付费功能
- FFmpeg 需单独安装并加入 PATH