import type { ReactNode } from 'react'
import { Plug, ScrollText, Clock, LayoutDashboard, Database, FileText, History, KeyRound, Network, Bot, Settings, Users, Zap, Wrench } from 'lucide-react'

// 导航表：菜单项、角色可见性与页面标题的唯一来源（docs/01 第 3 节权限矩阵）。
// 详情页（/agents/3）按路径前缀匹配到父菜单，标题显示父菜单名。
export interface NavItem {
  key: string
  label: string
  icon: ReactNode
  roles?: string[] // 缺省 = 所有登录角色可见
}

export const NAV_ITEMS: NavItem[] = [
  { key: '/', label: '工作台', icon: <LayoutDashboard /> },
  { key: '/agents', label: '智能体', icon: <Bot />, roles: ['admin', 'developer'] },
  { key: '/prompt-templates', label: '提示词模板', icon: <FileText />, roles: ['admin', 'developer'] },
  { key: '/chat', label: '对话', icon: <Plug /> },
  { key: '/models', label: '模型', icon: <Zap />, roles: ['admin', 'developer'] },
  { key: '/tools', label: '工具', icon: <Wrench />, roles: ['admin', 'developer'] },
  { key: '/knowledge-bases', label: '知识库', icon: <Database />, roles: ['admin', 'developer'] },
  { key: '/workflows', label: '工作流', icon: <Network />, roles: ['admin', 'developer'] },
  { key: '/runs', label: '运行记录', icon: <History />, roles: ['admin', 'developer'] },
  { key: '/users', label: '用户管理', icon: <Users />, roles: ['admin'] },
  { key: '/audit-logs', label: '审计日志', icon: <ScrollText />, roles: ['admin'] },
  { key: '/api-keys', label: 'API Key', icon: <KeyRound />, roles: ['admin', 'developer'] },
  { key: '/schedules', label: '定时任务', icon: <Clock />, roles: ['admin', 'developer'] },
  { key: '/system-settings', label: '系统参数', icon: <Settings />, roles: ['admin', 'developer'] },
]

export const visibleNavItems = (role?: string | null) => NAV_ITEMS.filter((item) => !item.roles || (role && item.roles.includes(role)))

// 不在菜单里的页面（从顶栏进入）单独给标题，侧栏也不高亮任何一项——否则会落到"工作台"
const EXTRA_TITLES: Record<string, string> = { '/profile': '个人中心' }

// 当前路径对应的菜单 key：最长前缀匹配（/agents/3 → /agents；/ 只匹配自身）；不在菜单里的页面返回空串
export function activeNavKey(pathname: string): string {
  if (pathname === '/') return '/'
  if (EXTRA_TITLES[pathname]) return ''
  const match = NAV_ITEMS.filter((i) => i.key !== '/' && (pathname === i.key || pathname.startsWith(i.key + '/'))).sort((a, b) => b.key.length - a.key.length)[0]
  return match?.key ?? '/'
}

export const navTitle = (pathname: string) => EXTRA_TITLES[pathname] ?? NAV_ITEMS.find((i) => i.key === activeNavKey(pathname))?.label ?? '工作台'
