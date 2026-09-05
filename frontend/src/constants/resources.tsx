import type { ReactNode } from 'react'
import { ApiOutlined, ClockCircleOutlined, DatabaseOutlined, FileTextOutlined, HistoryOutlined, KeyOutlined, PartitionOutlined, RobotOutlined, TeamOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons'

// 资源注册表：关联跳转的唯一来源。详情页型资源跳 /xxx/:id；抽屉型资源跳列表页并带 ?open=:id 自动打开抽屉；
// 会话跳对话页。审计日志的 resource 字段也按此映射成链接。
export type ResourceType = 'agent' | 'workflow' | 'kb' | 'run' | 'conversation' | 'model' | 'tool' | 'user' | 'template' | 'schedule' | 'apikey'

export interface ResourceMeta {
  label: string
  list: string
  link: (id: number) => string
  icon: ReactNode
}

export const RESOURCES: Record<ResourceType, ResourceMeta> = {
  agent: { label: '智能体', list: '/agents', link: (id) => `/agents/${id}`, icon: <RobotOutlined /> },
  workflow: { label: '工作流', list: '/workflows', link: (id) => `/workflows/${id}`, icon: <PartitionOutlined /> },
  kb: { label: '知识库', list: '/knowledge-bases', link: (id) => `/knowledge-bases/${id}`, icon: <DatabaseOutlined /> },
  run: { label: '运行记录', list: '/runs', link: (id) => `/runs/${id}`, icon: <HistoryOutlined /> },
  conversation: { label: '会话', list: '/chat', link: (id) => `/chat?conversation=${id}`, icon: <ApiOutlined /> },
  model: { label: '模型', list: '/models', link: (id) => `/models?open=${id}`, icon: <ThunderboltOutlined /> },
  tool: { label: '工具', list: '/tools', link: (id) => `/tools?open=${id}`, icon: <ToolOutlined /> },
  user: { label: '用户', list: '/users', link: (id) => `/users?open=${id}`, icon: <TeamOutlined /> },
  template: { label: '提示词模板', list: '/prompt-templates', link: (id) => `/prompt-templates?open=${id}`, icon: <FileTextOutlined /> },
  schedule: { label: '定时任务', list: '/schedules', link: (id) => `/schedules?open=${id}`, icon: <ClockCircleOutlined /> },
  apikey: { label: 'API Key', list: '/api-keys', link: (id) => `/api-keys?open=${id}`, icon: <KeyOutlined /> },
}

// 审计日志 resource 字段 → 资源类型；没有映射的（auth）不生成链接
export const AUDIT_RESOURCE_TYPE: Record<string, ResourceType> = {
  model: 'model', agent: 'agent', prompt_template: 'template', user: 'user', api_key: 'apikey', knowledge_base: 'kb', workflow: 'workflow', tool: 'tool',
}
