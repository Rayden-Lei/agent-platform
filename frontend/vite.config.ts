import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // 只反代 /api/ 前缀（正则）：写成 '/api' 会按前缀把前端路由 /api-keys 也转给后端，刷新页面时看到的是后端 404。
    // vite preview 默认沿用 server.proxy，线上（preview 反代）同样受此影响。
    proxy: {
      '^/api/': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 大依赖单独分块：图表库只在挂了图表的页面下载，画布库只在工作流编辑器 / 详情页下载；页面按路由懒加载
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom', 'zustand', 'axios', 'dayjs'],
          antd: ['antd', '@ant-design/icons'],
          charts: ['@ant-design/plots'],
          flow: ['@xyflow/react'],
          markdown: ['react-markdown', 'remark-gfm'],
        },
      },
    },
  },
})
