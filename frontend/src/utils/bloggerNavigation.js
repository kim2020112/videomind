// Per-tab, identity-scoped context survives workspace reload without storing credentials.
export function bloggerContextKey(identity, subId, state) {
  return `videomind:blogger-return:v1:${JSON.stringify([identity, String(subId), state.q || '', state.learned || 'all', Boolean(state.subtitle)])}`
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
