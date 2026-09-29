import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'
import type { ModelParams } from './models'

// ===== 智能体（docs/04 4.4）=====
// 发布语义（docs/15 3.2，FR-039）：这里读写的配置字段是草稿；对话、API Key、工作流只按 published_version 指向的线上快照回答，
// 保存不再立即生效，发布后才替换线上
export type AgentStatus = 'draft' | 'published' | 'offline' // 从未发布 / 线上可用 / 有线上版本但已下线
export interface AgentRow {
  id: number
  name: string
  description: string | null
  system_prompt: string
  model_id: number
  params: ModelParams // 覆盖模型的 default_params，留空的键继承
  kb_ids: number[]
  tool_ids: number[]
  workflow_id: number | null
  status: AgentStatus | string
  version: number // 最近一次生成的版本号
  published_version: number | null // 线上版本号；从未发布为 null
  published_at: string | null
  has_unpublished_changes: boolean // 草稿与线上快照不同（计算值）
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
  runs_7d: number // 不计装配页调试
  last_run_at: string | null
}
// system_prompt 与 prompt_template_id 二选一：绑定模板时 system_prompt 传空串，由后端渲染
export interface AgentInput {
  name: string
  description?: string
  system_prompt?: string
  model_id: number
  params?: ModelParams
  kb_ids?: number[]
  tool_ids?: number[]
  workflow_id?: number | null
  prompt_template_id?: number | null
  prompt_variables?: Record<string, string>
}
// 更新草稿要带读到的 updated_at（乐观锁）：与库中不一致 409「已被他人修改」，防止两个人同时编辑互相覆盖
export interface AgentUpdateInput extends AgentInput { expected_updated_at: string }
export interface AgentDetail extends AgentRow {
  model: { id: number; name: string; provider: string; model_name: string; is_enabled: boolean } | null
  tools: { id: number; name: string; type: string; is_enabled: boolean }[]
  missing_tool_ids: number[]
  knowledge_bases: { id: number; name: string; is_public: boolean }[]
  missing_kb_ids: number[]
  workflow: { id: number; name: string; status: string } | null
  prompt_template: { id: number; name: string; version: number; variables: { name: string; description?: string; required?: boolean; default?: string | null }[] } | null
}
// 发布 / 回滚上线的结果：published 生成了新线上版本或重新上线；unchanged 与线上一致，什么都没做
export interface AgentPublishResult extends AgentRow { publish_result: 'published' | 'unchanged' }
// 可对话智能体的对外资料（GET /agents/available）：任何登录角色都能取，只含这四个字段；名称与描述取线上快照
export interface AgentBrief {
  id: number
  name: string
  description: string | null
  published_at: string | null
}
export interface AgentVersionRow {
  id: number
  version: number
  snapshot: Record<string, unknown>
  created_at: string
  created_by: number | null
  created_by_username: string | null
  note: string | null // 发布说明；迁移补发的是"迁移补发"，回滚上线的是"回滚到 vN"
  is_live: boolean
  model_name: string | null
  prompt_template_name: string | null
}

export const listAgents = (params?: PageQuery) => get<Page<AgentRow>>('/agents', params)
export const listAvailableAgents = (params?: PageQuery) => get<Page<AgentBrief>>('/agents/available', params)
export const getAgent = (id: number) => get<AgentDetail>(`/agents/${id}`)
export const createAgent = (data: AgentInput) => post<AgentRow>('/agents', data)
export const updateAgent = (id: number, data: AgentUpdateInput) => put<AgentRow>(`/agents/${id}`, data)
export const deleteAgent = (id: number) => del(`/agents/${id}`)
export const publishAgent = (id: number, note?: string) => post<AgentPublishResult>(`/agents/${id}/publish`, note ? { note } : undefined)
export const offlineAgent = (id: number) => post<{ id: number; status: AgentStatus }>(`/agents/${id}/offline`)
export const batchAgents = (ids: number[], action: 'publish' | 'offline' | 'delete') => batchAction('/agents', ids, action)
export const getAgentVersions = (id: number, params?: PageQuery) => get<Page<AgentVersionRow>>(`/agents/${id}/versions`, params)
// 恢复到草稿：草稿 = 该版本快照，线上不变
export const restoreAgentVersion = (id: number, versionId: number) => post<AgentRow>(`/agents/${id}/versions/${versionId}/restore`)
// 回滚上线：用该版本快照生成新版本并立即上线，草稿不动
export const rollbackAgent = (id: number, versionId: number) => post<AgentPublishResult>(`/agents/${id}/rollback/${versionId}`)
