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
    // 大依赖单独分块：图表库只在挂了图表的页面下载，画布库只在工作流编辑器 / 详情页下载；页面按路由懒加载。
    // 其余第三方包合成一个 vendor：之前把 react 与 antd 拆成两个块，rc-* 等共享依赖被分到两边形成环，
    // 生产包里 antd 块先于 react 块执行、读 React.version 报 undefined，整站白屏（2026-09-06 线上踩坑）。
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@ant-design/plots') || id.includes('@antv')) return 'charts'
          if (id.includes('@xyflow')) return 'flow'
          if (/node_modules\/(react-markdown|remark-|micromark|mdast-|unified|unist-|hast-|vfile|bail|trough|zwitch|comma-separated-tokens|space-separated-tokens|property-information|html-url-attributes|estree-util|devlop|decode-named-character-reference|character-entities|ccount|longest-streak|markdown-table|trim-lines|is-plain-obj|style-to-object|style-to-js|inline-style-parser|extend)/.test(id)) return 'markdown'
          return 'vendor'
        },
      },
    },
  },
})
