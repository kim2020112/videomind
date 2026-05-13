# 开发指南

## 环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | >= 3.9（已在 3.14 验证） | 后端运行时 |
| Node.js | >= 18 | 前端构建和开发 |
| FFmpeg | 任意 | yt-dlp 合并音视频流必需 |

### FFmpeg 安装（Windows）

从 https://github.com/BtbN/FFmpeg-Builds/releases 下载，解压后将 `bin/` 目录加入系统 PATH。

## 环境变量配置

AI 总结功能需要在 `backend/.env` 中配置 DeepSeek API：

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic
DEEPSEEK_MODEL=deepseek-v4-flash
```

说明：
- `DEEPSEEK_BASE_URL` 使用 DeepSeek 的 **Anthropic 兼容端点**（`/anthropic` 后缀），后端通过 `anthropic` SDK 调用，而非 OpenAI 兼容端点
- `DEEPSEEK_MODEL` 默认 `deepseek-v4-flash`（非思考模型，约 11s）；如需更高质量可改为 `deepseek-v4-pro`（思考模型，60s+）
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

### 3. 访问

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
- 修改 `backend/api/routes.py` 来增删视频下载相关 API 端点
- 修改 `backend/api/summary_routes.py` 来调整 AI 总结路由逻辑
- 修改 `backend/api/stream_routes.py` 来调整 SSE 流式端点逻辑
- 修改 `backend/api/subtitle_text_routes.py` 来调整字幕文本提取逻辑
- 修改 `backend/core/summarizer.py` 来调整 AI 总结 prompt、B 站 CC 字幕提取或分片策略
- 修改 `backend/core/models.py` 来调整视频下载数据模型
- 修改 `backend/core/summary_models.py` 来调整 AI 总结数据模型
- 启用 `--reload` 参数后，代码修改会自动重启服务

### AI 总结开发说明

- `summarizer.py` 中的 `_extract_text(response)` 负责从 Anthropic SDK 响应中提取文本，同时兼容思考模型（`ThinkingBlock` + `TextBlock`）和非思考模型（仅 `TextBlock`）
- `stream_summarize()` 使用 `client.messages.stream()` 实现流式 AI 总结，yield `(event_type, data)` tuple 用于 SSE
- `extract_bilibili_subtitle(url)` 通过 Bilibili CC 字幕 API（`/x/v2/dm/view?type=1`）获取真实字幕，优先于 yt-dlp；yt-dlp 对 B 站只返回弹幕 XML
- `_sse_generator` 使用 `asyncio.Queue` + `loop.call_soon_threadsafe` 实现跨线程实时流式传输，注意不要回退到 `list()` 缓冲方案
- 无字幕时自动降级到 `summarize_from_description()`，基于视频标题和简介生成总结，前端会显示 `⚠️` 警告
- `danmaku` 语言轨道的字幕在 `downloader.py` 中被过滤，不出现在前端字幕列表；弹幕 XML 通过 `_clean_danmaku_xml()` 专门解析
- 思维导图渲染在 `AiSummary.vue` 的 `measureText()` 中，CJK 字符按 `fontSize * 1.0` 计算宽度，ASCII 按 `fontSize * 0.7`，修改 prompt 输出结构时需同步检查节点宽度是否够用
- 前端 Markdown 渲染使用 `marked` + `DOMPurify`，修改 `renderMarkdown()` 或在模板中新增 `v-html` 时注意 XSS 防护

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
free-video-downloader/
├── backend/                    # Python 后端
│   ├── main.py                 # FastAPI 应用入口（含 CORS、静态文件服务）
│   ├── requirements.txt        # Python 依赖清单
│   ├── .env                    # 环境变量（DEEPSEEK_API_KEY 等，不提交 git）
│   ├── core/
│   │   ├── __init__.py
│   │   ├── downloader.py       # yt-dlp 核心封装类 VideoDownloader
│   │   ├── summarizer.py       # DeepSeek AI 总结（B 站 CC 字幕提取、字幕清洗、流式/非流式 prompt）
│   │   ├── summary_models.py   # AI 总结 Pydantic 模型
│   │   └── models.py           # 视频下载 Pydantic 数据模型
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