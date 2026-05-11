# 前端设计规范

## 品牌

- 产品名称：**SaveAny**
- 定位：免费在线视频下载器
- 目标用户：以国内用户为主（B站、抖音、小红书、快手等）

## 配色（深色主题）

### CSS 变量

```css
--bg-primary: #0F172A        /* 页面主背景（深蓝黑） */
--bg-secondary: #1E293B      /* 区块背景（Features 等） */
--bg-card: rgba(255,255,255,0.05)   /* 卡片背景（半透明） */
--bg-card-hover: rgba(255,255,255,0.08)
--border: rgba(255,255,255,0.08)     /* 边框 */
--border-hover: rgba(255,255,255,0.15)
--text-primary: #F1F5F9      /* 主文字 */
--text-secondary: #94A3B8    /* 次要文字 */
--text-muted: #64748B        /* 辅助文字 */
--accent-blue: #3B82F6       /* 主色（蓝） */
--accent-cyan: #06B6D4       /* 强调色（青） */
--accent-pink: #EC4899       /* Pro/付费标识（粉） */
--success: #10B981           /* 成功/音频 */
--error: #EF4444             /* 错误 */
```

### 用途对照

| 用途 | 颜色 |
|------|------|
| 主色 / 按钮 / 链接 | `#3B82F6` → `#06B6D4`（蓝青渐变） |
| 页面背景 | `#0F172A` |
| 区块背景 | `#1E293B` |
| 卡片背景 | `rgba(255,255,255,0.05)` + `backdrop-filter: blur(12px)` |
| 主文字 | `#F1F5F9` |
| 次要文字 | `#94A3B8` |
| 边框 | `rgba(255,255,255,0.08)` |
| 错误 | 文字 `#FCA5A5`，背景 `rgba(239,68,68,0.1)` |
| Pro 标识 | `#EC4899` → `#a855f7`（粉紫渐变） |

## 字体

- 英文/品牌：`Plus Jakarta Sans`（Google Fonts，weight 400-800）
- 中文：`Noto Sans SC`（Google Fonts，weight 400-900）
- 回退：`-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif`

## 页面布局

页面从上到下分为四个区域：

```
NavBar（毛玻璃固定导航）
HeroSection（深色背景 + 光晕 + 输入框 + 平台标签）
Results Section（按需显示，有解析结果或错误时出现）
FeaturesSection（深色区块背景，6 卡片 3 列）
FooterSection（品牌 + 链接 + 平台列表 + 版权）
```

## 组件规范

### NavBar
- 毛玻璃效果：`background: rgba(15,23,42,0.8)` + `backdrop-filter: blur(16px)`
- sticky 定位，底部 1px 半透明边框
- 左：SaveAny Logo（蓝青渐变方形图标 + 加粗文字，`Plus Jakarta Sans` 字体）
- 中：导航链接，颜色 `var(--text-secondary)`，hover 变亮
- 右：登录按钮（描边）+ 立即使用按钮（蓝青渐变实心）
- 移动端：导航链接隐藏

### HeroSection
- 深色背景 + 蓝色光晕（`radial-gradient`，`rgba(59,130,246,0.12)`）
- 品牌名"SaveAny"使用蓝青渐变文字（`-webkit-background-clip: text`）
- 主标题：`3rem`，`Plus Jakarta Sans` 字体
- 副标题：`1.125rem`，`var(--text-secondary)`
- 输入框 + 下载按钮：横向排列，`max-width: 700px`，移动端改为纵向
  - 输入框：半透明深色背景，左侧链接图标，focus 时蓝青边框
  - 按钮：蓝青渐变，文案"免费下载"，hover 上浮
- 信任标签：`无需注册 · 完全免费 · 支持 4K`，`var(--text-muted)`
- 平台标签流：10 个胶囊标签，国内平台优先（B站、抖音、小红书、快手、微博、西瓜视频 → YouTube、TikTok、Instagram、Twitter），hover 时边框变为平台品牌色

### Results Section（App.vue 内联）
- 仅在 `videoInfo` 或 `error` 存在时渲染
- 错误卡片：红色半透明背景，浅红色文字
- 视频卡片：半透明深色背景，毛玻璃边框，圆角 16px
  - **视频信息**：封面图（220×124，含 hover 播放图标叠加层 + 时长角标）+ 标题 + 元数据标签行（平台/上传者/播放量）+ 原视频链接
  - **分P选择器**（B站多P视频）：checkbox（20px）+ P序号 + 标题 + 时长，支持全选/下载选中/合并下载全部
  - **格式选择**：视频/音频合并展示（2 列等宽网格），卡片第一行格式名（加粗），第二行格式类型+文件大小，音频用"仅音频"标签区分，推荐标识（SVG 星标），选中后显示详情栏（格式/编码/帧率/码率），移动端 1 列
  - **字幕区**：语言名 `var(--text-primary)` 高亮色，分组标签 `var(--text-secondary)`，翻译目标语言下拉框适配深色主题
  - **下载按钮**：蓝青渐变，全宽
  - **下载进度**：进度条含 shimmer 动画（下载中），完成=绿色对勾+绿色进度条，失败=红色叉号+红色进度条，边框随状态变色
- **下载记录**：状态图标（成功/失败）+ 标题 + 时间戳 + 保存按钮（含下载图标）

### FeaturesSection
- 背景色 `var(--bg-secondary)`，与 Hero 形成层次
- 标题：`2.25rem`，`Plus Jakarta Sans` 字体
- 卡片网格：**`grid-template-columns: repeat(3, 1fr)`**，6 卡片 2 行
  - 平板（≤1024px）：2 列
  - 移动端（≤768px）：1 列
- 每张卡片：半透明深色背景，毛玻璃边框，圆角 16px，hover 上浮 4px
- 图标颜色：蓝（国内平台）/ 青（极速解析）/ 紫（高清画质）/ 绿（永久免费）/ 粉（字幕翻译 Pro）/ 橙（批量下载 Pro）
- Pro 卡片：粉色边框 + 右上角 `Pro` badge（粉紫渐变）

### FooterSection
- 顶部边框 `var(--border)`
- 品牌区：Logo + 一句话描述
- 链接区：产品 / 支持 / 法律 三组
- 平台列表：国内平台优先，`·` 分隔
- 版权信息居中
- 移动端：品牌区和链接区纵向排列

## 样式规范

- 组件样式一律使用 `<style scoped>`，不使用 Tailwind 原子类
- 全局 `style.css` 管理 CSS 变量、Tailwind 导入、基础重置和全局动画
- 圆角统一：按钮 `8-12px`（使用 `var(--radius)` = 12px），卡片 `16px`
- 过渡：统一 `transition: all 0.2s`
- 毛玻璃：`backdrop-filter: blur(12-16px)` 用于卡片和导航
