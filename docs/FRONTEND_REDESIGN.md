# 前端设计规范

## 品牌

- 产品名称：**SaveAny**
- 定位：免费在线视频下载器
- 设计参考：`image/` 目录下的设计图

## 配色

| 用途 | 颜色 |
|------|------|
| 主色 / 按钮 / 强调 | `#3b82f6` → `#2563eb`（蓝色渐变） |
| 页面背景 | `#ffffff` |
| Hero 背景 | `linear-gradient(180deg, #f0f9ff 0%, #ffffff 100%)` |
| 卡片背景 | `#f9fafb` |
| 主文字 | `#1f2937` |
| 次要文字 | `#6b7280` |
| 边框 | `#e5e7eb` |
| 错误 | `#dc2626`，背景 `#fef2f2` |

## 字体

- 字体族：`-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif`
- 补充：Noto Sans SC（Google Fonts，用于中文）

## 页面布局

页面从上到下分为三个区域：

```
NavBar
HeroSection（含输入框 + 解析按钮）
Results Section（按需显示，有解析结果或错误时出现）
FeaturesSection
```

## 组件规范

### NavBar
- 白色背景，底部 1px 边框，sticky 定位
- 左：SaveAny Logo（蓝色方形图标 + 加粗文字）
- 中：导航链接（功能特性 / 使用教程 / 工具箱 / 常见问题），颜色 `#6b7280`，hover 变蓝
- 右：登录按钮（描边）+ 立即使用按钮（蓝色实心）
- 移动端：导航链接隐藏

### HeroSection
- 浅蓝到白色渐变背景，居中布局，`max-width: 900px`
- 主标题：`2.75rem`，加粗，"一键保存"使用蓝色渐变文字
- 副标题：`1rem`，灰色，列出支持的平台
- 输入框 + 解析按钮：横向排列，`max-width: 700px`，移动端改为纵向
  - 输入框：左侧链接图标，focus 时蓝色边框
  - 解析按钮：蓝色渐变，hover 上浮 2px
- 平台图标：YouTube（红）/ TikTok（黑）/ Bilibili（蓝）/ 抖音（玫红），圆形，hover 上浮 4px

### Results Section（App.vue 内联）
- 仅在 `videoInfo` 或 `error` 存在时渲染
- 错误卡片：红色背景，带图标
- 视频卡片：白色背景，圆角 16px，1px 边框
  - 视频缩略图（200×112）+ 标题 + 平台/时长
  - 清晰度选择按钮组：选中态蓝色边框 + 蓝色背景
  - 下载按钮：蓝色渐变，全宽，带下载图标
  - 进度条：蓝色渐变，显示百分比 + 速度 + ETA
- 下载历史卡片：列表项含标题 + 保存按钮（描边，hover 变实心蓝）

### FeaturesSection
- 白色背景，`padding: 5rem 2rem`，居中
- 标题：`2.5rem`，加粗
- 卡片网格：**`grid-template-columns: repeat(4, 1fr)`**，强制一行
  - 平板（≤1024px）：2 列
  - 移动端（≤768px）：1 列
- 每张卡片：灰色背景，圆角 16px，居中对齐，hover 上浮 4px
- 图标颜色：蓝（支持平台）/ 绿（极速下载）/ 紫（任意格式）/ 橙（永久免费）

## 样式规范

- 组件样式一律使用 `<style scoped>`，不使用 Tailwind 原子类
- 全局 `style.css` 仅保留 Tailwind 导入、基础重置和全局动画
- 圆角统一：按钮 `8-12px`，卡片 `12-16px`，图标容器 `50%`（圆形）或 `12-16px`
- 阴影：卡片 `0 2px 8px rgba(0,0,0,0.05)`，按钮 hover `0 4-6px 12-16px rgba(59,130,246,0.3-0.4)`
- 过渡：统一 `transition: all 0.2s`
