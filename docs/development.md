# 开发指南 — VideoMind

## 环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | >= 3.9（已在 3.14 验证） | 后端运行时 |
| Node.js | >= 18 | 前端构建和开发 |
| FFmpeg | 任意 | yt-dlp 合并音视频流必需 |

### FFmpeg 安装（Windows）

从 https://github.com/BtbN/FFmpeg-Builds/releases 下载，解压后将 `bin/` 目录加入系统 PATH。

## 环境变量配置

AI 总结功能需要在 `backend/.env` 中配置 API：

```env
# ── AI Provider ──
AI_PROVIDER=deepseek               # deepseek | openai | openrouter
AI_API_KEY=your_api_key_here
AI_BASE_URL=https://api.deepseek.com/anthropic
AI_MODEL=deepseek-v4-flash

# ── Prompt ──
PROMPT_VERSION=1                   # prompts/{name}/v{N}.txt 版本号

# ── Whisper 语音转录 ──
WHISPER_MODEL=small                # tiny | base | small | medium | large
SUBTITLE_CORRECTION_ENABLED=true   # AI 字幕校正开关
SUBTITLE_CORRECTION_MAX_CHARS=15000  # 校正最大字符数
WHISPER_MAX_DURATION=120           # 转录最大视频时长（秒），超过则跳过
```

### 兼容旧变量

旧版变量名仍然生效（优先级低于 `AI_*`）：

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic
DEEPSEEK_MODEL=deepseek-v4-flash
```

说明：
- `AI_BASE_URL` 使用 Anthropic 兼容端点（`/anthropic` 后缀），后端通过 `anthropic` SDK 调用
- `AI_MODEL` 默认 `deepseek-v4-flash`（非思考模型，约 11s）；如需更高质量可改为 `deepseek-v4-pro`（思考模型，60s+）
- `.env` 文件不应提交到 git

## 快速开始

### 1. 安装依赖

```bash
# 后端
cd backend
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 2. 启动开发环境

**方式一：一键启动（Windows）**

双击 `start.bat`

**方式二：手动启动**

终端 1 - 后端：
```bash
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

终端 2 - 前端：
```bash
cd frontend
npm run dev
```

### 3. 配置 Whisper 模型（可选）

Whisper 语音转录用于无字幕视频的兜底方案。模型文件需手动下载到本地：

```bash
# 模型目录结构
mkdir -p backend/data/whisper_models/faster-whisper-small

# 必需文件（从 HuggingFace 下载，约 2.4 GB）
# 国内镜像: https://hf-mirror.com/guillaumeklay/faster-whisper-small
# 文件列表: config.json, model.bin, tokenizer.json, vocabulary.txt
```

启动时自动检查模型完整性，缺失则禁用 Whisper（不影响其他功能）。

### 4. 访问

| 服务 | 地址 | 说明 |
|------|------|------|
| 前端页面 | http://localhost:5173 | Vue 3 开发服务器 |
| 后端 API | http://localhost:8000 | FastAPI 服务器 |
| API 文档 | http://localhost:8000/docs | Swagger UI |

## 开发工作流

### 前端开发

- 修改 `frontend/src/components/` 下的组件，Vite 会自动热重载
- `frontend/src/composables/useDownloader.js` 封装了所有 API 调用和 WebSocket 逻辑
- Vite 开发服务器通过代理将 `/api` 和 `/ws` 请求转发到后端

### 后端开发

- 修改 `backend/core/downloader.py` 来调整 yt-dlp 参数
- 修改 `backend/core/ai_client.py` 来调整 AI API 调用（统一客户端，含摘要/导图/笔记/问答的流式与非流式实现）
- 修改 `backend/core/summarizer.py` 来调整字幕清洗、B 站 CC 字幕提取或降级方案
- 修改 `backend/core/whisper.py` 来调整 Whisper 模型配置或转录参数
- 修改 `backend/core/cache.py` 来调整缓存策略或表结构（ai_cache / whisper_cache / video_info_cache）
- 修改 `backend/api/routes.py` 来增删视频下载相关 API 端点
- 修改 `backend/api/summary_routes.py` 来调整 AI 总结路由逻辑
- 修改 `backend/api/stream_routes.py` 来调整 SSE 流式端点逻辑
- 修改 `backend/api/subtitle_text_routes.py` 来调整字幕文本提取逻辑
- 修改 `backend/core/models.py` 来调整视频下载数据模型
- 修改 `backend/core/summary_models.py` 来调整 AI 总结数据模型
- 修改 `backend/prompts/` 下的模板文件来调整 AI 输出质量
- 启用 `--reload` 参数后，代码修改会自动重启服务

### AI 总结开发说明

**架构分层**：
- `core/ai_client.py` — 统一 AI API 客户端，所有 AI 调用入口（流式/非流式），不包含业务逻辑
- `core/summarizer.py` — 字幕清洗 + B 站 CC 字幕提取 + 降级方案，AI 调用委托给 `ai_client.py`
- `core/cache.py` — SQLite 持久化缓存，URL → AI 结果映射
- `core/summary_models.py` — Pydantic 数据模型
- `api/stream_routes.py` — SSE 流式端点，编排缓存→字幕→AI→持久化全流程
- `prompts/{name}/v{N}.txt` — Prompt 模板文件，通过 `{variable}` 占位符注入上下文

**模块详解**：

`core/ai_client.py`（统一 AI 客户端）：
- `_load_prompt(name)` 从 `prompts/{name}/v{PROMPT_VERSION}.txt` 加载模板
- `_parse_json_response(content)` 从 AI 响应提取 JSON（支持 ` ```json ``` ` 包裹和裸 JSON）
- `_chunk_summarize(subtitle_text, title)` 长视频分片 pipeline（>60000 字符触发）
- 流式 API 使用 `client.messages.stream()`，yield `(event_type, data)` tuple
- 非流式 API 返回 dict（结构化 JSON 解析后）
- `_extract_text(response)` 兼容思考模型（`ThinkingBlock` + `TextBlock`）和非思考模型

`core/cache.py`（SQLite 持久化缓存，三张表）：
- 表 `ai_cache`：`url_hash TEXT PRIMARY KEY` + `url, video_title, subtitle_text, source, result_json, created_at, updated_at`
- 表 `whisper_cache`：`url_hash TEXT PRIMARY KEY` + `url, subtitle_text, language, raw_text, created_at` — 存储校正后文本 + 原始转录
- 表 `video_info_cache`：`url_hash TEXT PRIMARY KEY` + `url, duration, title, info_json, created_at` — 避免重复 yt-dlp 解析
- `get_cached(url)` → dict | None；`save_cache(url, ...)` → upsert；`list_history(limit)` / `delete_cache(url)`
- 缓存完整 AI 输出（result + mindmap + notes），命中后 SSE 重放，零 token 消耗

`core/whisper.py`（Faster-Whisper 转录模块）：
- `is_model_available()` — 检查本地模型文件完整性
- `transcribe(audio_path, language)` — 直接转录音频文件
- `transcribe_video(url, language)` — 下载音频 + 转录 + 清理临时文件
- 模型配置：device="cpu"，compute_type="int8"，local_files_only=True
- VAD 过滤：beam_size=5，vad_filter=True
- 字幕 AI 校正：`correct_subtitle(text, title, description)` 在 `ai_client.py` 中

`api/stream_routes.py`（SSE 流式端点）：
- `_get_subtitle_text()` 标准化字幕 pipeline：B 站 CC API → yt-dlp 原生 → Whisper + AI 校正
- 视频时长预检：先查 `video_info_cache`，超长视频直接拦截（跳过慢速 yt-dlp 解析）
- 缓存优先：`get_cached()` 命中 → SSE 重放，不调用 AI
- 进度阶段：`subtitle_loaded` → `summary_generating` → `mindmap_generating` → `notes_generating`
- 流水线完成后 `save_cache()` + `save_video_info_cache()` 持久化
- `_sse_generator` 使用 `asyncio.Queue` + `loop.call_soon_threadsafe` 跨线程实时流式

**Prompt 系统**：
- 模板位于 `backend/prompts/{name}/v{N}.txt`
- 变量通过 Python `.format()` 注入：`{video_title}`、`{subtitle_text}`、`{content_summary}`
- 切换版本：修改 `.env` 中 `PROMPT_VERSION`
- 要求 AI 输出结构化 JSON（非纯文本），便于后续解析和学习卡片生成

**其他要点**：
- `extract_bilibili_subtitle(url)` 通过 Bilibili CC 字幕 API（`/x/v2/dm/view?type=1`）获取真实字幕，优先于 yt-dlp
- 无字幕时自动降级到 `summarize_from_description()`，前端显示 `⚠️` 警告
- `danmaku` 轨道在 `downloader.py` 中过滤，弹幕 XML 通过 `_clean_danmaku_xml()` 专门解析
- 思维导图渲染使用 `markmap-lib` + `markmap-view`；导出须基于 `mindmapMarkdown` 离屏重新渲染
- 前端 Markdown 渲染使用 `marked` + `DOMPurify`，注意 XSS 防护
- 摘要区和问答区列表缩进依赖 `AiSummary.vue` 中显式 CSS，不要假设 `prose` 默认样式

### 新增平台兼容补丁

当某个平台出现解析错误时，在 `core/downloader.py` 末尾添加 monkey-patch 函数，参考已有的 `_patch_bilibili_extractor` 和 `_patch_douyin_extractor`。

常见错误类型及处理思路：

| 错误 | 原因 | 处理方式 |
|------|------|----------|
| HTTP 412 / 403 | 服务器 IP 被封，网页请求被拒 | 改调平台 API 接口，构造假网页数据 |
| Fresh cookies needed | 需要 JS 生成的 cookie | 寻找移动端 API 或其他无 cookie 接口 |
| Unable to extract | 提取器解析失败 | 查看 yt-dlp 源码，找降级路径 |

### 新增短链支持

在 `api/routes.py` 的 `_resolve_short_url` 函数中添加新平台的短链解析逻辑，参考已有的 `b23.tv` 和 `v.douyin.com` 处理方式：只取 302 重定向的 `Location` header，不跟随到最终页面。

### 新增缩略图 CDN 映射

在 `api/routes.py` 的 `proxy_thumbnail` 函数中的 `_CDN_REFERER` 字典里添加新平台的 CDN 域名后缀和对应 Referer。

### 样式开发

本项目前端样式采用**两层结构**：

- **全局样式** `frontend/src/style.css`：仅包含 Tailwind 导入、基础重置（`* { box-sizing: border-box }`）和少量全局动画
- **组件样式**：每个组件使用 `<style scoped>` 编写独立 CSS，不使用 Tailwind 原子类

> 注意：早期版本曾使用 Tailwind 原子类，当前版本已全部迁移为 Scoped CSS，新增组件请遵循此规范。

## 生产构建

```bash
# 构建前端
cd frontend
npm run build

# 启动生产模式（FastAPI 会托管前端静态文件）
cd ../backend
python main.py
```

生产模式下访问 http://localhost:8000 即可。

## 目录说明

```
videomind/
├── backend/                    # Python 后端
│   ├── main.py                 # FastAPI 应用入口（含 CORS、静态文件服务）
│   ├── requirements.txt        # Python 依赖清单
│   ├── .env                    # 环境变量（DEEPSEEK_API_KEY 等，不提交 git）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── downloader.py       # yt-dlp 核心封装类 VideoDownloader
│   │   ├── ai_client.py        # 统一 AI API 客户端（流式/非流式，prompt 加载，字幕校正）
│   │   ├── summarizer.py       # 字幕清洗 + B 站 CC 字幕提取 + 降级方案
│   │   ├── whisper.py          # Faster-Whisper 转录模块（本地模型，CPU/int8）
│   │   ├── cache.py            # SQLite 持久化缓存（ai_cache + whisper_cache + video_info_cache）
│   │   ├── summary_models.py   # AI 总结 Pydantic 模型
│   │   └── models.py           # 视频下载 Pydantic 数据模型
│   ├── prompts/                # Prompt 模板（版本化）
│   │   ├── summary/v1.txt
│   │   ├── notes/v1.txt
│   │   ├── mindmap/v1.txt
│   │   ├── flashcard/v1.txt
│   │   └── subtitle_correction/v1.txt
│   ├── data/
│   │   ├── chroma/              # ChromaDB 向量数据库
│   │   └── whisper_models/      # Whisper 本地模型文件
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py                # REST + WebSocket 路由（含 bilibili.com URL 规范化）
│   │   ├── summary_routes.py        # AI 总结路由（/api/summarize，含无字幕降级）
│   │   ├── stream_routes.py         # SSE 流式端点（/api/summarize/stream + /api/chat/stream）
│   │   └── subtitle_text_routes.py  # 字幕文本提取端点（/api/subtitle/text）
│   └── downloads/              # 视频下载输出目录（自动创建）
├── frontend/                   # Vue 3 前端
│   ├── vite.config.js          # Vite 配置（插件、代理）
│   ├── index.html              # HTML 入口
│   ├── package.json            # Node.js 依赖
│   └── src/
│       ├── main.js             # Vue 应用入口
│       ├── App.vue             # 根组件（串联所有子组件）
│       ├── style.css           # Tailwind 和自定义样式
│       ├── components/         # Vue 组件
│       │   ├── NavBar.vue          # 顶部导航栏（品牌 + 菜单 + 按钮）
│       │   ├── HeroSection.vue     # Hero 区域（含输入框和解析按钮）
│       │   ├── AiSummary.vue       # AI 总结（流式摘要+章节大纲+思维导图+AI 问答，Markdown 渲染，含 CJK 宽度修正）
│       │   ├── FeaturesSection.vue # 特性展示（4 卡片一行）
│       │   ├── UrlInput.vue        # 备用（当前未使用）
│       │   ├── VideoInfo.vue       # 备用（当前未使用）
│       │   ├── FormatSelector.vue  # 备用（当前未使用）
│       │   ├── DownloadProgress.vue # 备用（当前未使用）
│       │   ├── DownloadHistory.vue  # 备用（当前未使用）
│       │   └── HelloWorld.vue       # 备用（Vite 脚手架默认组件，当前未使用）
│       └── composables/
│           ├── useDownloader.js # 下载 API/WebSocket 对接（核心状态管理）
│           ├── useSummary.js    # AI 总结状态管理（SSE 流式接收、Markdown 渲染、字幕文本获取）
│           └── useChat.js       # AI 问答状态管理（流式对话、历史记录）
├── docs/                       # 项目文档
├── start.bat                   # Windows 一键启动脚本
└── README.md
```

## 调试技巧

### 查看后台日志

后端使用 uvicorn 的 `--reload` 模式，代码修改后自动重启；启动终端会实时显示请求日志和错误信息。

### 使用 API 文档调试接口

打开 http://localhost:8000/docs，可以直接在 Swagger UI 中测试所有 REST 端点。

### WebSocket 调试

在浏览器开发者工具 → Network → WS 标签页可以查看 WebSocket 消息。

### 常见问题

**Q: 提示 "No module named 'core.downloader'"**

A: 确保在 `backend/` 目录下启动服务（`cd backend && python -m uvicorn main:app`）。

**Q: 下载时提示 ffmpeg 找不到**

A: 安装 FFmpeg 并加入 PATH，或在 `downloader.py` 中通过 `ffmpeg_location` 参数指定路径。

**Q: 前端页面无法访问后端 API**

A: 检查 Vite 代理配置是否正确（`vite.config.js` 中的 proxy 配置）。确保后端在 8000 端口运行。

**Q: B 站解析报 412 错误**

A: 云服务器 IP 被 B 站封锁，`_patch_bilibili_extractor()` 会自动处理。如果仍然失败，检查 `api.bilibili.com` 是否可访问。

**Q: 抖音解析报 "Fresh cookies needed"**

A: `_patch_douyin_extractor()` 会自动降级到移动端 API。如果失败，检查 `api.amemv.com` 是否可访问。

**Q: 某平台缩略图不显示**

A: 两种可能：① CDN 防盗链——在 `proxy_thumbnail` 的 `_CDN_REFERER` 字典中添加该平台 CDN 域名和 Referer；② Mixed Content——确认前端使用的是 `/api/thumbnail?url=...` 代理而非直接 URL。

**Q: 手机分享链接解析失败（带标题文字）**

A: `extract_url()` 会自动从文本中提取 URL。如果短链无法解析，检查 `_resolve_short_url()` 是否覆盖了该短链域名。

**Q: AI 总结报错 `'ThinkingBlock' object has no attribute 'text'`**

A: 使用了 DeepSeek 思考模型（如 `deepseek-v4-pro`），其响应第一个 block 是 `ThinkingBlock`。`summarizer.py` 中的 `_extract_text()` 已处理此情况；如果仍报错，检查 `summarizer.py` 是否是最新版本。

**Q: AI 总结提示"该视频无字幕"**

A: 部分平台（如 Bilibili）不提供 yt-dlp 可获取的字幕，系统会自动降级为基于视频简介生成总结，并在结果顶部显示 `⚠️` 警告。这是预期行为，不是错误。

**Q: AI 总结速度很慢（超过 60 秒）**

A: 检查 `backend/.env` 中的 `DEEPSEEK_MODEL`，如果是 `deepseek-v4-pro`（思考模型）则速度较慢。改为 `deepseek-v4-flash` 可将耗时降至约 11 秒。

**Q: 思维导图文字超出方框**

A: `AiSummary.vue` 的 `measureText()` 函数负责计算节点宽度。如果出现溢出，检查节点文本是否包含特殊字符或混合 CJK+ASCII 内容，可适当增大 `MINDMAP_CONFIG.fontSize` 或 `nodeGapX` 参数。

**Q: AI 总结 SSE 流式无实时输出（全部一次性返回）**

A: 检查 `stream_routes.py` 中的 `_sse_generator` 是否被回退为 `list()` 缓冲方案。正确实现使用 `asyncio.Queue` + `loop.call_soon_threadsafe`，确保每个 SSE 事件即时推送。

**Q: B 站视频有字幕但系统返回"无字幕"**

A: 检查 `extract_bilibili_subtitle()` 是否正常调用。B 站的 CC 字幕通过 `api.bilibili.com/x/v2/dm/view?type=1` 获取，与 yt-dlp 的字幕机制完全不同。如果 `dm/view` API 返回空 `subtitles` 列表，则该视频确实没有 CC 字幕。

**Q: AI 问答提示"字幕内容为空，无法进行问答"**

A: `chat_stream` 端点要求前端先通过 `/api/subtitle/text` 获取字幕文本，然后在请求体中传入 `subtitle_text` 字段。不能直接传 URL。

**Q: Whisper 转录提示"模型未就绪"**

A: 检查 `backend/data/whisper_models/faster-whisper-small/` 目录下是否包含 4 个必需文件：`config.json`、`model.bin`、`tokenizer.json`、`vocabulary.txt`。缺失则转录功能自动禁用。

**Q: Whisper 转录非常慢**

A: Faster-Whisper small 在 CPU 上的实时率约为 3-5x，2 分钟视频约需 6-10 分钟。超过 `WHISPER_MAX_DURATION`（默认 120s）的视频会自动跳过。如需提升速度，可考虑：① 使用 GPU ② 换用 tiny 模型 ③ 调大 WHISPER_MAX_DURATION。

**Q: 字幕校正后内容异常短**

A: `correct_subtitle()` 有 30% 长度校验：如果校正后文本少于原始文本的 30%，判定为异常并降级使用原始文本。日志会输出 `[SubtitleCorrection] 校正失败` 提示。

**Q: 抖音视频解析很慢（20s+）**

A: yt-dlp 请求抖音页面获取视频信息较慢，这是正常现象。首次解析后结果缓存到 `video_info_cache` 表，二次访问毫秒级。超长视频在缓存命中后会直接拦截，不再调用 yt-dlp。

**Q: 长视频点 AI 总结仍然提示"超过限制"**

A: 这是预期行为。超过 `WHISPER_MAX_DURATION`（默认 120s）的无字幕视频不支持语音识别。如果视频有简介，会自动降级为基于简介的总结。