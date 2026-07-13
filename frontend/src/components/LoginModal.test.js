import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import LoginModal from './LoginModal.vue'

const authMocks = vi.hoisted(() => ({
  login: vi.fn(),
  register: vi.fn(),
}))

vi.mock('../composables/useAuth.js', () => ({
  useAuth: () => ({
    login: authMocks.login,
    register: authMocks.register,
    loading: ref(false),
  }),
}))

describe('LoginModal', () => {
  beforeEach(() => {
    authMocks.login.mockReset()
    authMocks.register.mockReset()
  })

  it('shows field-level errors and does not submit empty credentials', async () => {
    const wrapper = mount(LoginModal, {
      attachTo: document.body,
      props: { visible: true },
    })

    await document.querySelector('.form-submit').click()

    expect(document.body.textContent).toContain('请输入用户名')
    expect(document.body.textContent).toContain('请输入密码')
    expect(authMocks.login).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('announces successful authentication to the parent', async () => {
    authMocks.login.mockResolvedValue(true)
    const wrapper = mount(LoginModal, {
      attachTo: document.body,
      props: { visible: true },
    })

    const username = document.querySelector('#login-username')
    const password = document.querySelector('#login-password')
    username.value = 'tester'
    username.dispatchEvent(new Event('input', { bubbles: true }))
    password.value = 'secret'
    password.dispatchEvent(new Event('input', { bubbles: true }))
    document.querySelector('.form-submit').click()
    await flushPromises()

    expect(authMocks.login).toHaveBeenCalledWith('tester', 'secret')
    expect(wrapper.emitted('authenticated')).toHaveLength(1)
    expect(wrapper.emitted('close')).toHaveLength(1)
    wrapper.unmount()
  })
})
