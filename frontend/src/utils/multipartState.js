export function markPartCached(parts, partIndex) {
  return (parts || []).map(part => (
    part.index === partIndex ? { ...part, is_cached: true } : part
  ))
}

export function canMarkPartCached({ summaryResult, backgroundTask = null, summaryError = '' }) {
  return Boolean(summaryResult?.summary && !backgroundTask && !summaryError)
}
