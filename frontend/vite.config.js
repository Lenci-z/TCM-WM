import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// B-T2 前端工程：开发代理 /api → FastAPI（B-T1，默认 8321 端口）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8321',
        changeOrigin: true,
      },
    },
  },
})
