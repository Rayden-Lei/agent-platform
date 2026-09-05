import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 智能体（docs/04 4.4，含发布、版本历史与回滚）=====
export interface AgentRow {
  id: number
  name: string
  description: string | null
  system_prompt: string
  model_id: number
  params: Record<string, unknown>
  kb_ids: number[]
  tool_ids: number[]
  workflow_id: number | null
  status: string
  version: number
  // Prompt 模板绑定：绑定时 system_prompt 是渲染结果；outdated = 模板当前版本高于绑定时版本
  prompt_template_id: number | null
  prompt_template_version: number | null
  prompt_variables: Record<string, string>
  prompt_template_outdated: boolean
  // 列表附带的关联信息
  model_name: string | null
  prompt_template_name: string | null
  created_by: number | null
  created_by_username: string | null
  created_at: string | null
  updated_at: string | null
  runs_7d: number
  last_run_at: string | null
}
// system_prompt 与 prompt_template_id 二选一：绑定模板时 system_prompt 传空串，由后端渲染
export interface AgentInput {
  name: string
  description?: string
  system_prompt?: string
  model_id: number
  params?: Record<string, unknown>
  kb_ids?: number[]
  tool_ids?: number[]
  workflow_id?: number | null
  prompt_template_id?: number | null
  prompt_variables?: Record<string, string>
}
export interface AgentDetail extends AgentRow {
  model: { id: number; name: string; provider: string; model_name: string; is_enabled: boolean } | null
  tools: { id: number; name: string; type: string; is_enabled: boolean }[]
  missing_tool_ids: number[]
  knowledge_bases: { id: number; name: string; is_public: boolean }[]
  missing_kb_ids: number[]
  workflow: { id: number; name: string; status: string } | null
  prompt_template: { id: number; name: string; version: number; variables: { name: string; description?: string; required?: boolean; default?: string | null }[] } | null
}
export interface AgentVersionRow {
  id: number
  version: number
  snapshot: Record<string, unknown>
  created_at: string
}

export const listAgents = (params?: PageQuery) => get<Page<AgentRow>>('/agents', params)
export const getAgent = (id: number) => get<AgentDetail>(`/agents/${id}`)
export const createAgent = (data: AgentInput) => post<AgentRow>('/agents', data)
export const updateAgent = (id: number, data: AgentInput) => put<AgentRow>(`/agents/${id}`, data)
export const deleteAgent = (id: number) => del(`/agents/${id}`)
export const publishAgent = (id: number) => post<AgentRow>(`/agents/${id}/publish`)
export const batchAgents = (ids: number[], action: 'publish' | 'delete') => batchAction('/agents', ids, action)
export const getAgentVersions = (id: number, params?: PageQuery) => get<Page<AgentVersionRow>>(`/agents/${id}/versions`, params)
export const rollbackAgent = (id: number, versionId: number) => post<AgentRow>(`/agents/${id}/rollback/${versionId}`)
