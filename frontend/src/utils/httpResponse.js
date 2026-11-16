export async function readJsonResponse(response) {
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const error = new Error(typeof data?.detail === 'string' ? data.detail : `请求失败（HTTP ${response.status}），请稍后重试`)
    error.status = response.status
    throw error
  }
  if (!data || typeof data !== 'object') throw new Error('服务返回的数据为空或格式异常，请稍后重试')
  return data
}
