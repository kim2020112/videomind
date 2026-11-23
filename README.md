# VideoMind

VideoMind 是一个将在线视频转化为结构化学习资料的 Web 应用。它支持视频解析与下载、字幕获取、AI 总结、学习笔记、思维导图、关键问答和个人学习历史。

## 主要能力

- 解析多平台视频信息并提供下载选项。
- 字幕是独立获取、阅读、复制和下载的原文资料；有完整时间轴时提供 SRT/VTT，没有则提供 TXT。
- 可清空当前身份的字幕记录和“有字幕”标记；清空后再次进入不自动获取，已有 AI 资料和其他用户的字幕不受影响。
- 学习历史只收录至少保存一种正文 AI 整理资料的视频；仅有字幕或简介摘要保留在博主列表，不进入学习历史。
- 字幕获取后默认展开；收起正文仍可复制或下载，悬停或聚焦格式按钮可查看用途说明。
- 工作台取不到平台字幕时，如果 Whisper 可用，会提供语音转录确认。遇到 B 站访问保护且没有有效音频直链时，可以按页面提示稍后重试。
- B 站多分 P 视频按用户所选分 P 的精确 `cid` 获取字幕。
- B 站短链在解析后统一为规范视频 URL；转录限制与 ETA 使用所选分 P 时长，而不是整套视频总时长。
- 确认转录后，后台任务优先复用解析阶段取得的有效音频直链，减少重复请求。
- 摘要、思维导图、学习笔记和精选问答可分别选择生成；默认全选，也可单独补生成或重试失败模块。
- 后台生成可跨页面和刷新继续；每个生成操作最多计 1 次额度，只有新资料成功保存时才计费，读取缓存和字幕提取不计费。
- 无法取得视频全文时，可单独选择根据视频简介生成摘要，结果会标明来源且不混入字幕摘要缓存。
- 管理员可在运行时配置多个 OpenAI 或 Anthropic 兼容连接，发现或手动维护模型目录、测试模型并切换业务主力模型。
- 保存标签、收藏、历史状态，并按当前身份展示分 P 的字幕缓存和已整理资料。
- 订阅 B 站 UP 主（每个用户/访客各自独立的博主列表），浏览投稿目录并批量生成学习资料；批量条目复用缓存、原子提交与额度管控。默认仅必要的列表/字幕接口使用 Cookie，目录单次最多 20 页；所有 B 站请求受统一额度和风控暂停保护，详见 [B 站访问保护](docs/bilibili-access.md)。
- 从博主视频列表进入工作区后，可直接返回原列表，并恢复搜索、整理状态/字幕筛选、页码和每页数量、展开的分 P 和原视频滚动位置；刷新工作区或浏览器后退仍可返回。
- 博主视频支持每页 10/20/50 条、页码跳转和一键回到列表顶部；返回时优先恢复原页缓存，后台更新标签。桌面返回入口固定在顶部，手机固定在底部。
- 摘要、导图、笔记、精选问答共用顶部工具栏，复制、导出、重新生成无需翻到内容底部；字幕模块按钮使用统一样式。
- 视频自动标记“有字幕”“已整理 · n/4”或“简介摘要”；多分 P 分别统计有字幕和已整理的比例。仅浏览共享缓存也会记录当前身份，不触发生成或扣额度。
- 学习历史或收藏中的 AI 成果不会因缓存数量超限被自动淘汰；缓存清理不删除字幕、视频记录或标签。
- 登录会话按浏览器窗口隔离，管理员和普通用户可以在不同窗口同时使用。
- Whisper 任务持久化到 SQLite，由后端调度短生命周期子进程执行。
- 已知平台的旧 HTTP 缩略图地址会在代理入口升级为 HTTPS。

## 技术栈

- 前端：Vue 3、Vue Router、Vite、Tailwind CSS、Vitest。
- 后端：FastAPI、Uvicorn、Python `unittest`。
- 数据与后台任务：SQLite WAL。
- 视频处理：yt-dlp、FFmpeg。
- AI：OpenAI 与 Anthropic 兼容接口，可通过管理员连接配置在运行时切换。
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
.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，至少配置有效的 `AI_API_FORMAT`（`anthropic` 或 `openai`）和 AI API Key。管理员保存运行时连接后，该连接会优先于 `.env` 兜底。公开提供访客能力时，还必须把 `GUEST_SECRET` 改为随机长字符串。

分别启动后端与前端：

```bash
# 终端 1：后端 API
.venv/bin/python -m uvicorn main:app --app-dir backend --reload --host 0.0.0.0 --port 8083

# 终端 2：前端开发服务器
npm --prefix frontend run dev -- --host 0.0.0.0
```

开发页面为 `http://localhost:5173`，API 文档为 `http://localhost:8083/docs`。Vite 会把 `/api` 和 `/ws` 转发到后端。

## 生产运行

构建前端后，FastAPI 会自动挂载 `frontend/dist`，并为 `/workspace`、`/history`、历史详情和 `/bloggers` 深链提供 SPA 回退：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8083 --workers 1
```

若部署需要在 `5173` 保留独立前端监听端口，应先构建再运行 Vite Preview：

```bash
npm --prefix frontend run build
npm --prefix frontend run preview -- --host 0.0.0.0 --port 5173
```

不要用 `npm run dev` 承载长期用户会话。开发服务器会注入 HMR WebSocket，连接中断并恢复时会自动刷新页面；Preview 只提供构建产物，不包含 HMR，并继续代理 `/api` 与 `/ws` 到后端。

项目不提交环境专属的 systemd、反向代理和备份脚本。部署时应自行配置进程守护、HTTPS 与 SQLite 备份，并通过 `DB_PATH`、`AI_CONFIG_PATH`、`TEMP_DIR`、`DOWNLOAD_DIR` 和 `WHISPER_MODELS_DIR` 将运行数据放到持久化目录。后台调度器与 SQLite 状态位于同一进程，生产环境使用单个 Uvicorn worker。

## 通用配置

管理员登录后，点击导航栏「通用配置」（手机端位于菜单内），可管理 AI 连接、模型目录、主力模型，以及 B站和抖音 Cookie。

- 新 Cookie 可先验证再保存；验证草稿不会替换已有配置。留空保存会保留原值。
- 验证区分登录有效、登录失效和暂时无法确认。抖音接口可能要求签名或触发风控，此时不会把页面可访问误报为登录有效。
- 手动保存的 Cookie 优先于 `BILIBILI_COOKIE` / `DOUYIN_COOKIE` 环境变量。抖音后续解析和下载任务立即读取新配置。B站默认仅投稿列表、字幕目录和登录状态接口使用登录态，网页与 CDN 默认匿名；`BILIBILI_USE_ACCOUNT_COOKIE=false` 可完全禁用自动任务使用账号。配置页显示当前使用状态，保存 Cookie 不会清除访问冷却。
- 平台配置默认保存在 `backend/data/platform_config.json`，可通过 `PLATFORM_CONFIG_PATH` 指定持久化路径。该文件仅限服务用户读写，未纳入版本控制；读取接口不返回 Cookie 原文。备份时应作为敏感配置处理。

## 验证

```bash
# 后端 unittest 套件
env PYTHONPATH=backend .venv/bin/python -B -m unittest discover -s backend/tests -v

# 后端完整回归（同时包含 unittest 与 pytest 用例）
env PYTHONPATH=backend .venv/bin/python -B -m pytest backend/tests -q

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

本批次访问保护、字幕一致性与工作台回归说明见 [代码评审与验收记录](docs/code-review-2026-11-15.md)。
