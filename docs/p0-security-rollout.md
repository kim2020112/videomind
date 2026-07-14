# P0 安全补丁发布手册

本文只覆盖 P0 媒体代理、Bearer-only 认证和 generate-then-swap。发布会使全部现有 Session 失效，用户需要重新登录。

## 发布前

1. 确认工作树对应的后端、前端单测和生产构建均通过。
2. 记录当前提交、服务配置、`DB_PATH` 和数据库文件大小。
3. 阻止新写入或停止后端服务，然后对 SQLite 做一致性备份。

后端停止后可直接复制主库；若不能停服，使用 SQLite 在线备份命令，不要只复制 WAL 模式下的主文件。

```bash
sqlite3 "$DB_PATH" ".backup '$DB_PATH.p0-backup'"
sqlite3 "$DB_PATH.p0-backup" "PRAGMA integrity_check;"
```

`integrity_check` 必须返回 `ok`。保留原数据库、`-wal` 和 `-shm` 文件，直到 P0 验收完成。

## 发布

1. 部署后端和已构建前端。
2. 启动单个 Uvicorn worker；启动过程会运行 Session 失效迁移。
3. 确认迁移版本只存在一条，旧 Session 数量为零。

```sql
SELECT COUNT(*) FROM schema_migrations
WHERE version = '20260713_invalidate_legacy_auth_sessions';

SELECT COUNT(*) FROM sessions;
```

预期结果分别为 `1` 和 `0`。

## 代码级检查

```bash
pytest -q backend/tests
npm --prefix frontend run test:run
npm --prefix frontend run build
git diff --check
```

## 手工验收

按以下顺序在浏览器中验收，自动化代理不代替此步骤：

1. 旧窗口被要求重新登录，登录后刷新仍保持当前窗口身份。
2. Cookie 或普通 HTTP `session_id` 查询参数不能认证，`/api/auth/me` 不返回 `session_id`。
3. 已知平台缩略图可显示，视频可播放并 seek；未知平台不显示代理缩略图或在线播放入口。
4. 强制重生成制造失败后，旧摘要、字幕、视频记录和另一用户的缓存仍可读取，额度不增加。
5. 字幕重转录失败后，旧 Whisper 字幕仍可读取。

## 回滚约束

开放写入前可以恢复发布前备份。开放写入后禁止用旧备份覆盖新数据，只允许前向修复；否则会丢失新用户、历史、任务和生成结果。

P0 修复的是账号接管和共享缓存破坏风险，不应通过重新启用 Cookie fallback、通配 CORS、宽松代理域名或预删除缓存来回滚。若发布后发现问题，优先回滚前端或停止受影响入口，并以前向补丁修复后端。
