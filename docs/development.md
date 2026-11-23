# 开发指南

## 初始化

环境要求：Python 3.10+、Node.js 20.19+（20 LTS）或 22.12+；FFmpeg 与 Faster-Whisper 为可选能力。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
cp backend/.env.example backend/.env
```

生产环境可安装 `backend/requirements.txt`；本地开发和测试使用 `backend/requirements-dev.txt`。需要较轻的环境时，可先安装 `backend/requirements-core.txt` 和 `backend/requirements-ai.txt`，暂不安装 `backend/requirements-whisper.txt`。

## 配置

常用环境变量：

| 变量 | 用途 |
|---|---|
| `AI_API_FORMAT` | `.env` 兜底协议，取值为 `anthropic` 或 `openai` |
| `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` | `.env` 兜底连接的凭据、地址和模型；有管理员运行时连接时由其覆盖 |
| `FEATURE_AI`、`FEATURE_WHISPER` | 显式关闭可选功能 |
| `WHISPER_MODEL`、`WHISPER_MODELS_DIR` | 默认模型名称与本地模型根目录 |
| `WHISPER_MODEL_PATH` | 可选的完整本地模型目录；复用其他位置已有的 Faster-Whisper 模型时设置，无需重新下载 |
| `WHISPER_MAX_DURATION` | 转录时长上限，单位为秒。默认 `0` 表示不限时 |
| `BILIBILI_COOKIE` | 可选的 B 站登录凭据；默认仅登录验证、列表和字幕目录接口使用 |
| `BILIBILI_USE_ACCOUNT_COOKIE` | 默认 `true`；设为 `false` 则自动请求完全匿名，不会解除额度或冷却 |
| `ADMIN_USERNAME`、`ADMIN_PASSWORD` | 可选管理员初始化 |
| `GUEST_SECRET` | 访客签名；保持默认值时访客入口关闭 |
| `AI_CACHE_KEEP` | AI 缓存软上限（按视频计，默认 500）；历史和收藏中的成果受保护，可超过此值，清理不删除字幕与视频记录 |
| `AI_REQUEST_TIMEOUT`、`AI_STREAM_TIMEOUT` | AI 请求超时与流式空闲超时（秒） |
| `DB_PATH`、`AI_CONFIG_PATH` | 持久化数据位置 |
| `TEMP_DIR`、`DOWNLOAD_DIR`、`WHISPER_MODELS_DIR` | 运行目录 |
| `CORS_ORIGINS` | 逗号分隔的精确跨域来源；留空仅同源，`*` 不生效 |

不要提交 `backend/.env`、数据库、AI 配置、模型或真实 Cookie。

## AI 连接配置

管理员页面通过 `/api/admin/ai-config` 管理持久化在 `AI_CONFIG_PATH` 的运行时连接。版本 3 配置以 `connections` 保存每个连接的协议、规范化 Base URL、模型发现地址、模型目录和 `primary_model_id`；响应中的 API Key 会脱敏。

模型将来源/发现状态（`manual`、`available`、`not_returned`）与连通性测试状态（`untested`、`passed`、`failed`）分开保存。刷新目录不会删除手动模型或覆盖既有测试结果。第一个新连接会成为全局生效连接；编辑非当前连接只更新它自己的主力模型。切换模型会在同一保存操作中更新连接主力模型与全局 active 模型。

旧的单模型或服务商分组配置会在读取时归一化为版本 3，并在下一次成功保存时写回新结构。没有运行时连接时，管理员会看到只读的 `.env` 兜底连接。

## 启动

使用两个终端：

```bash
# 后端
.venv/bin/python -m uvicorn main:app --app-dir backend --reload --host 0.0.0.0 --port 8083

# 前端
npm --prefix frontend run dev -- --host 0.0.0.0
```

访问 `http://localhost:5173`。Vite 将 `/api` 和 `/ws` 代理到 `http://127.0.0.1:8083`。

需要模拟生产静态托管时：

```bash
npm --prefix frontend run build
npm --prefix frontend run preview -- --host 0.0.0.0 --port 5173
```

Preview 继续把 `/api` 和 `/ws` 代理到后端，但不注入 Vite HMR 客户端，适合需要独立 `5173` 监听端口的长期运行环境。不要用开发服务器承载用户会话；HMR WebSocket 断线重连会触发整页刷新。也可以让 FastAPI 直接托管已构建的 `frontend/dist`。

systemd、反向代理和备份策略属于部署环境，不在仓库内维护模板。修改已由 systemd 托管的后端后，应重启对应服务；修改 Preview 托管的前端后，应重新构建并重启前端服务。

## 代码位置

| 目标 | 主要位置 |
|---|---|
| 应用启动与健康检查 | `backend/main.py`、`backend/api/health_routes.py` |
| 认证与授权 | `backend/api/auth_routes.py`、`backend/api/security.py`、`backend/core/auth.py` |
| 视频解析与下载 | `backend/core/downloader.py`、`backend/api/routes.py` |
| 字幕与转录 | `backend/core/pipeline/subtitle.py`、`backend/core/summarizer.py`、`backend/workers/` |
| AI 流水线与运行时连接 | `backend/api/stream_routes.py`、`backend/core/pipeline/`、`backend/core/ai_config.py`、`backend/core/text_client.py`、`backend/prompts/` |
| 博主订阅与批量生成 | `backend/api/blogger_routes.py`、`backend/core/blogger/`、`frontend/src/components/BloggersPage.vue`、`frontend/src/components/BloggerDetailPage.vue` |
| 独立字幕与学习任务 | `backend/api/learning_routes.py`、`backend/core/learning.py`、`frontend/src/composables/useLearning.js` |
| 内容标签与列表定位 | `backend/core/content_state.py`、`backend/core/blogger/learned.py`、`frontend/src/components/ContentBadges.vue`、`frontend/src/utils/bloggerNavigation.js` |
| 缓存与历史 | `backend/core/cache.py`、`backend/api/knowledge_routes.py` |
| 前端路由与编排 | `frontend/src/router.js`、`frontend/src/App.vue` |
| 统一工具按钮与分页 | `frontend/src/toolbars.css`、`frontend/src/components/ListPagination.vue`、`frontend/src/components/AiSummary.vue` |
| 前端组件与状态 | `frontend/src/components/`、`frontend/src/composables/` |

## 测试

```bash
# 后端 unittest 套件
env PYTHONPATH=backend .venv/bin/python -B -m unittest discover -s backend/tests -v

# 后端完整回归（包含 pytest 与 unittest 用例）
env PYTHONPATH=backend .venv/bin/python -B -m pytest backend/tests -q

# 前端全部测试
npm --prefix frontend run test:run

# 生产构建
npm --prefix frontend run build

# Python 编译与补丁检查
python3 -m compileall -q backend
git diff --check
```

测试必须使用临时数据库，不得读写开发或生产数据库。涉及缓存、身份、后台任务或路由的修复应补回归测试，并先确认测试能复现旧行为。

博主列表回归需覆盖：字幕浏览后返回出现“有字幕”、生成部分模块后显示“已整理 · n/4”、失败重试保留已有标记、工作台刷新和浏览器后退恢复原视频/分 P、筛选后原视频移出时的提示，以及访客/用户之间的状态隔离。补充验证：只读字幕不进入学习历史、清空后标签/筛选计数同步消失且刷新不自动恢复、显式获取可恢复、其他身份/相邻分 P/已有 AI 资料不受影响，以及旧库新增 `subtitle_cleared` 列的兼容迁移。浏览器验收还应覆盖桌面/平板/手机无横向溢出、内层卡片不超出容器，导图加载期间返回不产生异常。

分页回归需覆盖：深页冷返回仅一次视频请求；10/20/50 条切换、跳页、筛选重置、每页数量 URL 优先及身份偏好隔离；缓存 LRU 淘汰、慢网络下先展示原页且后台刷新不重复滚动、旧请求晚到不覆盖新页、展开分 P 恢复、同步后锚点移动和删除后页码越界。UI 回归需检查长文下固定工具栏、手机底部返回与任务浮层/键盘/安全区避让、字幕各按钮普通/悬停/禁用/聚焦状态一致、已有内容生成中可复制导出、问答全部展开和清空字幕后仍能阅读问答，以及导图全屏内退出按钮。

## 运行排错

```bash
curl http://127.0.0.1:8083/api/health/live
curl http://127.0.0.1:8083/api/health/ready
curl http://127.0.0.1:8083/api/capabilities
```

- `/api/health/live` 失败：检查 Uvicorn 进程和端口。
- `/api/health/ready` 返回 503：检查 SQLite、临时目录和下载目录权限。
- 前端 5173 无法访问：检查 Vite Preview 进程、构建产物、监听地址和防火墙。
- Whisper 不可用时，先核对运行中服务的 `/api/capabilities` 和任务提示。检查服务所用 Python 环境是否已安装 `backend/requirements-whisper.txt` 中的依赖、FFmpeg 是否在服务的 `PATH` 中，以及模型目录内是否有 `config.json`、`model.bin`、`tokenizer.json` 和 `vocabulary.txt`。`backend/.env` 由后端按固定路径加载，服务环境变量优先。改动配置后重启服务再核对能力。
- B 站字幕暂时不可用时，查看后端日志中的平台错误码。工作台可提示重试或请求确认转录，具体取决于运行时能力和访问保护。
- 博主目录同步报 `login`：平台要求有效登录，自动任务已暂停；优先在官方客户端访问，不反复提交账号 Cookie。
- 解析或下载报 HTTP 412 时，对应功能冷却通常为 10～60 分钟。API 返回 HTTP 429 时可触发全局冷却。API 默认请求间隔为 5 秒，上限为每分钟 30 次、每小时 120 次、每天 600 次。工作台每次字幕操作最多 5 次可按不低于 0.25 秒的间隔发出，继续共用这些额度。见 [访问保护](bilibili-access.md)。
- B 站无 CC 后转录出现 `HTTP 412`：确认解析结果含 `audio_stream_url`，并确认 worker 命令收到 `--audio-url`。旧 `video_info_cache` 没有该字段时应先刷新解析，不要直接让 worker 再次抓取视频页面。
- 分 P 状态异常：同时检查精确 URL、`url_hash`、当前身份历史归属及已保存的有效字幕/模块，失败任务不应抹掉已有资料状态；不要把共享视频指纹当成分 P 唯一键。
- 分 P 转录 ETA 异常：确认 canonical URL 保留 `p` 参数，并从 `parts` 中读取所选分 P 时长，而不是全集总时长。

## Git 与文档

- 不提交运行数据、构建产物、密钥、模型和会话交接文件。
- 临时规划、发现和进度文档在任务结束后直接删除；本地 `handoff.md` 只用于跨会话交接并由 `.gitignore` 排除。
- 长期行为变化只更新 README、架构说明、开发指南和环境变量示例，避免保留完成后即过时的实施计划。
- 提交前逐文件暂存，避免把运行数据或本地交接文件混入提交。
