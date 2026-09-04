// 应用入口：挂载 React 根节点，注入全局 antd 中文语言包与主题 token
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import 'antd/dist/reset.css'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  // 全局 antd 配置：zh_CN 文案 + 统一主题（品牌蓝 #1e40af、圆角 6、字号 14、链接色、布局底色），并覆盖 Menu/Table 的局部样式
  <ConfigProvider
    locale={zhCN}
    theme={{
      token: {
        colorPrimary: '#1e40af',
        borderRadius: 6,
        fontSize: 14,
        colorLink: '#1e40af',
        colorBgLayout: '#f5f6f8',
      },
      components: {
        Menu: { darkItemBg: 'transparent' },
        Table: { headerBg: '#f8fafc' },
      },
    }}
  >
    {/* 使用 history 路由，配合 App.tsx 中的 <Routes> 定义页面导航 */}
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </ConfigProvider>,
)
