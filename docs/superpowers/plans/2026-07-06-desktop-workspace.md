# Desktop Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a desktop-only parsed-result workspace with a fixed left video sidebar and AI-first main area while preserving the current mobile flow.

**Architecture:** `App.vue` remains the state owner. New focused Vue components provide layout boundaries: `ResultWorkspace` switches desktop/mobile slots, `DesktopWorkspace` composes the two-column shell, `VideoSidebar` frames video/download controls, and `AiWorkspace` frames the AI main area.

**Tech Stack:** Vue 3 SFCs, Vite, scoped CSS, existing JavaScript Composition API patterns.

---

### Task 1: Add Workspace Shell Components

**Files:**
- Create: `frontend/src/components/ResultWorkspace.vue`
- Create: `frontend/src/components/DesktopWorkspace.vue`
- Create: `frontend/src/components/VideoSidebar.vue`
- Create: `frontend/src/components/AiWorkspace.vue`

- [ ] **Step 1: Create `ResultWorkspace.vue`**

```vue
<template>
  <section class="result-workspace">
    <div class="result-workspace__desktop">
      <slot name="desktop" />
    </div>
    <div class="result-workspace__mobile">
      <slot name="mobile" />
    </div>
  </section>
</template>

<style scoped>
.result-workspace {
  padding: 3rem 2rem;
  background: var(--bg-primary);
}

.result-workspace__desktop {
  display: none;
}

.result-workspace__mobile {
  display: block;
}

@media (min-width: 1024px) {
  .result-workspace {
    padding: 2rem clamp(1.5rem, 3vw, 3rem) 3rem;
  }

  .result-workspace__desktop {
    display: block;
  }

  .result-workspace__mobile {
    display: none;
  }
}

@media (max-width: 768px) {
  .result-workspace {
    padding: 1.5rem 0.75rem;
  }
}
</style>
```

- [ ] **Step 2: Create `DesktopWorkspace.vue`**

```vue
<template>
  <div class="desktop-workspace">
    <aside class="desktop-workspace__sidebar">
      <slot name="sidebar" />
    </aside>
    <main class="desktop-workspace__main">
      <slot name="main" />
    </main>
  </div>
</template>

<style scoped>
.desktop-workspace {
  width: min(100%, 1480px);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(320px, 360px) minmax(0, 1fr);
  gap: 1.25rem;
  align-items: start;
}

.desktop-workspace__sidebar {
  position: sticky;
  top: 88px;
  max-height: calc(100vh - 112px);
  overflow: auto;
}

.desktop-workspace__main {
  min-width: 0;
}
</style>
```

- [ ] **Step 3: Create `VideoSidebar.vue`**

```vue
<template>
  <div class="video-sidebar">
    <slot />
  </div>
</template>

<style scoped>
.video-sidebar {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
</style>
```

- [ ] **Step 4: Create `AiWorkspace.vue`**

```vue
<template>
  <div class="ai-workspace">
    <slot />
  </div>
</template>

<style scoped>
.ai-workspace {
  min-width: 0;
}
</style>
```

- [ ] **Step 5: Run a build check**

Run: `cd frontend && npm run build`

Expected: build passes or fails only because the new components are unused.

### Task 2: Wire Desktop and Mobile Result Layouts

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Import the workspace components**

Add these imports near existing component imports:

```js
import ResultWorkspace from './components/ResultWorkspace.vue'
import DesktopWorkspace from './components/DesktopWorkspace.vue'
import VideoSidebar from './components/VideoSidebar.vue'
import AiWorkspace from './components/AiWorkspace.vue'
```

- [ ] **Step 2: Replace the parsed-result section wrapper**

Replace the current `<section v-if="videoInfo || error" class="results-section">` with `ResultWorkspace`.

Desktop slot:
- Render the error card when `error` exists.
- Render `DesktopWorkspace` when `videoInfo` exists.
- Put video metadata and download controls inside `VideoSidebar`.
- Put `AiSummary` and download history inside `AiWorkspace`.

Mobile slot:
- Keep the existing `video-card`, top-level summary/download tab bar, and download history flow.

- [ ] **Step 3: Keep mobile behavior unchanged**

The mobile slot should continue using:

```vue
<div class="tab-bar">
  <button class="tab-button" :class="{ active: activeTab === 'summary' }" @click="activeTab = 'summary'">AI 总结</button>
  <button class="tab-button" :class="{ active: activeTab === 'download' }" @click="activeTab = 'download'">视频下载</button>
</div>
```

- [ ] **Step 4: Make desktop download secondary**

In the desktop sidebar, wrap download controls in:

```vue
<details class="sidebar-download">
  <summary class="sidebar-download-summary">视频下载</summary>
  <div class="sidebar-download-content">
    <!-- existing download controls -->
  </div>
</details>
```

- [ ] **Step 5: Run a build check**

Run: `cd frontend && npm run build`

Expected: build passes.

### Task 3: Add Desktop-Specific Styling

**Files:**
- Modify: `frontend/src/App.vue`

- [ ] **Step 1: Add desktop workspace classes**

Add CSS classes for:

```css
.desktop-video-card
.desktop-ai-card
.desktop-sidebar-card
.sidebar-download
.sidebar-download-summary
.sidebar-download-content
.desktop-download-history
```

- [ ] **Step 2: Keep existing mobile styles intact**

Do not remove existing mobile media rules for:

```css
.results-section
.results-container
.video-card
.video-info
.format-grid
.tab-bar
.tab-button
```

- [ ] **Step 3: Run a build check**

Run: `cd frontend && npm run build`

Expected: build passes.

### Task 4: Verify Responsive Behavior

**Files:**
- No code files unless verification finds layout regressions.

- [ ] **Step 1: Build production assets**

Run: `cd frontend && npm run build`

Expected: Vite build completes successfully.

- [ ] **Step 2: Inspect generated CSS/JS bundle warnings**

Expected: no syntax errors or unresolved component warnings.

- [ ] **Step 3: Manual viewport checklist**

Check these viewport intents after starting the app:

```text
390px: mobile slot is visible; desktop workspace is hidden.
1024px: desktop workspace is visible; left sidebar is sticky.
1440px: AI main area is primary; sidebar remains around 320px-360px.
```

- [ ] **Step 4: Commit implementation**

```bash
git add frontend/src/App.vue frontend/src/components/ResultWorkspace.vue frontend/src/components/DesktopWorkspace.vue frontend/src/components/VideoSidebar.vue frontend/src/components/AiWorkspace.vue docs/superpowers/plans/2026-07-06-desktop-workspace.md
git commit -m "feat: add desktop result workspace"
```
