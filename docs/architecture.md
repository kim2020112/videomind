# 方案设计文档

## 1. 技术选型

| 层次 | 技术 | 选型理由 |
|------|------|----------|
| 前端框架 | Vue 3 + Vite | 轻量、快速、生态成熟 |
| CSS 框架 | Tailwind CSS 4 | 原子化 CSS，快速构建 UI |
| 后端框架 | FastAPI (Python) | 异步支持好、自动生成 API 文档、WebSocket 原生支持 |
| 视频引擎 | yt-dlp | GitHub 19w+ Star，支持 1800+ 平台，Python 库直接调用 |
| 进度推送 | WebSocket | 实时双向通信，低延迟 |
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
| POST | `/api/download` | 创建下载任务 | `{"url": "...", "format_id": "best"}` | `{"task_id": "...", "ws_url": "..."}` |
| GET | `/api/files/{task_id}` | 下载文件 | - | 文件流 |
| GET | `/api/downloads` | 已完成任务列表 | - | `{"downloads": [...]}` |

### 4.2 WebSocket

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

**VideoInfo**：视频元数据
- title, webpage_url, duration, thumbnail, description, uploader, view_count, extractor, formats[], parts[]

**FormatOption**：格式选项
- format_id, ext, resolution, height, fps, vcodec, acodec, filesize, is_audio_only, is_video_only, is_combined

**VideoPart**：分P条目（仅 B 站多P视频）
- index（P序号）, title（分P标题）, duration

**ProgressData**：进度数据
- status, percent, speed, eta, downloaded, total, file_path, error

## 5. 前端组件树

```
App.vue
├── NavBar.vue                 # 顶部导航（Logo + 导航菜单 + 登录/立即使用按钮）
├── HeroSection.vue            # Hero 区域（大标题 + 副标题 + 输入框 + 解析按钮 + 平台图标）
├── results section (内联)     # 解析结果区域（仅在有结果或错误时显示）
│   ├── video-card             # 视频信息卡片（封面/标题/时长/平台 + 格式选择 + 下载按钮 + 进度条）
│   └── history-card           # 下载历史列表
└── FeaturesSection.vue        # 特性展示区（4 个特性卡片，一行排列）
```

**设计说明：**
- 输入框和解析按钮内嵌在 `HeroSection.vue` 中，通过 props 传入 `url`、`loading` 状态和事件回调
- 视频信息、格式选择、下载进度、下载历史均在 `App.vue` 的 results section 中内联实现，不拆分为独立组件
- `FeaturesSection.vue` 为纯展示组件，无状态

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
     - 点击标题区域：重新解析该P（切换预览格式）
     - "全选/取消全选"按钮
     - "下载选中(N)"：只下载勾选的P，合并为一个文件
     - "合并下载全部"：下载所有P并合并
  4. _download_concat_parts(selected_indices) 逐P下载到独立子目录，
     再用 ffmpeg -f concat -c copy 合并为 merged.mp4
     （不用 concat_playlist='always'，因为同名文件会互相覆盖）
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
b23.tv   → HTTP GET 取 Location header → 提取 BV ID → bilibili.com/video/BVxxx
v.douyin.com → HTTP GET 取 Location header → 提取视频 ID → douyin.com/video/{id}
手机分享文本 → 正则提取第一个 URL → 去除末尾标点
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
free-video-downloader/
├── backend/
│   ├── main.py                 # FastAPI 入口
│   ├── requirements.txt        # Python 依赖
│   ├── core/
│   │   ├── downloader.py       # yt-dlp 封装
│   │   └── models.py           # Pydantic 数据模型
│   ├── api/
│   │   └── routes.py           # REST + WebSocket 路由
│   └── downloads/              # 下载文件输出
├── frontend/
│   ├── src/
│   │   ├── App.vue             # 主页面（含结果区内联逻辑）
│   │   ├── main.js             # Vue 入口
│   │   ├── style.css           # 全局样式（Tailwind + 基础重置）
│   │   ├── components/
│   │   │   ├── NavBar.vue          # 顶部导航栏（品牌 + 菜单 + 按钮）
│   │   │   ├── HeroSection.vue     # Hero 区域（含输入框和解析按钮）
│   │   │   ├── FeaturesSection.vue # 特性展示（4 卡片一行）
│   │   │   ├── UrlInput.vue        # 备用（当前未使用）
│   │   │   ├── VideoInfo.vue       # 备用（当前未使用）
│   │   │   ├── FormatSelector.vue  # 备用（当前未使用）
│   │   │   ├── DownloadProgress.vue # 备用（当前未使用）
│   │   │   └── DownloadHistory.vue  # 备用（当前未使用）
│   │   └── composables/
│   │       └── useDownloader.js    # API/WebSocket 对接（核心状态管理）
│   ├── vite.config.js          # Vite + Tailwind + 代理
│   └── index.html
├── docs/                       # 项目文档
├── image/                      # 设计参考图
├── start.bat                   # 一键启动脚本
└── README.md
```