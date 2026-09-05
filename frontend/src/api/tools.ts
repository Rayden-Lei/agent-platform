import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 工具（docs/04 4.7，含在线测试）=====
export type ToolPropertyType = 'string' | 'number' | 'integer' | 'boolean'
export interface ToolProperty { type: ToolPropertyType; description?: string; enum?: string[] }
// HTTP 工具参数声明（docs/03-数据库设计.md 4.2 的 JSON Schema 子集）；后端保存时校验并规范化
export interface ToolParameters { type: 'object'; properties: Record<string, ToolProperty>; required: string[] }
export interface ToolConfig { url?: string; method?: string; headers?: Record<string, string>; parameters?: ToolParameters }
export interface ToolRow {
  id: number
  name: string
  description: string
  type: 'builtin' | 'http'
  config: ToolConfig
  timeout: number
  is_enabled: boolean
  agents_count: number
}
export type ToolInput = Pick<ToolRow, 'name' | 'description' | 'type' | 'config' | 'timeout'>
export interface ToolDetail extends ToolRow { agents: { id: number; name: string; status: string }[] }

export const listTools = (params?: PageQuery) => get<Page<ToolRow>>('/tools', params)
export const getTool = (id: number) => get<ToolDetail>(`/tools/${id}`)
export const createTool = (data: ToolInput) => post<ToolRow>('/tools', data)
export const updateTool = (id: number, data: ToolInput) => put<ToolRow>(`/tools/${id}`, data)
export const deleteTool = (id: number) => del(`/tools/${id}`)
export const toggleTool = (id: number) => post<{ id: number; is_enabled: boolean }>(`/tools/${id}/toggle`)
export const batchTools = (ids: number[], action: 'enable' | 'disable' | 'delete') => batchAction('/tools', ids, action)
// HTTP 工具的 args 先按参数声明校验，不合法 400 "参数校验失败：..." 且不发起调用
export const testTool = (id: number, data: { args: Record<string, unknown> }) => post<{ code: number; message: string; data: { result: unknown } }>(`/tools/${id}/test`, data)
