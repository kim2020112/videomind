# 方案设计文档 — VideoMind

## 1. 技术选型

| 层次 | 技术 | 选型理由 |
|------|------|----------|
| 前端框架 | Vue 3 + Vite | 轻量、快速、生态成熟 |
| CSS 框架 | Tailwind CSS 4 | 原子化 CSS，快速构建 UI |
| 后端框架 | FastAPI (Python) | 异步支持好、自动生成 API 文档、WebSocket 原生支持 |
| 视频引擎 | yt-dlp | GitHub 19w+ Star，支持主流视频平台，Python 库直接调用 |
| AI 总结 | anthropic SDK + DeepSeek | 通过 Anthropic 兼容端点调用，支持流式 MessageStream（thinking + text 双轨） |
| Markdown 渲染 | marked + DOMPurify | 轻量无依赖，XSS 防护，AI 输出结构化展示 |
| 思维导图 | markmap-lib + markmap-view | 将 Markdown 列表渲染为交互式思维导图 |
| 导图导出 | 原生 SVG + Canvas | SVG 走离屏重渲染与静态化导出，PNG 基于内联 SVG 生成 4K 位图，避免受展示区缩放影响 |
| 进度推送 | WebSocket / SSE | 下载用 WebSocket（双向），AI 总结用 SSE（单向流式） |
| 进程管理 | Uvicorn | 高性能 ASGI 服务器 |

## 2. 系统架构

```
┌──────────────────────────────────────────────────┐
│                    浏览器                          │
│  ┌────────────────────────────────────────────┐  │
│  │         Vue 3 + Vite + Tailwind CSS         │  │
│  │  NavBar / Hero / UrlInput / VideoInfo       │  │
│  │  FormatSelector / DownloadProgress / History│  │
│  │              useDownloader.js               │  │
│  └──────────────┬─────────────────────────────┘  │
│                 │  HTTP / WebSocket                │
└─────────────────┼──────────────────────────────────┘
                  │
┌─────────────────┼──────────────────────────────────┐
│                 ▼                                   │
│  ┌────────────────────────────────────────────┐  │
│  │            FastAPI (Python)                  │  │
│  │  /api/parse  /api/download  /api/health     │  │
│  │  /ws/download/{task_id}  /api/files/{id}    │  │
│  └──────────────┬─────────────────────────────┘  │
│                 │                                   │
│  ┌──────────────▼─────────────────────────────┐  │
│  │   VideoDownloader (core/downloader.py)      │  │
│  │   parse_info()    download()                │  │
│  │   progress_hook → asyncio.Queue → WS        │  │
│  └──────────────┬─────────────────────────────┘  │
│                 │                                   │
│  ┌──────────────▼─────────────────────────────┐  │
│  │         yt-dlp (Python Library)              │  │
│  │         extract_info / download              │  │
│  └──────────────┬─────────────────────────────┘  │
└─────────────────┼──────────────────────────────────┘
                  │
┌─────────────────▼──────────────────────────────────┐
│              视频平台 (YouTube / B站 / ...)          │
└─────────────────────────────────────────────────────┘
```

## 3. 核心流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant FE as 前端(Vue)
    participant BE as 后端(FastAPI)
    participant DL as yt-dlp
    participant Platform as 视频平台

    U->>FE: 粘贴视频链接
    FE->>BE: POST /api/parse {url}
    BE->>DL: extract_info(url, download=False)
    DL->>Platform: 解析页面/调用API
    Platform-->>DL: 视频元数据
    DL-->>BE: info + formats
    BE-->>FE: {title, thumbnail, duration, formats[]}
    FE->>U: 展示视频信息卡片 + 格式选择

    U->>FE: 选择格式，点击下载
    FE->>BE: POST /api/download {url, format_id}
    BE->>FE: {task_id, ws_url}
    BE->>DL: download(url, format)
    DL->>Platform: 下载视频
    loop WebSocket 推送
        DL-->>BE: progress_hook 回调
        BE-->>FE: WS {percent, speed, eta, status}
        FE->>U: 实时更新进度条
    end
    BE-->>FE: WS {status: "completed", file_path}
    FE->>U: 显示下载完成
    U->>FE: 点击保存文件
    FE->>BE: GET /api/files/{task_id}
    BE-->>FE: 文件流
```

## 4. API 设计

### 4.1 REST 接口

| 方法 | 路径 | 说明 | 请求体 | 响应 |
|------|------|------|--------|------|
| GET | `/api/health` | 健康检查 | - | `{"status": "ok"}` |
| POST | `/api/parse` | 解析视频链接 | `{"url": "..."}` | VideoInfo |
| GET | `/api/thumbnail` | 缩略图代理 | `?url=...` | 图片二进制流 |
| GET | `/api/subtitle` | 下载字幕文件 | `?url=...&lang=...&auto=false` | SRT/VTT 字幕文件 |
| GET | `/api/subtitle/translate` | 翻译字幕 | `?url=...&lang=...&target=zh-Hans` | 翻译后的字幕文件 |
| GET | `/api/subtitle/text` | 字幕文本提取 | `?url=...&lang=zh` | `{"text": "...", "lang": "zh", ...}` |
| POST | `/api/summarize` | AI 视频总结（同步） | `{"url": "..."}` | SummaryResult |
| POST | `/api/summarize/stream` | AI 视频总结（SSE 流式） | `{"url": "...", "lang": "zh"}` | SSE 事件流 |
| POST | `/api/chat/stream` | AI 问答（SSE 流式） | `{"subtitle_text": "...", "question": "...", "history": []}` | SSE 事件流 |
| POST | `/api/download` | 创建下载任务 | `{"url": "...", "format_id": "best"}` | `{"task_id": "...", "ws_url": "..."}` |
| GET | `/api/files/{task_id}` | 下载文件 | - | 文件流 |
| GET | `/api/downloads` | 已完成任务列表 | - | `{"downloads": [...]}` |

### 4.2 实时通信

**WebSocket** — 下载进度推送

| 路径 | 说明 |
|------|------|
| `WS /ws/download/{task_id}` | 实时下载进度推送 |

WebSocket 消息格式：

```json
{
  "status": "downloading",
  "percent": 45.2,
  "speed": "2.1 MB/s",
  "eta": 30,
  "downloaded": 52428800,
  "total": 115343360
}
```

**SSE（Server-Sent Events）** — AI 总结/问答实时流式输出

SSE 端点返回 `text/event-stream`，事件格式：

```json
data: {"type": "progress", "data": {"stage": "subtitle_loaded", ...}}

data: {"type": "thinking_start", "data": {}}

data: {"type": "thinking", "data": {"text": "..."}}

data: {"type": "text", "data": {"text": "..."}}

data: {"type": "result", "data": {"summary": "...", "chapters": [...], "mindmap": {...}}}

data: {"type": "mindmap", "data": {"markdown": "..."}}

data: {"type": "notes_text", "data": {"text": "..."}}

data: {"type": "done", "data": {}}
```

事件类型：

| 事件 | 说明 |
|------|------|
| `progress` | 进度通知（字幕加载完成等） |
| `thinking_start` / `thinking` / `thinking_end` | 思考模型推理过程 |
| `text_start` / `text` | AI 摘要流式文本生成 |
| `notes_text` | 学习笔记流式文本生成（逐 token） |
| `mindmap` | 思维导图 Markdown（一次性） |
| `result` | 最终结构化结果 |
| `warn` | 警告信息 |
| `error` | 错误信息 |
| `done` | 流结束 |

实现原理：`_sse_generator` 使用 `asyncio.Queue` + `loop.call_soon_threadsafe` 实现真正的实时流式传输，每生成一个 token 即推送至客户端，不再缓冲。

状态枚举：`pending` → `downloading` → `processing` → `completed` / `failed`

客户端发送下载指令格式：

```json
{
  "url": "https://www.bilibili.com/video/BVxxx",
  "format_id": "bestvideo+bestaudio/best",
  "concat_parts": true,
  "selected_parts": [1, 2, 3]
}
```

`concat_parts: true` 触发分P合并下载；`selected_parts` 为空时下载全部分P。

### 4.3 数据模型

**ParseRequest**：解析请求
- url（视频链接）

**VideoInfo**：视频元数据
- title, webpage_url, duration, thumbnail, description, uploader, view_count, extractor, formats[], parts[]

**FormatOption**：格式选项
- format_id, ext, resolution, height, fps, vcodec, acodec, filesize, is_audio_only, is_video_only, is_combined

**SubtitleTrack**：字幕轨道
- lang（语言代码）, name（显示名称）, ext（格式后缀）, is_auto（是否自动生成）

**VideoPart**：分P条目（仅 B 站多P视频）
- index（P序号）, title（分P标题）, duration, filesize（估算字节数）, filesize_str

**DownloadRequest**：下载请求
- url, format_id, concat_parts（是否合并分P）, selected_parts（选中的分P索引列表）

**DownloadTask**：下载任务
- task_id, url, format_id, status, ws_url, file_path, title, created_at

**ProgressData**：进度数据
- status, percent, speed, eta, downloaded, total, file_path, error

**SummarizeRequest**：AI 总结请求
- url（视频链接）, lang（字幕语言偏好，默认 `zh`）

**SummaryResult**：AI 总结结果
- summary（摘要文本）, chapters[]（章节大纲：time/title/content）, mindmap（思维导图：title/children）

**ChatMessage**：对话消息
- role（`user` / `assistant`）, content（消息内容）

**ChatRequest**：AI 问答请求
- subtitle_text（字幕纯文本）, question（用户问题）, history[]（历史对话记录）

> AI 总结使用 `anthropic` SDK 调用 DeepSeek 的 Anthropic 兼容端点（`https://api.deepseek.com/anthropic`），而非 OpenAI 兼容端点。

## 5. 前端组件树

```
App.vue
├── NavBar.vue                 # 顶部导航（毛玻璃效果，Logo + 导航菜单 + 登录/立即使用按钮）
├── HeroSection.vue            # Hero 区域（深色背景 + 光晕 + 标题 + 输入框 + 下载按钮 + 平台标签流）
├── results section (内联)     # 解析结果区域（仅在有结果或错误时显示）
│   ├── error-card             # 错误提示（红色半透明背景）
│   ├── video-card             # 视频信息卡片
│   │   ├── video-info         # 封面图（含播放图标叠加层+时长角标）+ 标题 + 元数据标签行 + 原视频链接
│   │   ├── tab-bar            # 标签栏（下载 / AI 总结）
│   │   ├── [下载标签页]
│   │   │   ├── parts-section      # 分P选择器（B站多P视频，checkbox+序号+标题+时长）
│   │   │   ├── format-section     # 格式选择（2列等宽网格，视频/音频合并展示）
│   │   │   ├── subtitle-section   # 字幕区（手动/自动分组，下载+翻译按钮）
│   │   │   ├── download-button    # 下载按钮（蓝青渐变，全宽）
│   │   │   └── progress-card      # 下载进度（shimmer动画，状态图标+边框变色）
│   │   └── [AI 总结标签页]
│   │       └── AiSummary.vue      # AI 总结组件（内含：字幕加载状态 + 流式摘要 + 章节大纲 + 思维导图 + AI 问答，Markdown 渲染）
│   └── history-card           # 下载记录（状态图标+标题+时间戳+保存按钮）
├── FeaturesSection.vue        # 特性展示区（6 个卡片，3 列排列，含 2 个 Pro 卡片）
└── FooterSection.vue          # 页脚（品牌 + 链接 + 平台列表 + 版权）
```

**设计说明：**
- 整体采用深色主题（`#0F172A`），CSS 变量统一管理颜色
- 输入框和解析按钮内嵌在 `HeroSection.vue` 中，通过 props 传入 `url`、`loading` 状态和事件回调
- 视频信息、格式选择、下载进度、下载历史均在 `App.vue` 的 results section 中内联实现，不拆分为独立组件
- `FeaturesSection.vue` 为纯展示组件，含 4 个基础功能卡片 + 2 个 Pro 专属卡片
- `FooterSection.vue` 为纯展示组件，包含产品/支持/法律链接和平台列表
- 平台展示以国内为主（B站、抖音、小红书），海外平台为辅（YouTube、TikTok、Instagram 等）
- 辅助函数：`formatViewCount()`（播放量万为单位）、`formatDuration()`（秒转 mm:ss）、`formatTime()`（时间戳格式化）
- 下载历史数据通过 `useDownloader.js` 管理，每条记录包含 `task_id`、`title`、`status`、`time` 字段

## 6. 关键技术决策

| 决策 | 方案 | 原因 |
|------|------|------|
| yt-dlp 集成方式 | Python 库 `import yt_dlp` | 类型安全、无子进程开销、进度回调直接 |
| 进度推送 | `progress_hook` → `asyncio.Queue` → WebSocket | 延迟 < 100ms，天然异步 |
| 文件存储 | `downloads/{task_id}/{title}.{ext}` | 每任务独立目录，避免同名覆盖，路径可靠 |
| 任务存储 | 内存 dict | 无数据库依赖，重启清空可接受 |
| 多线程 | 每任务独立 `YoutubeDL` 实例 | yt-dlp 非线程安全 |
| 前端代理 | Vite proxy → 后端 | 开发模式避免跨域 |
| 生产部署 | FastAPI 托管前端静态文件 | 单进程部署，零配置 |
| 缩略图代理 | 后端 `/api/thumbnail` 统一代理 | 解决 Mixed Content 和各平台 CDN 防盗链 |
| 平台兼容层 | monkey-patch yt-dlp 提取器 | 不修改 yt-dlp 源码，升级安全；对业务代码透明 |
| 分P合并 | 逐P独立子目录下载 + ffmpeg concat | `concat_playlist='always'` 同名覆盖问题；手动合并更可靠 |
| AI 流式输出 | `asyncio.Queue` + `call_soon_threadsafe` | 跨线程实时推送，每 token 即时送达；避免 `list()` 缓冲所有数据后再发送 |
| B 站字幕获取 | 优先 Bilibili CC 字幕 API (`dm/view`)，降级 yt-dlp | yt-dlp 对 Bilibili 只返回弹幕 XML；CC 字幕 API 可获取真实人工/自动字幕 |
| AI SDK 端点 | Anthropic 兼容端点 (`/anthropic`) | 支持流式 MessageStream（thinking + text 双轨）；OpenAI 兼容端点无此能力 |
| Markdown 渲染 | `marked` + `DOMPurify` + `v-html` | 轻量无框架依赖；XSS 防护；AI 输出的结构化内容可读性大幅提升 |

## 7. 平台兼容层

部分平台在服务器环境下存在特殊限制，通过 monkey-patch 解决，代码位于 `core/downloader.py` 底部，模块加载时自动执行。

### B 站分P视频

```
问题：多P视频默认被 yt-dlp 当作 playlist 处理，导致解析慢/失败/只有一个清晰度
解决：
  1. 解析和下载均加 noplaylist=True，只处理当前P
  2. 解析后调用 api.bilibili.com/x/player/pagelist 获取完整分P列表
  3. 前端展示分P列表（checkbox 多选）：
     - 点击 checkbox：勾选/取消，用于批量下载
     - 分P信息区域为纯展示（<div>），不触发页面刷新，避免手机误触
     - "全选/取消全选"按钮
     - "下载选中(N)"：只下载勾选的P，合并为一个文件
     - "合并下载全部"：下载所有P并合并
     - 主下载按钮：选中分P时下载选中的；未选中时下载当前分P
  4. _download_concat_parts(selected_indices) 逐P下载到独立子目录，
     再用 ffmpeg -f concat -c copy 合并为 merged.mp4
     （不用 concat_playlist='always'，因为同名文件会互相覆盖）

文件大小估算：
  - yt-dlp 的 filesize/filesize_approx 对 Bilibili 不准，改用码率估算
  - 公式：filesize = tbr(kbps) × 1000 / 8 × 全视频时长(秒)
  - 视频流格式（is_video_only）下载时会自动合并 +bestaudio，估算时需加上最佳音频流码率
  - 关键：info['duration'] 只是 P1 时长，必须用分P列表时长之和作为总时长
  - 分P大小估算：用已有 filesize 的格式的 filesize / duration 得到每秒字节数，再乘以分P时长
  - 格式列表中最高分辨率格式自动标记为"推荐"，不再有固定的"最佳画质"选项
  - 前端根据选中分P的时长比例动态调整显示大小
```

### B 站（BiliBiliIE）

```
问题 1：云服务器 IP 访问 bilibili.com 网页返回 412
解决：拦截 _download_webpage_handle，412 时改调 api.bilibili.com/x/web-interface/view
      将返回数据构造为含 window.__INITIAL_STATE__ 的假网页，提取器正常继续

问题 2：WBI 签名接口未登录限制 480p
解决：覆盖 _download_playinfo，未登录时改用非 WBI 接口 + try_look=1，可获取 1080p/720p
```

### 抖音（DouyinIE）

```
问题：web API 需要 JS 生成的 s_v_web_id cookie，服务器无法获取（yt-dlp 自身 TODO）
解决：覆盖 _real_extract，web API 报 cookie 错误时降级到 api.amemv.com 移动端 API
      使用 Android 设备参数请求，无需任何 cookie
```

### 短链解析（routes.py `extract_url`）

```
b23.tv       → HTTP GET 取 Location header → 提取 BV ID → bilibili.com/video/BVxxx
v.douyin.com → HTTP GET 取 Location header → 提取视频 ID → douyin.com/video/{id}
bilibili.com → 自动补全为 www.bilibili.com（无 www 时 yt-dlp 返回 403）
手机分享文本  → 正则提取第一个 URL → 去除末尾标点
```

### 缩略图代理（routes.py `/api/thumbnail`）

```
前端统一使用 /api/thumbnail?url=... 代理所有缩略图
代理根据 CDN 域名后缀匹配 Referer：
  xhscdn.com      → https://www.xiaohongshu.com/
  hdslb.com       → https://www.bilibili.com/
  bilivideo.com   → https://www.bilibili.com/
  douyinvod.com   → https://www.douyin.com/
  365yg.com       → https://www.douyin.com/
  ytimg.com       → https://www.youtube.com/
  （其余不带 Referer）
```



## 8. 目录结构

```
videomind/
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── requirements.txt        # Python 依赖
│   ├── .env                    # 环境变量（DEEPSEEK_API_KEY 等，不提交到 git）
│   ├── core/
│   │   ├── downloader.py       # yt-dlp 封装
│   │   ├── summarizer.py       # DeepSeek AI 总结模块（含 B 站 CC 字幕提取、字幕清洗、流式/非流式 prompt）
│   │   ├── summary_models.py   # AI 总结 Pydantic 模型（SummarizeRequest、SummaryResult 等）
│   │   └── models.py           # 视频下载 Pydantic 数据模型
│   ├── api/
│   │   ├── routes.py                # REST + WebSocket 路由（含 bilibili.com URL 规范化）
│   │   ├── summary_routes.py        # AI 总结路由（/api/summarize，含无字幕降级逻辑）
│   │   ├── stream_routes.py         # SSE 流式端点（/api/summarize/stream + /api/chat/stream）
│   │   └── subtitle_text_routes.py  # 字幕文本提取端点（/api/subtitle/text）
│   └── downloads/              # 下载文件输出
├── frontend/
│   ├── src/
│   │   ├── App.vue             # 主页面（含结果区内联逻辑 + 标签栏）
│   │   ├── main.js             # Vue 入口
│   │   ├── style.css           # 全局样式（CSS 变量 + Tailwind + 基础重置 + 动画）
│   │   ├── components/
│   │   │   ├── NavBar.vue          # 顶部导航栏（毛玻璃效果，品牌 + 菜单 + 按钮）
│   │   │   ├── AiSummary.vue       # AI 总结组件（流式摘要+章节大纲+思维导图+AI 问答，Markdown 渲染，含 CJK 宽度修正）
│   │   │   ├── HeroSection.vue     # Hero 区域（深色背景 + 光晕 + 输入框 + 平台标签流）
│   │   │   ├── FeaturesSection.vue # 特性展示（6 卡片 3 列，含 Pro 卡片）
│   │   │   ├── FooterSection.vue   # 页脚（品牌 + 链接 + 平台列表 + 版权）
│   │   │   ├── UrlInput.vue        # 备用（当前未使用）
│   │   │   ├── VideoInfo.vue       # 备用（当前未使用）
│   │   │   ├── FormatSelector.vue  # 备用（当前未使用）
│   │   │   ├── DownloadProgress.vue # 备用（当前未使用）
│   │   │   ├── DownloadHistory.vue  # 备用（当前未使用）
│   │   │   └── HelloWorld.vue       # 备用（Vite 脚手架默认组件，当前未使用）
│   │   └── composables/
│   │       ├── useDownloader.js    # 下载 API/WebSocket 对接（核心状态管理）
│   │       ├── useSummary.js       # AI 总结状态管理（SSE 流式接收、Markdown 渲染、字幕文本获取）
│   │       └── useChat.js          # AI 问答状态管理（流式对话、历史记录）
│   ├── vite.config.js          # Vite + Tailwind + 代理
│   └── index.html
├── docs/                       # 项目文档
├── image/                      # 设计参考图
├── start.bat                   # 一键启动脚本
└── README.md
```