# 变更记录

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