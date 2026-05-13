# 变更记录

## [2.2.0] - 2026-05-12

### 修复

- **SSE 实时流式输出修复**（`api/stream_routes.py`）：
  - `_sse_generator` 原先使用 `lambda: list(_run())` 缓冲全部 AI 输出后才发送，导致前端等待 30-60s 无任何反馈
  - 改为 `asyncio.Queue` + `loop.call_soon_threadsafe`，AI 每生成一个 token 即推送至客户端
  - 新增 `progress` 事件，通知前端字幕加载完成、AI 总结开始生成

### 新增

- **B 站 CC 字幕提取**（`core/summarizer.py` `extract_bilibili_subtitle()`）：
  - 通过 `api.bilibili.com/x/v2/dm/view?type=1` 获取 CC 字幕列表（人工字幕优先于自动字幕）
  - 下载字幕 JSON 后解析分段，生成带时间戳的格式化文本和纯文本
  - 返回 `has_subtitle`、`language`、`subtitle_type`、`segments`、`full_text`、`text` 字段
  - `stream_routes.py`、`subtitle_text_routes.py`、`summary_routes.py` 的 AI 总结和字幕文本提取均优先使用此 API

- **字幕文本提取端点**（`api/subtitle_text_routes.py`）：
  - `GET /api/subtitle/text?url=...&lang=...` 返回清洗后的字幕纯文本
  - 优先 Bilibili CC 字幕 API，降级到 yt-dlp 字幕下载
  - 弹幕 XML 用专用解析器（`_clean_danmaku_xml`），其他格式走通用清洗

- **AI 问答功能**（`api/stream_routes.py` + `frontend/src/composables/useChat.js`）：
  - `POST /api/chat/stream` SSE 流式端点，基于字幕内容回答用户问题
  - 支持多轮对话历史（`history` 参数），最多保留最近 10 条
  - 前端 `AiSummary.vue` 新增聊天区域，问答结果支持 Markdown 渲染

### 优化

- **AI prompt 增强**（`core/summarizer.py`）：
  - summary 字段明确要求 Markdown 格式输出（`##` 标题、`**加粗**`、`-` 列表）
  - 思维导图层级从 3 层提升至 3-4 层，每分支最多 6 个子节点
  - 强调提取具体概念/技术/工具名称作为节点，避免"要点1"等无信息量标题
  - `summarize_from_description()` 同步应用 enhanced prompt

- **Markdown 渲染**（`frontend/src/components/AiSummary.vue`）：
  - 引入 `marked` + `dompurify`，AI 输出的摘要、流式文本、聊天消息均渲染为 HTML
  - 添加 `:deep()` CSS 样式覆盖（h1-h4、ul、ol、code、blockquote、strong、a）
  - `streamingText`、`result.summary`、`chat content` 三处改为 `v-html="renderMarkdown(...)"`

- **字幕与弹幕区分**（`core/downloader.py` + `frontend/src/components/AiSummary.vue`）：
  - `parse_info()` 过滤 `lang == 'danmaku'` 的字幕轨道，不展示在字幕列表
  - 前端字幕空状态改为"该视频无可用的字幕文本"，提示弹幕不等于字幕

### 新增依赖

- `frontend/package.json`：`marked`、`dompurify`（Markdown 渲染 + XSS 防护）、`markmap-lib`、`markmap-view`（思维导图渲染）、`@tailwindcss/typography`（Markdown 排版）

### 技术细节

- `_sse_generator` 跨线程流式实现：sync generator 在 thread executor 中运行，每 yield 一个事件就通过 `call_soon_threadsafe` 推入 `asyncio.Queue`；async generator 从队列中取出并立即 yield SSE 字节
- `extract_bilibili_subtitle()` 强制 HTTPS，解决字幕 URL 可能为 `//` 或 `http://` 开头的问题
- 弹幕 XML 解析回退到通用清洗方案（`_clean_plain_text`），而非直接失败
- AI 问答问答截取字幕后 80000 字符，保留足够上下文

---

## [2.1.0] - 2026-05-12

### 修复

- **ThinkingBlock 兼容性**（`core/summarizer.py`）：
  - DeepSeek 思考模型（如 `deepseek-v4-pro`）返回的响应中第一个 block 是 `ThinkingBlock`，无 `.text` 属性，直接访问会抛 `AttributeError`
  - 新增 `_extract_text(response)` 函数，遍历 `response.content`，跳过无 `.text` 属性的 block，返回第一个文本 block 的内容
  - 同时兼容思考模型（`ThinkingBlock` + `TextBlock`）和非思考模型（仅 `TextBlock`）

- **bilibili.com URL 规范化**（`api/routes.py`）：
  - 手机分享链接解析后可能得到 `bilibili.com`（无 www），yt-dlp 访问该域名返回 HTTP 403
  - 在 `_resolve_short_url()` 中新增正则检测，自动将 `bilibili.com/` 替换为 `www.bilibili.com/`

- **思维导图 CJK 文字溢出**（`frontend/src/components/AiSummary.vue`）：
  - 原 `measureText()` 用 `text.length * fontSize * 0.65 + 24` 估算宽度，对中文字符严重低估
  - 改为逐字符计算：CJK 字符（Unicode 范围检测）宽度 = `fontSize * 1.0`，ASCII 字符宽度 = `fontSize * 0.7`，padding 从 28 增至 32
  - `nodeGapX` 从 180 增至 220，节点间距更宽松

### 优化

- **AI 总结提速**（`backend/.env`、`core/summarizer.py`）：
  - 默认模型从 `deepseek-v4-pro`（思考模型，耗时 60s+）切换为 `deepseek-v4-flash`（非思考模型，约 11s）
  - 通过环境变量 `DEEPSEEK_MODEL` 可随时切换回思考模型

### 新增

- **无字幕视频 AI 总结降级方案**（`core/summarizer.py`、`api/summary_routes.py`）：
  - Bilibili 等平台无法通过 yt-dlp 获取自动生成字幕
  - 新增 `summarize_from_description(title, description)` 函数，基于视频标题和简介生成基础总结
  - 两种触发条件：① `info.subtitles` 为空；② 字幕内容 < 50 字符（如弹幕 XML 格式）
  - 前端展示时在总结顶部显示 `⚠️` 警告，说明总结基于简介而非字幕

### 技术细节

- `core/summarizer.py` 新增 `summarize_from_description()` 函数，`_call_deepseek()` 和多分片路径均改用 `_extract_text()` 提取文本
- `api/summary_routes.py` 新增 `from core.summarizer import summarize_from_description` 导入，路由中加入无字幕降级逻辑
- `DEEPSEEK_MODEL` 默认值改为 `deepseek-v4-flash`

---

## [2.0.0] - 2026-05-11

### 新增

- **AI 视频总结功能**：
  - 新增 `/api/summarize` 端点，输入视频 URL 即可生成 AI 总结
  - 集成 DeepSeek API（Anthropic 兼容端点），通过环境变量 `DEEPSEEK_API_KEY` 配置
  - 字幕获取策略：优先中文 → 其次英文 → 自动选择第一个可用字幕
  - 字幕清洗支持 SRT、VTT、JSON3 等多种格式
  - 长视频自动分片处理（超过 60000 字符分片摘要后再合并）

- **前端 AI 总结标签页**（`AiSummary.vue`）：
  - 视频信息卡片新增"下载 / AI 总结"标签栏切换
  - **内容摘要**：AI 生成的视频核心内容概要（200-500 字）
  - **章节大纲**：带时间戳的章节列表，展示各章节核心要点
  - **思维导图**：静态 SVG 树状图渲染，支持缩放（+/-/重置）
  - 加载状态：shimmer 骨架屏动画
  - 重新生成功能

- **免费限制机制**：
  - 每日 3 次免费 AI 总结（内存计数，重启清零）
  - 超出次数后显示 Pro 升级提示卡片

### 技术细节

- 新增 `core/summarizer.py`：DeepSeek API 调用模块，含字幕清洗、文本分片、prompt 工程、JSON 解析
- 新增数据模型：`SummarizeRequest`、`SummaryResult`、`ChapterItem`、`MindMapNode`
- 新增依赖：`anthropic>=0.40.0`（通过 DeepSeek 的 Anthropic 兼容端点调用）
- 新增 `core/summary_models.py`：AI 总结相关 Pydantic 模型（`SummarizeRequest`、`SummaryResult`、`ChapterItem`、`MindMapNode`）
- 新增 `api/summary_routes.py`：AI 总结路由，挂载到主应用
- 新增 `composables/useSummary.js`：AI 总结状态管理（`summarizeVideo()`、`summaryResult`、`isSummarizing`、`summarizeError`、`resetSummary`）
- 思维导图使用 `markmap-lib` + `markmap-view` 渲染（v2.2.0 起；v2.0.0 原为纯 SVG 渲染）

### 配置

需设置环境变量（`backend/.env`）：
- `DEEPSEEK_API_KEY`：DeepSeek API 密钥（必需）
- `DEEPSEEK_BASE_URL`：API 地址（默认 `https://api.deepseek.com/anthropic`，使用 Anthropic 兼容端点）
- `DEEPSEEK_MODEL`：模型名称（默认 `deepseek-v4-flash`，v2.1.0 起；v2.0.0 原默认为 `deepseek-chat`）

---

## [1.9.0] - 2026-05-11

### 修复

- **多P视频标题清理**（`downloader.py`）：
  - yt-dlp 对 B 站多P视频会在标题后追加 ` pNN 分P名称`，前端显示多余
  - 解析时用正则 `\s+p\d{2,}\s+.*$` 去掉该后缀，标题只保留原始视频名

- **文件大小估算算法重写**（`downloader.py`）：
  - 旧方案：直接用 yt-dlp 返回的 `filesize`/`filesize_approx` → Bilibili 数据严重不准
  - 新方案：用码率 `tbr` × 全视频时长 计算，`tbr` 是视频流真实属性，精度从 ~50% 误差降至 ~3%
  - 核心问题：yt-dlp 用 `noplaylist=True` 只解析第一P，`info['duration']` 是 P1 时长而非全视频时长
  - 修复：用分P列表时长之和作为总时长，同时修正返回给前端的 `duration` 字段
  - "最佳画质"选项：用最佳视频流码率 + 最佳音频流码率之和估算
  - 分P文件大小：用参考格式的每秒字节数 × 分P时长估算

- **清晰度区域动态大小**（`App.vue`）：
  - 选中分P后，清晰度列表中的文件大小按 `filesize ÷ 全视频时长 × 选中分P总时长` 动态调整
  - 未选中时默认显示当前分P（URL 中 `?p=` 参数）的大小
  - 标签中的单P大小描述（如 "，约 3.2 MB"）始终去掉，避免与动态总大小重复

- **下载按钮行为修正**（`App.vue`）：
  - 主下载按钮现在尊重分P选择：选中分P → 下载选中的（合并）；未选中 → 下载当前分P
  - 之前只下载第一P，忽略用户选择

### 优化

- **分P列表交互改进**（`App.vue`）：
  - 分P信息区域从 `<button>` 改为 `<div>`，点击不再触发页面刷新/重新解析
  - 只有点击左侧勾选框才触发选中操作，避免手机端误触
  - 移除 `cursor: pointer` 和 hover 变色效果

- **VideoPart 模型扩展**（`models.py`）：
  - 新增 `filesize`（估算字节数）和 `filesize_str`（人类可读大小）字段
  - 分P列表每行显示估算大小，方便用户判断下载量

---

## [1.8.0] - 2026-05-11

### 优化

- **视频信息区**（`App.vue`）：
  - 封面图增加播放图标叠加层（hover 显示）和时长角标
  - 元数据改为标签行展示：平台、上传者、播放量（万为单位自动换算）
  - 新增"查看原视频"链接（新窗口打开）

- **格式选择区**（`App.vue`）：
  - 视频/音频格式合并展示，去掉分组标签，音频格式用"仅音频"标签区分
  - 布局改为 2 列等宽网格（`grid-template-columns: repeat(2, 1fr)`），卡片更宽敞
  - 卡片内部：第一行格式名（加粗），第二行格式类型 + 文件大小（灰色小字）
  - 推荐标识从 emoji（⭐）改为 SVG 星标图标
  - 选中格式后显示详细信息栏（格式、编码、帧率、码率）
  - 移动端自动变为 1 列

- **字幕区**（`App.vue`）：
  - 字幕语言名颜色从 `#94A3B8` 提亮为 `#F1F5F9`，解决深色主题下看不清的问题
  - 分组标签（"手动字幕"/"自动生成字幕"）颜色从 `#64748B` 提亮为 `#94A3B8`
  - 翻译目标语言提示文字提亮
  - `<select>` 下拉框适配深色主题（自定义箭头 + option 背景色）

- **分P选择器**（`App.vue`）：
  - 每行增加时长显示（`mm:ss` 格式）
  - checkbox 尺寸从 18px 加大到 20px，圆角从 4px 调整为 5px

- **下载进度**（`App.vue`）：
  - 进度条增加 shimmer 动画效果（下载中状态）
  - 完成状态增加绿色对勾图标，失败状态增加红色叉号图标
  - 进度卡片边框随状态变色（完成=绿，失败=红）
  - 完成/失败状态进度条颜色同步变化

- **下载记录**（`App.vue`、`useDownloader.js`）：
  - 每条记录增加状态图标（成功/失败）
  - 增加下载时间戳（今天只显示时间，非今天显示日期+时间）
  - "保存"按钮增加下载图标
  - 历史记录数据新增 `time` 字段

---

## [1.7.0] - 2026-05-11

### 变更

- **前端 UI 深色主题改造**（全局）：
  - 整体视觉从白色浅色风格改为深蓝黑渐变主题（`#0F172A`），提升工具质感
  - 新增 CSS 变量体系（`--bg-primary`、`--text-primary`、`--accent-blue` 等），统一管理颜色
  - 字体新增 `Plus Jakarta Sans`（英文/品牌），中文继续使用 `Noto Sans SC`

- **NavBar.vue**：
  - 白色背景改为毛玻璃效果（`backdrop-filter: blur(16px)` + 半透明深色背景）
  - 文字颜色适配深色主题

- **HeroSection.vue**：
  - 标题改为"SaveAny 视频下载器"，品牌名用蓝青渐变色突出
  - 副标题精简为"粘贴链接，一键下载高清视频"
  - 按钮文案从"解析视频"改为"免费下载"
  - 新增信任标签行：无需注册 · 完全免费 · 支持 4K
  - 平台展示从 4 个静态圆形图标改为 10 个横向标签流，国内平台优先排列（B站、抖音、小红书、快手、微博、西瓜视频在前）
  - 背景新增蓝色光晕效果（`radial-gradient`）
  - 输入框 placeholder 更新为"粘贴视频链接，支持 B站、抖音、小红书、YouTube 等平台"

- **App.vue（Results 区域）**：
  - 所有卡片、按钮、进度条、字幕区域适配深色主题
  - 卡片使用半透明背景 + 毛玻璃边框（`backdrop-filter: blur(12px)`）
  - 进度条改为蓝青渐变

- **FeaturesSection.vue**：
  - 4 个现有卡片文案优化，突出具体数字和国内平台覆盖
  - 新增 2 个 Pro 专属卡片：字幕翻译、批量下载（带粉色 Pro badge）
  - 布局从 4 列改为 3 列（6 卡片 = 2 行）
  - 背景色改为 `var(--bg-secondary)`，与 Hero 区域形成层次

- **FooterSection.vue**（新增）：
  - 品牌区 + 产品/支持/法律三组链接
  - 支持平台列表（国内平台优先排列）
  - 版权信息

### 设计决策

- 目标用户以国内为主（B站、抖音、小红书等），平台展示国内优先
- 深色主题更符合年轻用户审美，提升"专业工具"质感
- Pro 卡片提前布局，为后续付费功能做视觉铺垫

---

## [1.6.0] - 2026-05-11

### 新增

- **字幕提取与翻译**：
  - 解析视频时自动获取可用字幕列表（手动字幕 + 自动生成字幕）
  - 前端在视频信息卡片中展示字幕列表，按"手动字幕"和"自动生成字幕"分组
  - 每个字幕轨道提供"下载"按钮（下载 SRT/VTT 原始字幕文件）
  - 每个字幕轨道提供"翻译"按钮，支持选择目标语言（中文、English、日本語、한국어 等 7 种）
  - 后端 `/api/subtitle` 端点：使用 yt-dlp 下载字幕文件
  - 后端 `/api/subtitle/translate` 端点：下载字幕 + 使用 deep-translator（Google Translate）翻译
  - SRT 格式按时间轴逐段翻译，保留时间码；其他格式逐行翻译

### 技术细节

- 新增 `SubtitleTrack` 数据模型（`core/models.py`）
- `VideoInfo` 新增 `subtitles` 字段
- `parse_info()` 新增 `listsubtitles: True` 提取字幕信息
- YouTube 翻译字幕：利用 yt-dlp 的 `automatic_captions` 中已有的翻译条目（带 `tlang` 参数），直接从 YouTube 服务器获取翻译结果，无需外部 API
- 其他平台翻译：降级到 MyMemory 翻译服务（免费、无需 API Key、国内可访问）
- 依赖新增 `deep-translator==1.11.4`

---

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