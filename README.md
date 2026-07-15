# VideoMind

VideoMind 是一个将在线视频转化为结构化学习资料的 Web 应用。它支持视频解析与下载、字幕获取、AI 总结、学习笔记、思维导图、关键问答和个人学习历史。

## 主要能力

- 解析多平台视频信息并提供下载选项。
- 优先使用平台原生字幕；没有字幕时可选用本地 Whisper 转录。
- B 站字幕区分“可用、明确没有、暂时不可用”，接口限流或临时失败不会误启动 Whisper 或生成简介总结。
- B 站多分 P 视频按用户所选分 P 的精确 `cid` 获取字幕。
- B 站短链在解析后统一为规范视频 URL；转录限制与 ETA 使用所选分 P 时长，而不是整套视频总时长。
- B 站确实没有可下载字幕时才进入 Whisper；后台任务复用解析阶段取得的音频直链，避免重复抓取视频页面。
- 基于字幕生成摘要、笔记、思维导图和关键问答。
- 保存标签、收藏、历史状态，并按当前身份标记已经学习且有 AI 缓存的分 P。
- 登录会话按浏览器窗口隔离，管理员和普通用户可以在不同窗口同时使用。
- Whisper 任务持久化到 SQLite，由后端调度短生命周期子进程执行。
- 已知平台的旧 HTTP 缩略图地址会在代理入口升级为 HTTPS。

## 技术栈

- 前端：Vue 3、Vue Router、Vite、Tailwind CSS、Vitest。
- 后端：FastAPI、Uvicorn、Python `unittest`。
- 数据与后台任务：SQLite WAL。
- 视频处理：yt-dlp、FFmpeg。
- AI：Anthropic 兼容接口。
- 本地转录：Faster-Whisper（可选）。

## 环境要求

- Python 3.10+
- Node.js 20.19+（20 LTS）或 22.12+
- FFmpeg（下载合并和 Whisper 需要）
- Faster-Whisper 与本地模型（仅本地转录需要）

缺少 AI、Whisper 或 FFmpeg 时，应用仍可启动；对应能力会通过 `/api/capabilities` 安全关闭。

## 本地开发

从仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，至少配置有效的 AI API Key。公开提供访客能力时，还必须把 `GUEST_SECRET` 改为随机长字符串。

分别启动后端与前端：

```bash
# 终端 1：后端 API
.venv/bin/python -m uvicorn main:app --app-dir backend --reload --host 0.0.0.0 --port 8000

# 终端 2：前端开发服务器
npm --prefix frontend run dev -- --host 0.0.0.0
```

开发页面为 `http://localhost:5173`，API 文档为 `http://localhost:8000/docs`。Vite 会把 `/api` 和 `/ws` 转发到后端。

## 生产运行

构建前端后，FastAPI 会自动挂载 `frontend/dist`，并为 `/workspace`、`/history` 和历史详情深链提供 SPA 回退：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

项目不提交环境专属的 systemd、反向代理和备份脚本。部署时应自行配置进程守护、HTTPS 与 SQLite 备份，并通过 `DB_PATH`、`AI_CONFIG_PATH`、`TEMP_DIR`、`DOWNLOAD_DIR` 和 `WHISPER_MODELS_DIR` 将运行数据放到持久化目录。后台调度器与 SQLite 状态位于同一进程，生产环境使用单个 Uvicorn worker。

## 验证

```bash
# 后端测试
python3 -B -m unittest discover -s backend/tests -v

# 前端测试与生产构建
npm --prefix frontend run test:run
npm --prefix frontend run build

# Python 编译和补丁格式
python3 -m compileall -q backend
git diff --check
```

健康与能力端点：

- `GET /api/health/live`：进程存活检查。
- `GET /api/health/ready`：SQLite 与运行目录可写检查。
- `GET /api/capabilities`：AI、Whisper、FFmpeg 和访客能力状态。

## 文档

- [架构说明](docs/architecture.md)
- [开发指南](docs/development.md)

请仅处理有权访问的视频内容，并遵守适用的平台规则与版权要求。
