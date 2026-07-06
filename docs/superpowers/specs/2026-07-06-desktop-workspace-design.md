# Desktop Workspace Design

## Context

VideoMind currently supports both desktop and mobile with a responsive single-column flow. This works well on phones, but it leaves desktop screens underused, especially after a video has been parsed. The project should keep the homepage simple while turning the parsed-result experience into a desktop learning workspace.

This design is for the first structured desktop upgrade. It does not redesign the whole product, change backend APIs, or alter mobile-first behavior.

## Goals

- Keep the homepage clean and simple before parsing.
- Enable a desktop workspace layout only after a video has been parsed.
- Make AI learning output the primary desktop focus.
- Keep video context, multipart navigation, and download controls available in a fixed left sidebar.
- Preserve the current mobile vertical layout below the desktop breakpoint.
- Split the result page into clearer components without duplicating business state.

## Non-Goals

- Do not redesign the public homepage.
- Do not change backend APIs or composables.
- Do not rewrite `AiSummary` internals in the first pass.
- Do not make download the primary product workflow.
- Do not change mobile interaction patterns unless required to prevent regressions.

## Breakpoint Strategy

The desktop workspace starts at `1024px`.

Below `1024px`, the result experience keeps the current vertical card flow. This protects phone and narrow tablet layouts from desktop-specific structure.

At `1024px` and above, parsed results use a two-column workspace:

- Left: fixed video context sidebar.
- Right: AI learning workspace.

## Information Architecture

### Homepage

The homepage remains simple:

- Brand and short value proposition.
- URL input.
- Existing navigation.
- Existing feature section.

No desktop workspace is shown before parsing.

### Parsed Desktop Workspace

After `videoInfo` exists, desktop users see a workspace layout.

The left sidebar represents the current video object. It should contain:

- Video thumbnail.
- Video title.
- Platform, uploader, view count, and original link.
- Multipart navigation when available.
- A secondary download area.

The right main area represents the AI learning output. It should contain:

- AI summary as the default primary view.
- Existing AI tabs for summary, notes, mindmap, subtitle, chat, and QA where currently provided by `AiSummary`.
- Enough width for reading and map exploration on large screens.

Download remains a secondary tool. On desktop, it belongs in the sidebar and should be visually quieter than the AI learning area. The first implementation can use a collapsed or subdued download section in the sidebar.

## Component Design

### `App.vue`

`App.vue` remains the state owner for the first implementation.

It keeps:

- URL state.
- Parsing and reset flow.
- Video metadata state.
- Download state.
- Summary, subtitle, chat, and QA state.
- Auth and history view switching.

It delegates parsed-result rendering to `ResultWorkspace`.

### `ResultWorkspace`

Responsibility: choose the result layout.

It receives all result-related data and callbacks from `App.vue`.

It renders:

- Desktop workspace for `>= 1024px`.
- Existing mobile vertical result flow below `1024px`.

It should not own business state or call composables directly.

### `DesktopWorkspace`

Responsibility: desktop two-column composition.

It renders:

- `VideoSidebar` on the left.
- `AiWorkspace` on the right.

The left sidebar should use sticky positioning below the navbar. The right area should scroll naturally with page content.

### `VideoSidebar`

Responsibility: video context and secondary tools.

It receives video-related props and emits events upward.

It should include:

- Thumbnail and play affordance when stream playback exists.
- Title and metadata.
- Description summary if useful and compact.
- Multipart selector when available.
- Download section as a secondary/collapsible control.

It emits events such as:

- `open-video`
- `select-part`
- `select-download-part`
- `select-all-parts`
- `download`
- `download-selected`
- `download-all`
- `download-subtitle`
- `translate-subtitle`

It should not call APIs or composables.

### `AiWorkspace`

Responsibility: AI learning main area.

It wraps the existing `AiSummary` component and passes through AI-related props and callbacks.

It emits events such as:

- `summarize`
- `regenerate-summary`
- `regenerate-mindmap`
- `regenerate-notes`
- `regenerate-subtitle`
- `fetch-subtitle`
- `send-question`
- `generate-qa`
- `regenerate-qa`
- `switch-part`
- `seek-video`

The first implementation should avoid rewriting `AiSummary` internals unless necessary to move download-only UI out of the main workspace.

## Data Flow

The data model remains single-source from `App.vue`.

Props flow downward:

- `App.vue` to `ResultWorkspace`.
- `ResultWorkspace` to `DesktopWorkspace` or mobile layout.
- `DesktopWorkspace` to `VideoSidebar` and `AiWorkspace`.

Events and callbacks flow upward:

- Child components emit user intent.
- `App.vue` runs the existing handlers and composables.

This avoids separate desktop and mobile state, keeps behavior consistent, and lowers the chance of regressions.

## Layout Details

Desktop workspace:

- Container max width should be wider than the current `1100px`, with responsive side padding.
- Left sidebar width should be around `320px` to `360px`.
- Left sidebar should be sticky below the navbar and fit within the viewport.
- Right AI workspace should use remaining width and remain the visual center.
- Sidebar download controls should not visually compete with AI content.

Mobile layout:

- Keep the current order: video information first, then top-level tabs and content.
- Keep current touch target behavior.
- Keep the existing mobile download tab unless a later iteration explicitly redesigns it.

## Error Handling

This change does not introduce new backend errors.

Existing parsing, summary, subtitle, chat, QA, and download errors should continue to render through current state and messages.

Layout-specific error risk is handled by keeping the mobile layout separate from the desktop workspace and by not duplicating async state.

## Testing

Run the frontend build after implementation:

```bash
cd frontend && npm run build
```

Manual responsive checks should cover:

- `390px`: mobile vertical flow remains usable; no desktop sidebar appears.
- `1024px`: desktop workspace appears; left sidebar and AI area both remain usable.
- `1440px`: desktop space is used meaningfully; AI area is primary and sidebar is stable.

Functional checks should cover:

- Parse a video and display metadata.
- Start AI summary generation.
- Switch multipart videos when available.
- Open video playback when stream URL exists.
- Fetch subtitles.
- Send chat questions.
- Generate QA.
- Open and use the secondary download controls.

## Implementation Notes

The first implementation should prioritize structure and behavior preservation over visual polish.

Recommended sequence:

1. Extract the existing parsed-result markup into a result workspace boundary.
2. Introduce desktop-only layout components.
3. Move video context and download controls into the desktop sidebar.
4. Keep mobile markup close to the current implementation.
5. Verify responsive behavior and build output.

After this lands, later iterations can improve:

- AI sub-tab hierarchy.
- Sidebar density and collapse states.
- Desktop keyboard navigation.
- History-to-workspace transitions.
- More polished empty/loading states.
