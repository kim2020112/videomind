# VideoMind — AI 视频学习助手

将任何视频转化为结构化知识：AI 总结、学习笔记、思维导图、智能问答。

## 核心功能

- **AI 智能总结**：自动提取字幕，大模型生成精炼摘要，快速把握核心内容
- **多P视频 AI 总结**：B站多P视频按分P独立总结，分P列表垂直滚动、居中定位当前P，每P可单独触发 AI 分析
- **结构化笔记**：自动生成标题层级分明的 Markdown 笔记，支持代码块与重点高亮
- **思维导图**：提炼关键概念生成可视化导图，支持 SVG/PNG 导出
- **AI 问答**：基于视频字幕内容自由提问，AI 帮你找到答案
- **关键问答对**：自动从视频中提取关键知识点问答对，强化学习效果
- **字幕提取**：支持 SRT/VTT/TXT 格式下载，多语言翻译
- **学习历史**：自动保存每次分析结果，支持搜索、标签过滤、平台筛选、收藏、语义搜索，随时回顾已学内容
- **智能标签**：基于规则自动提取视频标签（编程语言、AI/ML、框架等），支持按标签筛选历史
- **视频下载**：保留原下载功能，支持多清晰度选择
- **用户认证**：注册登录 + 游客模式，三级权限（Guest/User/Admin），按用户隔离学习历史和标签
- **请求安全**：统一安全守卫模块，SSRF 防护 + 身份校验 + 资源归属校验，所有 API 端点强制认证
- **管理员 AI 模型配置**：管理员可在前端配置多个 AI 服务商和模型预设，支持热切换无需重启，同一服务商下多个模型共享 API Key
- **移动端适配**：响应式布局，手机浏览器可正常使用 URL 输入、AI 总结、分P选择等全部功能

## 支持平台

B站 · YouTube · 抖音 · 小红书 · TikTok

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | Vue 3 + Vite + Tailwind CSS |
| 后端 | FastAPI + Python |
| AI | DeepSeek API（Anthropic 兼容协议，可切换） |
| 存储 | SQLite + ChromaDB |
| 视频引擎 | yt-dlp |

## 快速开始

### 环境要求

- Python >= 3.9
- Node.js >= 18
- FFmpeg

### 安装

```bash
cd backend && pip install -r requirements.txt
cd frontend && npm install
```

### 配置

编辑 `backend/.env`：

```env
AI_API_KEY=your_api_key
AI_BASE_URL=https://api.deepseek.com/anthropic
AI_MODEL=deepseek-v4-flash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_admin_password
GUEST_SECRET=random_secret_key
```

### 启动

```bash
# 开发模式
cd backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
cd frontend && npm run dev

# 生产模式（推荐使用 systemd 管理后端进程，限制内存防止 OOM）
cd frontend && npm run build
cd ../backend && python main.py  # FastAPI 托管前端静态文件
```

### 访问

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:5173 |
| API 文档 | http://localhost:8000/docs |

## 架构

```
用户输入 URL → 字幕获取 → AI 处理流水线 → 知识存储
                 │              │               │
          B站CC(按cid)   摘要/笔记/导图/问答对     SQLite + ChromaDB
          yt-dlp/Whisper     │              │
          多P按P独立获取  core/pipeline/    用户认证/隔离
          无字幕不降级P1   流式 SSE 推送（渐进式生成）
```

## API 端点

| 端点 | 说明 |
|------|------|
| `POST /api/parse` | 解析视频信息 |
| `GET /api/video/stream` | 视频流代理（支持 Range，在线播放） |
| `GET /api/video/refresh` | 刷新过期视频直链 |
| `GET /api/thumbnail` | 缩略图代理（防盗链） |
| `POST /api/summarize` | AI 视频总结（同步） |
| `POST /api/summarize/stream` | AI 总结（SSE 流式） |
| `POST /api/chat/stream` | AI 问答（SSE 流式） |
| `POST /api/qa/stream` | AI 关键问答对生成（SSE 流式） |
| `GET /api/subtitle` | 下载字幕文件 |
| `GET /api/subtitle/text` | 获取字幕纯文本 |
| `GET /api/subtitle/translate` | 翻译字幕 |
| `POST /api/download` | 创建下载任务 |
| `WS /ws/download/{task_id}` | WebSocket 下载进度 |
| `GET /api/history` | 学习历史列表 |
| `GET /api/history/stats` | 学习统计数据 |
| `GET /api/history/tags` | 标签列表 |
| `GET /api/search` | 语义搜索 |
| `POST /api/auth/register` | 用户注册 |
| `POST /api/auth/login` | 用户登录 |
| `GET /api/auth/me` | 当前用户信息 |
| `GET /api/auth/usage` | 轻量用量查询 |
| `GET /api/admin/ai-config` | 获取 AI 服务商/模型配置（管理员） |
| `POST /api/admin/ai-config/providers` | 新增服务商（管理员） |
| `PUT /api/admin/ai-config/providers/{pid}` | 更新服务商（管理员） |
| `DELETE /api/admin/ai-config/providers/{pid}` | 删除服务商（管理员） |
| `POST /api/admin/ai-config/providers/{pid}/test` | 测试服务商连通性（管理员） |
| `POST /api/admin/ai-config/providers/{pid}/models` | 新增模型（管理员） |
| `PUT /api/admin/ai-config/providers/{pid}/models/{mid}` | 更新模型（管理员） |
| `DELETE /api/admin/ai-config/providers/{pid}/models/{mid}` | 删除模型（管理员） |
| `POST /api/admin/ai-config/switch` | 切换激活模型（管理员） |
| `POST /api/admin/ai-config/test` | 测试连通性（管理员） |

## 注意事项

- 基于 yt-dlp 开源项目，仅供学习使用
- 请尊重版权，仅处理有权访问的内容
- 生产部署建议用 systemd 限制 Python 进程内存（参考 `CLAUDE.md` 中的资源管理经验），避免 ChromaDB + uvicorn 内存雪崩
