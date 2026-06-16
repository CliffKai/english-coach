import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 后端默认跑在 8000；前端 dev server 5173（与后端 CORS 默认源一致）。
// /api 代理到后端，前端代码里只写相对路径 /api/...。
// /ws 也代理到后端（ws:true）：F2d 语音对话走 WebSocket（/ws/practice/dialogue），
// 否则 dev 下会连到 Vite server 而非 FastAPI，路由永远到不了。
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
