# 开发指南

## 初始化

环境要求：Python 3.10+、Node.js 20.19+（20 LTS）或 22.12+；FFmpeg 与 Faster-Whisper 为可选能力。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
cp backend/.env.example backend/.env
```

需要较轻的环境时，可先安装 `backend/requirements-core.txt` 和 `backend/requirements-ai.txt`，暂不安装 `backend/requirements-whisper.txt`。

## 配置

常用环境变量：

| 变量 | 用途 |
|---|---|
| `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` | 外部 AI 服务 |
| `FEATURE_AI`、`FEATURE_WHISPER` | 显式关闭可选功能 |
| `BILIBILI_COOKIE` | 可选的 B 站字幕 Cookie；留空时使用匿名设备 Cookie |
| `ADMIN_USERNAME`、`ADMIN_PASSWORD` | 可选管理员初始化 |
| `GUEST_SECRET` | 访客签名；保持默认值时访客入口关闭 |
| `DB_PATH`、`AI_CONFIG_PATH` | 持久化数据位置 |
| `TEMP_DIR`、`DOWNLOAD_DIR`、`WHISPER_MODELS_DIR` | 运行目录 |
| `CORS_ORIGINS` | 逗号分隔的跨域来源 |

不要提交 `backend/.env`、数据库、AI 配置、模型或真实 Cookie。

## 启动

使用两个终端：

```bash
# 后端
.venv/bin/python -m uvicorn main:app --app-dir backend --reload --host 0.0.0.0 --port 8000

# 前端
npm --prefix frontend run dev -- --host 0.0.0.0
```

访问 `http://localhost:5173`。Vite 将 `/api` 和 `/ws` 代理到 `http://127.0.0.1:8000`。

需要模拟生产静态托管时：

```bash
npm --prefix frontend run build
.venv/bin/python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

systemd、反向代理和备份策略属于部署环境，不在仓库内维护模板。修改已由 systemd 托管的后端后，应重启对应服务；前端 Vite 开发服务会自动热更新。

## 代码位置

| 目标 | 主要位置 |
|---|---|
| 应用启动与健康检查 | `backend/main.py`、`backend/api/health_routes.py` |
| 认证与授权 | `backend/api/auth_routes.py`、`backend/api/security.py`、`backend/core/auth.py` |
| 视频解析与下载 | `backend/core/downloader.py`、`backend/api/routes.py` |
| 字幕与转录 | `backend/core/pipeline/subtitle.py`、`backend/core/summarizer.py`、`backend/workers/` |
| AI 流水线 | `backend/api/stream_routes.py`、`backend/core/pipeline/`、`backend/prompts/` |
| 缓存与历史 | `backend/core/cache.py`、`backend/api/knowledge_routes.py` |
| 前端路由与编排 | `frontend/src/router.js`、`frontend/src/App.vue` |
| 前端组件与状态 | `frontend/src/components/`、`frontend/src/composables/` |

## 测试

```bash
# 后端全部测试
python3 -B -m unittest discover -s backend/tests -v

# 前端全部测试
npm --prefix frontend run test:run

# 生产构建
npm --prefix frontend run build

# Python 编译与补丁检查
python3 -m compileall -q backend
git diff --check
```

测试必须使用临时数据库，不得读写开发或生产数据库。涉及缓存、身份、后台任务或路由的修复应补回归测试，并先确认测试能复现旧行为。

## 运行排错

```bash
curl http://127.0.0.1:8000/api/health/live
curl http://127.0.0.1:8000/api/health/ready
curl http://127.0.0.1:8000/api/capabilities
```

- `/api/health/live` 失败：检查 Uvicorn 进程和端口。
- `/api/health/ready` 返回 503：检查 SQLite、临时目录和下载目录权限。
- 前端 5173 无法访问：检查 Vite 进程、监听地址和防火墙。
- B 站字幕临时不可用：查看后端日志中的平台错误码；不要直接改成“无字幕”回退。
- 分 P 状态异常：同时检查精确 URL、`url_hash`、当前身份历史状态和非空 AI 缓存；不要把共享视频指纹当成分 P 唯一键。
- 分 P 转录 ETA 异常：确认 canonical URL 保留 `p` 参数，并从 `parts` 中读取所选分 P 时长，而不是全集总时长。

## Git 与文档

- 不提交运行数据、构建产物、密钥、模型和会话交接文件。
- 临时规划、发现和进度文档在任务结束后直接删除；本地 `handoff.md` 只用于跨会话交接并由 `.gitignore` 排除。
- 长期行为变化只更新 README、架构说明、开发指南和环境变量示例，避免保留完成后即过时的实施计划。
- 提交前逐文件暂存，避免把运行数据或本地交接文件混入提交。
