// 应用入口：挂载 React 根节点、全局提示与确认框宿主
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './styles/theme.css'
import './styles.css'
import './utils/time' // 初始化 dayjs 中文与相对时间插件
import ThemeProvider from './components/theme/ThemeProvider'
import { Toaster } from './components/shadcn/sonner'
import { TooltipProvider } from './components/shadcn/tooltip'
import { ConfirmHost } from './components/ui/confirm'
import { useTheme } from './store/theme'

// 首帧之前先把 data-theme / data-glass 写到 <html> 上。
// ThemeProvider 里的 useEffect 要等挂载后才跑，不提前写的话首帧取到的是默认值，切到深色主题时会闪一下白。
{
  const initial = useTheme.getState()
  document.documentElement.setAttribute('data-theme', initial.theme)
  document.documentElement.setAttribute('data-glass', initial.glass ? 'on' : 'off')
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <ThemeProvider>
    {/* 提示条与浮层需要两个全局 Provider；确认框宿主挂在根部，供 hook 里的 confirm() 使用 */}
    <TooltipProvider delayDuration={200}>
      {/* 使用 history 路由，配合 App.tsx 中的 <Routes> 定义页面导航 */}
      <BrowserRouter>
        <App />
      </BrowserRouter>
      <Toaster position="top-center" />
      <ConfirmHost />
    </TooltipProvider>
  </ThemeProvider>,
)
