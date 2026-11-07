import type { ReactNode } from 'react'
import { Plug, ScrollText, Clock, LayoutDashboard, Database, FileText, History, KeyRound, Network, Bot, Settings, Users, Zap, Wrench, BookOpen, Blocks, Binary, Cpu } from 'lucide-react'

// 导航表：菜单项、分组、角色可见性与页面标题的唯一来源（docs/01 第 3 节权限矩阵、docs/17 §2 分组）。
// 详情页（/agents/3）按路径前缀匹配到父菜单，标题显示父菜单名。
// 分组只影响呈现、不影响权限；空组不渲染（caller 只有两组，不能留下空标题）。
export type NavGroup = 'overview' | 'build' | 'capability' | 'chat' | 'operation' | 'system'

// 组的显示顺序与标题；没有成员的组会被 visibleNavGroups 丢掉
export const NAV_GROUPS: { key: NavGroup; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'chat', label: '对话' },
  { key: 'build', label: '构建' },
  { key: 'capability', label: '能力' },
  { key: 'operation', label: '运营' },
  { key: 'system', label: '系统' },
]

export interface NavItem {
  key: string
  label: string
  icon: ReactNode
  group: NavGroup
  roles?: string[] // 缺省 = 所有登录角色可见
}

export const NAV_ITEMS: NavItem[] = [
  { key: '/', label: '工作台', icon: <LayoutDashboard />, group: 'overview' },
  { key: '/chat', label: '对话', icon: <Plug />, group: 'chat' },
  { key: '/agents', label: '智能体', icon: <Bot />, group: 'build', roles: ['admin', 'developer'] },
  { key: '/prompt-templates', label: '提示词模板', icon: <FileText />, group: 'build', roles: ['admin', 'developer'] },
  { key: '/knowledge-bases', label: '知识库', icon: <Database />, group: 'build', roles: ['admin', 'developer'] },
  { key: '/workflows', label: '工作流', icon: <Network />, group: 'build', roles: ['admin', 'developer'] },
  { key: '/models', label: '模型', icon: <Zap />, group: 'capability', roles: ['admin', 'developer'] },
  // 向量模型与对话模型分开：协议（embeddings vs chat/completions）与字段都不同，混在一页会让人选错
  { key: '/embedding-models', label: '向量模型', icon: <Binary />, group: 'capability', roles: ['admin', 'developer'] },
  { key: '/tools', label: '工具', icon: <Wrench />, group: 'capability', roles: ['admin', 'developer'] },
  { key: '/skills', label: '技能', icon: <BookOpen />, group: 'capability', roles: ['admin', 'developer'] },
  { key: '/mcp-servers', label: 'MCP 连接器', icon: <Blocks />, group: 'capability', roles: ['admin', 'developer'] },
  { key: '/runs', label: '运行记录', icon: <History />, group: 'operation', roles: ['admin', 'developer'] },
  // 调用日志与运行记录并列：运行记录是"业务上发生了什么"，调用日志是"上游到底收到了什么"，排查时两张表要对着看
  { key: '/llm-logs', label: '模型调用日志', icon: <Cpu />, group: 'operation', roles: ['admin', 'developer'] },
  { key: '/schedules', label: '定时任务', icon: <Clock />, group: 'operation', roles: ['admin', 'developer'] },
  { key: '/api-keys', label: 'API Key', icon: <KeyRound />, group: 'operation', roles: ['admin', 'developer'] },
  { key: '/users', label: '用户管理', icon: <Users />, group: 'system', roles: ['admin'] },
  { key: '/audit-logs', label: '审计日志', icon: <ScrollText />, group: 'system', roles: ['admin'] },
  { key: '/system-settings', label: '系统参数', icon: <Settings />, group: 'system', roles: ['admin', 'developer'] },
]

export const visibleNavItems = (role?: string | null) => NAV_ITEMS.filter((item) => !item.roles || (role && item.roles.includes(role)))

// 侧栏用：按 NAV_GROUPS 的顺序分组，丢掉没有可见成员的组（组标题都在、项都在空组时会是空标题）
export function visibleNavGroups(role?: string | null): { key: NavGroup; label: string; items: NavItem[] }[] {
  const visible = visibleNavItems(role)
  return NAV_GROUPS.map((g) => ({ ...g, items: visible.filter((item) => item.group === g.key) })).filter((g) => g.items.length > 0)
}

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
