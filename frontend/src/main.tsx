import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import 'antd/dist/reset.css'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
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
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </ConfigProvider>,
)
