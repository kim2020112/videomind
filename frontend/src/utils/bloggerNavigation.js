// Per-tab, identity-scoped context survives workspace reload without storing credentials.
export function bloggerContextKey(identity, subId, state) {
  return `videomind:blogger-return:v1:${JSON.stringify([identity, String(subId), state.q || '', state.learned || 'all', Boolean(state.subtitle), state.pageSize || 20])}`
}
export function saveBloggerContext(key, value) {
  try { sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* navigation also works with URL anchors */ }
}
export function readBloggerContext(key) {
  try {
    const value = JSON.parse(sessionStorage.getItem(key))
    return value && Number.isFinite(value.videoId) && Array.isArray(value.neighbors) ? value : null
  } catch { return null }
}

// Only five identity-scoped pages are retained in memory; no credentials or subtitles.
const snapshots = new Map()
export function cacheBloggerPage(key, value) {
  snapshots.delete(key)
  snapshots.set(key, value)
  while (snapshots.size > 5) snapshots.delete(snapshots.keys().next().value)
}
export function readBloggerPage(key) {
  const value = snapshots.get(key)
  if (value) { snapshots.delete(key); snapshots.set(key, value) }
  return value
}

export function clearBloggerPages() { snapshots.clear() }
