import { beforeEach, describe, expect, it } from 'vitest'
import { bloggerContextKey, cacheBloggerPage, readBloggerPage, clearBloggerPages } from './bloggerNavigation.js'
describe('blogger page snapshots', () => {
  beforeEach(clearBloggerPages)
  it('evicts least recently used pages and separates identity and page size', () => {
    for (let i = 0; i < 5; i++) cacheBloggerPage(`page${i}`, { id: i })
    readBloggerPage('page0')
    cacheBloggerPage('page5', { id: 5 })
    expect(readBloggerPage('page1')).toBeUndefined()
    expect(readBloggerPage('page0')).toEqual({ id: 0 })
    expect(bloggerContextKey('user:1', '7', {})).not.toBe(bloggerContextKey('user:2', '7', {}))
    expect(bloggerContextKey('user:1', '7', {})).not.toBe(bloggerContextKey('user:1', '7', { pageSize: 50 }))
  })
})
