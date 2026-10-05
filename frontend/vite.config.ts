import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// 分享页允许被哪些站点嵌入（docs/15 PB-07；嵌入功能在第 3 批）：空格分隔的来源，如 "https://a.com https://b.com"。
// 只保留形如 scheme://host[:port] 的项，防止把分号、引号、换行写进响应头；为空时分享页与管理台一样只许同源嵌入。
const EMBED_ALLOWED_ORIGINS = (process.env.EMBED_ALLOWED_ORIGINS || '').split(/\s+/).filter((o) => /^https?:\/\/[A-Za-z0-9.-]+(:\d+)?$/.test(o))

// 防点击劫持（docs/15 PB-07）：管理台一律 frame-ancestors 'self'，分享页 /s/* 另放行上面的来源。
// 只挂在 preview（线上就是它）；直接 use 的中间件排在 Vite 内置中间件之前，静态文件与 index.html 回退都带上这个头。
function frameAncestors(): Plugin {
  return {
    name: 'frame-ancestors',
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        const allowed = (req.url || '').startsWith('/s/') ? ['\'self\'', ...EMBED_ALLOWED_ORIGINS] : ['\'self\'']
        res.setHeader('Content-Security-Policy', `frame-ancestors ${allowed.join(' ')}`)
        next()
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), frameAncestors()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // 只反代 /api/ 前缀（正则）：写成 '/api' 会按前缀把前端路由 /api-keys 也转给后端，刷新页面时看到的是后端 404。
    // vite preview 默认沿用 server.proxy，线上（preview 反代）同样受此影响。
    // 后端地址可用 VITE_API_TARGET 覆盖：本机跑 oMLX 时 8000 被它占用，后端要换到 8001
    proxy: {
      '^/api/': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        // 来源 IP 由这一跳说了算（docs/15 PB-07）：X-Real-IP 覆写为连接对端，删掉客户端自带的 X-Forwarded-For。
        // 不能只开 xfwd：Vite 内置 http-proxy 是在客户端带来的 X-Forwarded-For 后面追加，而后端（TRUSTED_PROXY_ENABLED 打开时）
        // 先信 X-Real-IP、再取 X-Forwarded-For 首项，客户端自带一个头就能伪造来源，绕过按 IP 的限流、登录尝试次数与 Key 来源白名单。
        // IPv4 客户端在双栈监听下显示为 ::ffff:1.2.3.4，去掉前缀，日志与白名单按普通 IPv4 比对。
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            proxyReq.removeHeader('x-forwarded-for')
            const peer = req.socket.remoteAddress?.replace(/^::ffff:/, '')
            if (peer) proxyReq.setHeader('x-real-ip', peer)
            else proxyReq.removeHeader('x-real-ip')
          })
        },
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
