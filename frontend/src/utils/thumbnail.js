/** 远程图片统一走缩略图代理：解决混合内容（http 封面）与 CDN 防盗链。 */
export function thumbnailSrc(url) {
  if (!url) return ''
  if (url.startsWith('/') || url.startsWith('data:')) return url
  return `/api/thumbnail?url=${encodeURIComponent(url)}`
}
