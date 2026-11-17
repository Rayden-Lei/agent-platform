import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

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

// 用域名从外网访问时（反向代理、临时隧道等），Vite 的 DNS rebinding 防护会拒绝外部域名
// （"Blocked request. This host ... is not allowed"）。用 VITE_ALLOWED_HOSTS 逗号分隔放行；
// 不配则完全不设该项，保持 Vite 默认（只放行本机与 IP）。
// 线上用 IP 直连，走默认规则即可，不需要配这个。
const ALLOWED_HOSTS = (process.env.VITE_ALLOWED_HOSTS || '').split(',').map((h) => h.trim()).filter(Boolean)

export default defineConfig({
  plugins: [react(), tailwindcss(), frameAncestors()],
  // shadcn 组件的源码里统一用 @/ 前缀引用（@/lib/utils 等），这里补上同一套别名
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // preview 也要放行：预览模式同样受 DNS rebinding 防护约束，不放行是 "Blocked request"。
  ...(ALLOWED_HOSTS.length ? { preview: { allowedHosts: ALLOWED_HOSTS } } : {}),
  server: {
    host: '0.0.0.0',
    port: 5173,
    ...(ALLOWED_HOSTS.length ? { allowedHosts: ALLOWED_HOSTS } : {}),
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
    // 其余第三方包合成一个 vendor。
    //
    // **只拆自带依赖、不与别人共享的库**（图表、画布都是这种）。手写正则把某一片生态
    // （react-markdown / remark / unified 那一族）单独切出去是错的：它的共享依赖（react-jsx-runtime、
    // devlop 等）落在 vendor 里，vendor 又要 import 它的导出，于是 Rollup 报循环分块，
    // 把 markdown 块提升成入口的静态依赖 —— 未登录页也会先下那 165 KB。
    // 这正是 2026-09-06 白屏事故的同型结构（当时是 react 与 antd 互依）。
    //
    // 结论：markdown 那一族退回 vendor，由 Rollup 按真实依赖图自行切分；markdown 只在对话/分享页用到，
    // 页面已按路由懒加载，跟着页面走即可。
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('@ant-design/plots') || id.includes('@antv')) return 'charts'
          if (id.includes('@xyflow')) return 'flow'
          // React 运行时单独一块：它是所有页面的公共底座，体积稳定、升级频率低，
          // 单独成块后浏览器能长期缓存，改业务代码不必让它失效重下。
          // 注意只认 react / react-dom / scheduler 本身 —— 把 rc-*、@radix-ui 这类
          // 「依赖 React 的库」也塞进来就会与 vendor 互依成环（2026-09-06 白屏的成因）。
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react'
          return 'vendor'
        },
      },
    },
  },
})
