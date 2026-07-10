export const translateLangs = [
  { code: 'zh-Hans', name: '中文' },
  { code: 'en', name: 'English' },
  { code: 'ja', name: '日本語' },
  { code: 'ko', name: '한국어' },
  { code: 'fr', name: 'Français' },
  { code: 'de', name: 'Deutsch' },
  { code: 'es', name: 'Español' },
]

const langNames = {
  en: 'English',
  'zh-Hans': '中文',
  zh: '中文',
  'zh-CN': '中文',
  ja: '日本語',
  ko: '한국어',
  fr: 'Français',
  de: 'Deutsch',
  es: 'Español',
  pt: 'Português',
  ru: 'Русский',
  it: 'Italiano',
  ar: 'العربية',
  th: 'ไทย',
  vi: 'Tiếng Việt',
  id: 'Bahasa Indonesia',
}

export function formatBytes(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export function stripSizeFromLabel(label) {
  if (!label) return ''
  return label.replace(/[，,]\s*约?\s*[\d.]+\s*[KMGT]?B\s*$/i, '').trim()
}

export function subtitleDisplayName(sub) {
  const parts = sub.lang.split('-')
  if (parts.length >= 2) {
    const target = parts[0]
    const source = parts.slice(1).join('-')
    const targetName = langNames[target] || target
    const sourceName = langNames[source] || source
    return `${targetName}（从 ${sourceName} 翻译）`
  }
  return sub.name || sub.lang
}

export function formatViewCount(count) {
  if (!count) return ''
  if (count >= 10000) return `${(count / 10000).toFixed(1).replace(/\.0$/, '')}万`
  return count.toLocaleString()
}

export function formatDuration(seconds) {
  if (!seconds) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  return `${m} 分钟`
}

export function formatTime(timestamp) {
  if (!timestamp) return ''
  const d = new Date(timestamp)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  const time = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  return isToday ? time : `${d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${time}`
}
