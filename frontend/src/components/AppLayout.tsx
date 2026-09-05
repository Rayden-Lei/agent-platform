import { Suspense, useEffect, useState } from 'react'
import { Layout, Button, Space, Typography, Drawer, Grid, Avatar, Skeleton } from 'antd'
import { LogoutOutlined, MenuOutlined } from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { useUnsaved } from '../store/unsaved'
import { navTitle } from '../constants/nav'
import { roleLabel } from '../constants/status'
import SideNav from './layout/SideNav'
import DegradedBanner from './layout/DegradedBanner'

const { Sider, Header, Content } = Layout
const { useBreakpoint } = Grid

// 应用主框架：左侧导航（桌面端 Sider / 移动端 Drawer）+ 顶部用户信息栏 + 降级横幅 + 右侧内容区（<Outlet> 渲染当前路由页面，路由级懒加载用骨架兜底）
export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const dirty = useUnsaved((s) => s.dirty)
  const screens = useBreakpoint() // antd 响应式断点
  const isMobile = !screens.md // md 以下视为移动端：侧边栏改为抽屉
  const [drawerOpen, setDrawerOpen] = useState(false) // 移动端抽屉是否展开

  // 有未保存改动时拦刷新 / 关闭标签页（路由内跳转由 SideNav 拦）
  useEffect(() => {
    if (!dirty) return
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 移动端用抽屉承载导航，桌面端用固定 Sider */}
      {isMobile ? (
        <Drawer placement="left" open={drawerOpen} onClose={() => setDrawerOpen(false)} width={230} styles={{ body: { padding: 0, background: '#1f2937' } }} title={null}>
          <SideNav onNavigate={() => setDrawerOpen(false)} />
        </Drawer>
      ) : (
        <Sider theme="dark" width={220} style={{ background: '#1f2937' }}>
          <SideNav />
        </Sider>
      )}
      <Layout style={{ height: '100vh', overflow: 'hidden' }}>
        {/* 顶部栏：左侧为移动端菜单按钮/页面标题，右侧为当前用户信息与退出登录 */}
        <Header style={{ height: 56, flexShrink: 0, background: '#fff', padding: '0 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', zIndex: 10 }}>
          {isMobile ? (
            <Button type="text" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)} />
          ) : (
            <Typography.Text strong style={{ fontSize: 15 }}>{navTitle(location.pathname)}</Typography.Text>
          )}
          <Space size="middle">
            {/* 用户信息：头像取用户名首字母，另展示用户名与角色中文名 */}
            <Space size={8}>
              <Avatar size="small" style={{ background: '#1e40af' }}>{user?.username?.[0]?.toUpperCase()}</Avatar>
              <Typography.Text style={{ fontSize: 13 }}>{user?.username}</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{roleLabel[user?.role] || user?.role}</Typography.Text>
            </Space>
            <Button size="small" icon={<LogoutOutlined />} onClick={() => { logout(); navigate('/login') }} />
          </Space>
        </Header>
        <DegradedBanner />
        {/* 内容区：外层负责占位与内边距（min-height: 0 保证 flex 子项可收缩），页面自身滚动由各页面内部处理 */}
        <Content style={{ flex: 1, minHeight: 0, padding: isMobile ? 12 : 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} style={{ padding: 8 }} />}>
              <Outlet />
            </Suspense>
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
