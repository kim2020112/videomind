import { afterEach } from 'vitest'
import { config } from '@vue/test-utils'

config.global.stubs = {
  transition: false,
}

window.scrollTo = () => {}

afterEach(() => {
  document.body.innerHTML = ''
  document.body.style.overflow = ''
  localStorage.clear()
  sessionStorage.clear()
})
