# 变更记录

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