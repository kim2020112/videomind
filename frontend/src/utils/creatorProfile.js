export function creatorSpaceUrl(creator) {
  return creator?.platform === 'bilibili' && /^[1-9]\d{0,19}$/.test(String(creator.uid))
    ? `https://space.bilibili.com/${creator.uid}/video`
    : ''
}

export function syncStateLabel(item) {
  if (!item) return ''
  switch (item.sync_status) {
    case 'running': return item.sync_mode === 'deep' ? '正在同步全部投稿…' : '正在检查最新投稿…'
    case 'queued': return item.sync_error_code === 'rate_limit'
      ? 'B站限制请求，请稍后手动继续同步'
      : item.sync_error ? `等待自动重试 · ${item.sync_error}` : '同步排队中'
    case 'complete': return `已收录 ${item.catalog_count ?? 0} 个投稿`
    case 'paused': return item.sync_error || (item.sync_error_code === 'login' ? '请更新 通用配置中的 B站 Cookie' : '同步已暂停')
    case 'failed': return item.sync_error ? `同步失败 · ${item.sync_error}` : '同步失败'
    case 'interrupted': return '同步被中断，点击同步继续补齐'
    case 'cancelled': return '同步已取消'
    default: return '尚未同步'
  }
}
