import { describe, expect, it } from 'vitest'
import { canMarkPartCached, markPartCached } from './multipartState.js'

describe('markPartCached', () => {
  it('marks only the selected part without mutating the input list', () => {
    const parts = [
      { index: 1, title: '第一节', is_cached: false },
      { index: 2, title: '第二节', is_cached: false },
    ]

    const updated = markPartCached(parts, 2)

    expect(updated).toEqual([
      { index: 1, title: '第一节', is_cached: false },
      { index: 2, title: '第二节', is_cached: true },
    ])
    expect(parts[1].is_cached).toBe(false)
  })

  it('marks foreground results including cache replay, but not fallback or background work', () => {
    const summaryResult = { summary: '已生成摘要' }

    expect(canMarkPartCached({ summaryResult })).toBe(true)
    expect(canMarkPartCached({ summaryResult, summaryError: '该视频无字幕，将基于简介生成总结' })).toBe(false)
    expect(canMarkPartCached({ summaryResult, backgroundTask: { task_id: 'task-1' } })).toBe(false)
    expect(canMarkPartCached({ summaryResult: { summary: '' } })).toBe(false)
  })
})
