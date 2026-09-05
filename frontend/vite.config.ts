import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
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
