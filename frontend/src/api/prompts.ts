import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 提示词模板（docs/04 4.16）=====
export interface PromptVariable { name: string; description?: string; required?: boolean; default?: string | null }
export interface PromptTemplateRow {
  id: number
  name: string
  description: string | null
  variables: PromptVariable[]
  version: number
  created_by: number | null
  created_by_username?: string | null
  updated_at: string
  agents_count?: number // 列表附带：绑定该模板的智能体数
  content?: string // 列表不下发，详情 / 保存响应才有
  unused_variables?: string[] // 保存响应：声明了但内容未使用的变量
}
export interface PromptTemplateInput { name: string; description?: string; content: string; variables: PromptVariable[] }
export interface PromptTemplateVersionRow { id: number; version: number; content: string; variables: PromptVariable[]; created_at: string }
export interface PromptRenderResult { content: string; missing: string[]; unused: string[] }
export interface TemplateAgentRow { id: number; name: string; status: string; prompt_template_version: number | null; outdated: boolean }

export const listPromptTemplates = (params?: PageQuery) => get<Page<PromptTemplateRow>>('/prompt-templates', params)
export const getPromptTemplate = (id: number) => get<PromptTemplateRow>(`/prompt-templates/${id}`)
export const createPromptTemplate = (data: PromptTemplateInput) => post<PromptTemplateRow>('/prompt-templates', data)
export const updatePromptTemplate = (id: number, data: PromptTemplateInput) => put<PromptTemplateRow>(`/prompt-templates/${id}`, data)
export const deletePromptTemplate = (id: number) => del(`/prompt-templates/${id}`)
export const batchPromptTemplates = (ids: number[]) => batchAction('/prompt-templates', ids, 'delete')
export const getPromptTemplateVersions = (id: number, params?: PageQuery) => get<Page<PromptTemplateVersionRow>>(`/prompt-templates/${id}/versions`, params)
export const rollbackPromptTemplate = (id: number, versionId: number) => post<PromptTemplateRow>(`/prompt-templates/${id}/rollback/${versionId}`)
export const getPromptTemplateAgents = (id: number) => get<TemplateAgentRow[]>(`/prompt-templates/${id}/agents`)
// 渲染预览：缺必填变量 400 "缺少必填变量：x"
export const renderPromptTemplate = (id: number, variables: Record<string, string>) => post<PromptRenderResult>(`/prompt-templates/${id}/render`, { variables })
