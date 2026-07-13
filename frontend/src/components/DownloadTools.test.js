import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import DownloadTools from './DownloadTools.vue'

describe('DownloadTools multipart selection', () => {
  it('makes the entire part row a pressed-state button', async () => {
    const wrapper = mount(DownloadTools, {
      props: {
        videoInfo: {
          parts: [
            { index: 1, title: '第一集', duration: 60 },
            { index: 2, title: '第二集', duration: 90 },
          ],
        },
        selectedPartIndices: [],
        currentPart: 1,
      },
    })

    const row = wrapper.get('button.part-row')
    expect(row.attributes('aria-pressed')).toBe('false')
    expect(row.attributes('aria-label')).toContain('选择 P1')

    await row.trigger('click')

    expect(wrapper.emitted('toggle-part')[0]).toEqual([1])
  })

  it('uses a specific current-part download label', () => {
    const wrapper = mount(DownloadTools, {
      props: {
        videoInfo: { parts: [{ index: 1, title: '第一集' }, { index: 2, title: '第二集' }] },
        selectedPartIndices: [],
        currentPart: 2,
        selectedFormatDetail: { height: 1080, ext: 'mp4' },
      },
    })

    expect(wrapper.get('.download-btn-inline').text()).toContain('下载当前 P2 · 1080P')
  })
})
