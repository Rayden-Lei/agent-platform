// 应用入口：挂载 React 根节点，注入全局 antd 中文语言包与主题 token
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import 'antd/dist/reset.css'
import './styles/theme.css'
import './styles.css'
import './utils/time' // 初始化 dayjs 中文与相对时间插件
import ThemeProvider from './components/theme/ThemeProvider'
import { useTheme } from './store/theme'

// antd 主题桥接：过渡期 antd 组件仍在使用，把当前配色映射到 antd token，
// 让还没迁移的页面也跟着换肤。antd 全部迁移完成后这一层整体删除。
function AntdBridge({ children }: { children: React.ReactNode }) {
  const themeKey = useTheme((s) => s.theme)
  const dark = themeKey === 'deep' || themeKey === 'midnight'

  // CSS 变量是运行时解析的，React 不知道它变了——所以这里把 themeKey 声明为依赖，
  // 主题切换时强制重算一次 getComputedStyle，antd 的 token 才会跟着换。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const css = React.useMemo(() => getComputedStyle(document.documentElement), [themeKey])
  const pick = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: pick('--accent', '#4F46E5'),
          borderRadius: 8,
          fontSize: 14,
          colorLink: pick('--accent', '#4F46E5'),
          colorBgLayout: pick('--bg', '#F5F7FB'),
          colorBgContainer: pick('--bg-elev', '#FFFFFF'),
          colorText: pick('--fg', '#0F172A'),
          colorBorder: pick('--border', '#E4E9F0'),
        },
        components: {
          Menu: { darkItemBg: 'transparent' },
        },
      }}
    >
      {children}
    </ConfigProvider>
  )
}

// 首帧之前先把 data-theme / data-glass 写到 <html> 上。
// ThemeProvider 里的 useEffect 要等挂载后才跑，而 AntdBridge 在同一次渲染里就要读 CSS 变量——
// 不提前写的话首帧取到的全是 fallback（白底），切到深色主题时会闪一下白。
{
  const initial = useTheme.getState()
  document.documentElement.setAttribute('data-theme', initial.theme)
  document.documentElement.setAttribute('data-glass', initial.glass ? 'on' : 'off')
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <ThemeProvider>
    <AntdBridge>
      {/* 使用 history 路由，配合 App.tsx 中的 <Routes> 定义页面导航 */}
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </AntdBridge>
  </ThemeProvider>,
)
