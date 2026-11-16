import { describe, expect, it } from 'vitest'
import config from '../vite.config.js'

describe('Vite preview configuration', () => {
  it('serves the production build with the application proxies', () => {
    expect(config.preview).toMatchObject({
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': 'http://127.0.0.1:8083',
        '/ws': { target: 'http://127.0.0.1:8083', ws: true },
      },
    })
  })
})
