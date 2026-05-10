# 万能视频下载器

基于 yt-dlp 的万能视频下载网站，支持 1800+ 平台视频解析与下载。

## 技术栈

- **前端**：Vue 3 + Vite + Tailwind CSS
- **后端**：FastAPI + yt-dlp (Python)
- **视频引擎**：yt-dlp (GitHub 19w+ Star)

## 快速开始

### 环境要求

- Python >= 3.9
- Node.js >= 18
- FFmpeg（已加入 PATH）

### 安装依赖

```bash
cd backend && pip install -r requirements.txt
cd frontend && npm install
```

### 启动

```bash
# 方式一：一键启动（Windows）
start.bat

# 方式二：手动启动
cd backend && python -m uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

### 访问

| 服务 | 地址 |
|------|------|
| 前端页面 | http://localhost:5173 |
| 后端 API | http://localhost:8000 |
| API 文档 | http://localhost:8000/docs |

## 功能

- 粘贴视频链接，自动解析视频信息（标题、时长、封面、格式列表）
- 支持多清晰度选择（360p/720p/1080p/4K）
- 实时下载进度推送（WebSocket）
- 支持 1800+ 视频平台（YouTube、B站、TikTok、Instagram 等）

## 项目文档

详细文档见 [docs/](docs/) 目录：

| 文档 | 说明 |
|------|------|
| [需求分析](docs/requirements.md) | 项目背景、目标用户、核心需求 |
| [方案设计](docs/architecture.md) | 技术架构、API 设计、核心流程 |
| [开发指南](docs/development.md) | 环境搭建、启动方式、目录说明 |
| [变更记录](docs/changelog.md) | 版本迭代历史 |

## 注意事项

- 基于 yt-dlp 开源项目，仅供学习使用
- 请尊重版权，仅下载有权访问的内容
- 大量下载可能触发平台限速，请合理使用