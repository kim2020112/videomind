import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const backendTarget = process.env.VIDEOMIND_BACKEND_URL || 'http://127.0.0.1:8083'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': backendTarget,
      '/ws': { target: backendTarget, ws: true },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': backendTarget,
      '/ws': { target: backendTarget, ws: true },
    },
  },
})
