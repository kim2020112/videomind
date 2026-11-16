import { expect, it } from 'vitest'
import { readJsonResponse } from './httpResponse.js'
it('handles empty success and HTML proxy errors', async () => {
  await expect(readJsonResponse(new Response(''))).rejects.toThrow('为空或格式异常')
  await expect(readJsonResponse(new Response('<html>bad gateway</html>', { status: 502 }))).rejects.toThrow('HTTP 502')
})
it('preserves status for authentication retry decisions', async () => {
  await expect(readJsonResponse(Response.json({ detail: '请登录' }, { status: 401 }))).rejects.toMatchObject({ status: 401, message: '请登录' })
})
