import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter, routes, scrollBehavior } from './router.js'

describe('router', () => {
  it('defines shareable home, workspace and history routes', () => {
    expect(routes.map(route => route.path)).toEqual([
      '/',
      '/workspace',
      '/history',
      '/history/:urlHash',
    ])
  })

  it('restores a history detail URL with query state', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/history/abc123?url=https%3A%2F%2Fexample.com%2Fvideo&tab=download&part=3')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('history-detail')
    expect(router.currentRoute.value.params.urlHash).toBe('abc123')
    expect(router.currentRoute.value.query.tab).toBe('download')
    expect(router.currentRoute.value.query.part).toBe('3')
  })

  it('uses saved positions and otherwise starts at the top', () => {
    expect(scrollBehavior({}, {}, { left: 4, top: 80 })).toEqual({ left: 4, top: 80 })
    expect(scrollBehavior({}, {}, null)).toEqual({ left: 0, top: 0 })
  })
})
