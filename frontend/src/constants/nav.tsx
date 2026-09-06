import type { ReactNode } from 'react'
import { ApiOutlined, AuditOutlined, ClockCircleOutlined, DashboardOutlined, DatabaseOutlined, FileTextOutlined, HistoryOutlined, KeyOutlined, PartitionOutlined, RobotOutlined, SettingOutlined, TeamOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons'

// 导航表：菜单项、角色可见性与页面标题的唯一来源（docs/01 第 3 节权限矩阵）。
// 详情页（/agents/3）按路径前缀匹配到父菜单，标题显示父菜单名。
export interface NavItem {
  key: string
  label: string
  icon: ReactNode
  roles?: string[] // 缺省 = 所有登录角色可见
}

export const NAV_ITEMS: NavItem[] = [
  { key: '/', label: '工作台', icon: <DashboardOutlined /> },
  { key: '/agents', label: '智能体', icon: <RobotOutlined />, roles: ['admin', 'developer'] },
  { key: '/prompt-templates', label: '提示词模板', icon: <FileTextOutlined />, roles: ['admin', 'developer'] },
  { key: '/chat', label: '对话', icon: <ApiOutlined /> },
  { key: '/models', label: '模型', icon: <ThunderboltOutlined />, roles: ['admin', 'developer'] },
  { key: '/tools', label: '工具', icon: <ToolOutlined />, roles: ['admin', 'developer'] },
  { key: '/knowledge-bases', label: '知识库', icon: <DatabaseOutlined />, roles: ['admin', 'developer'] },
  { key: '/workflows', label: '工作流', icon: <PartitionOutlined />, roles: ['admin', 'developer'] },
  { key: '/runs', label: '运行记录', icon: <HistoryOutlined />, roles: ['admin', 'developer'] },
  { key: '/users', label: '用户管理', icon: <TeamOutlined />, roles: ['admin'] },
  { key: '/audit-logs', label: '审计日志', icon: <AuditOutlined />, roles: ['admin'] },
  { key: '/api-keys', label: 'API Key', icon: <KeyOutlined />, roles: ['admin', 'developer'] },
  { key: '/schedules', label: '定时任务', icon: <ClockCircleOutlined />, roles: ['admin', 'developer'] },
  { key: '/system-settings', label: '系统参数', icon: <SettingOutlined />, roles: ['admin', 'developer'] },
]

export const visibleNavItems = (role?: string | null) => NAV_ITEMS.filter((item) => !item.roles || (role && item.roles.includes(role)))

// 当前路径对应的菜单 key：最长前缀匹配（/agents/3 → /agents；/ 只匹配自身）
export function activeNavKey(pathname: string): string {
  if (pathname === '/') return '/'
  const match = NAV_ITEMS.filter((i) => i.key !== '/' && (pathname === i.key || pathname.startsWith(i.key + '/'))).sort((a, b) => b.key.length - a.key.length)[0]
  return match?.key ?? '/'
}

export const navTitle = (pathname: string) => NAV_ITEMS.find((i) => i.key === activeNavKey(pathname))?.label ?? '工作台'
