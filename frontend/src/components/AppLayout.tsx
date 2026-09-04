import { useState } from 'react'
import { Layout, Menu, Button, Space, Typography, Drawer, Grid, Avatar } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
  ApiOutlined,
  ToolOutlined,
  DatabaseOutlined,
  PartitionOutlined,
  HistoryOutlined,
  TeamOutlined,
  LogoutOutlined,
  AuditOutlined,
  KeyOutlined,
  ClockCircleOutlined,
  MenuOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth'

const { Sider, Header, Content } = Layout
const { useBreakpoint } = Grid

// 角色 → 中文显示名映射（角色名来自后端，未知角色原样展示）
const roleLabel: Record<string, string> = { admin: '管理员', developer: '开发者', caller: '调用者' }

// 应用主框架：左侧导航（桌面端 Sider / 移动端 Drawer）+ 顶部用户信息栏 + 右侧内容区（<Outlet> 渲染当前路由页面）
export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const screens = useBreakpoint() // antd 响应式断点
  const isMobile = !screens.md // md 以下视为移动端：侧边栏改为抽屉
  const [drawerOpen, setDrawerOpen] = useState(false) // 移动端抽屉是否展开

  // 导航菜单项：key 即路由路径；用户管理/审计日志/API Key/定时任务仅管理员可见
  const items = [
    { key: '/', icon: <DashboardOutlined />, label: '工作台' },
    { key: '/agents', icon: <RobotOutlined />, label: '智能体' },
    { key: '/chat', icon: <ApiOutlined />, label: '对话' },
    { key: '/models', icon: <ThunderboltOutlined />, label: '模型' },
    { key: '/tools', icon: <ToolOutlined />, label: '工具' },
    { key: '/knowledge-bases', icon: <DatabaseOutlined />, label: '知识库' },
    { key: '/workflows', icon: <PartitionOutlined />, label: '工作流' },
    { key: '/runs', icon: <HistoryOutlined />, label: '运行记录' },
    ...(user?.role === 'admin' ? [{ key: '/users', icon: <TeamOutlined />, label: '用户管理' }, { key: '/audit-logs', icon: <AuditOutlined />, label: '审计日志' }, { key: '/api-keys', icon: <KeyOutlined />, label: 'API Key' }, { key: '/schedules', icon: <ClockCircleOutlined />, label: '定时任务' }] : []),
  ]

  // 品牌 Logo 区：图标 + 平台名
  const logo = (
    <div className="brand-logo">
      <div className="brand-logo-icon"><RobotOutlined /></div>
      <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.2 }}>智枢·智能体平台</div>
    </div>
  )

  // 导航菜单：选中项跟随当前路由，点击后跳转（移动端同时关闭抽屉）
  const menu = (
    <Menu
      mode="inline"
      theme="dark"
      selectedKeys={[location.pathname]}
      items={items}
      onClick={(e) => { navigate(e.key); setDrawerOpen(false) }}
      style={{ background: 'transparent' }}
    />
  )

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* 移动端用抽屉承载导航，桌面端用固定 Sider */}
      {isMobile ? (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          width={230}
          styles={{ body: { padding: 0, background: '#1f2937' } }}
          title={null}
        >
          {logo}
          {menu}
        </Drawer>
      ) : (
        <Sider theme="dark" width={220} style={{ background: '#1f2937' }}>
          {logo}
          {menu}
        </Sider>
      )}
      <Layout style={{ height: '100vh', overflow: 'hidden' }}>
        {/* 顶部栏：左侧为移动端菜单按钮/页面标题，右侧为当前用户信息与退出登录 */}
        <Header style={{ height: 56, flexShrink: 0, background: '#fff', padding: '0 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', zIndex: 10 }}>
          {isMobile ? (
            <Button type="text" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)} />
          ) : (
            <Typography.Text strong style={{ fontSize: 15 }}>工作台</Typography.Text>
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
        {/* 内容区：外层负责占位与内边距（min-height: 0 保证 flex 子项可收缩），页面自身滚动由各页面内部处理 */}
        <Content style={{ flex: 1, minHeight: 0, padding: isMobile ? 12 : 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
