import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import AiSummary from './AiSummary.vue'

const mocks = vi.hoisted(() => ({ instances: [], create: vi.fn() }))
vi.mock('markmap-lib', () => ({ Transformer: class { transform() { return { root: { content: 'root' } } } } }))
vi.mock('markmap-view', () => ({ Markmap: { create: mocks.create } }))

beforeEach(() => {
  mocks.instances.length = 0
  mocks.create.mockReset().mockImplementation(() => {
    let finish
    const instance = { fit: vi.fn().mockResolvedValue(), destroy: vi.fn(), svg: { interrupt: vi.fn() }, zoom: { extent: vi.fn() },
      setData: vi.fn(() => new Promise(resolve => { finish = resolve })), finish: () => finish() }
    mocks.instances.push(instance)
    return instance
  })
})
function setup() {
  return mount(AiSummary, { attachTo: document.body, props: { workspaceMode: true, mindmapMarkdown: '# 导图' } })
}
async function openMap(wrapper) {
  await wrapper.findAll('.sub-tab-btn').find(b => b.text() === '导图').trigger('click')
  await vi.waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1))
}
describe('mindmap navigation lifecycle', () => {
  it('renders only when visible and awaits data before fitting', async () => {
    const wrapper = setup()
    await flushPromises()
    expect(mocks.create).not.toHaveBeenCalled()
    await openMap(wrapper)
    const instance = mocks.instances[0]
    expect(instance.fit).not.toHaveBeenCalled()
    instance.finish()
    await flushPromises()
    expect(instance.fit).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
  it('does not fit an SVG after leaving the workspace during rendering', async () => {
    const wrapper = setup()
    await openMap(wrapper)
    const instance = mocks.instances[0]
    wrapper.unmount()
    instance.finish()
    await flushPromises()
    expect(instance.fit).not.toHaveBeenCalled()
    expect(instance.svg.interrupt).toHaveBeenCalled()
    expect(instance.destroy).toHaveBeenCalled()
  })
})
