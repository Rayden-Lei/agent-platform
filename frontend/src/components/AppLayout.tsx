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

const roleLabel: Record<string, string> = { admin: '管理员', developer: '开发者', caller: '调用者' }

export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout } = useAuth()
  const screens = useBreakpoint()
  const isMobile = !screens.md
  const [drawerOpen, setDrawerOpen] = useState(false)

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

  const logo = (
    <div className="brand-logo">
      <div className="brand-logo-icon"><RobotOutlined /></div>
      <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.2 }}>智枢·智能体平台</div>
    </div>
  )

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
        <Header style={{ height: 56, flexShrink: 0, background: '#fff', padding: '0 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 1px 4px rgba(0,0,0,0.06)', zIndex: 10 }}>
          {isMobile ? (
            <Button type="text" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)} />
          ) : (
            <Typography.Text strong style={{ fontSize: 15 }}>工作台</Typography.Text>
          )}
          <Space size="middle">
            <Space size={8}>
              <Avatar size="small" style={{ background: '#1e40af' }}>{user?.username?.[0]?.toUpperCase()}</Avatar>
              <Typography.Text style={{ fontSize: 13 }}>{user?.username}</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>{roleLabel[user?.role] || user?.role}</Typography.Text>
            </Space>
            <Button size="small" icon={<LogoutOutlined />} onClick={() => { logout(); navigate('/login') }} />
          </Space>
        </Header>
        <Content style={{ flex: 1, minHeight: 0, padding: isMobile ? 12 : 20, display: 'flex', flexDirection: 'column' }}>
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}
