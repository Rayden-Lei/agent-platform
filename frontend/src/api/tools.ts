import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 工具（docs/04 4.7，含在线测试）=====
export type ToolPropertyType = 'string' | 'number' | 'integer' | 'boolean'
export interface ToolProperty { type: ToolPropertyType; description?: string; enum?: string[] }
// HTTP 工具参数声明（docs/03-数据库设计.md 4.2 的 JSON Schema 子集）；后端保存时校验并规范化
export interface ToolParameters { type: 'object'; properties: Record<string, ToolProperty>; required: string[] }
// 目标地址白名单（docs/16 P3a）：只写主机名，执行时按域名后缀匹配；不填表示过渡期放行但每次留日志
// 内置工具自己的配置项声明（后端 tools/tool_config.py 下发），工具页据此渲染表单。
// 配置属于工具而不属于系统：同一平台上的两个 web_search 可以指向不同的搜索服务。
export interface ToolConfigField {
  key: string
  label: string
  description: string
  kind: 'str' | 'int' | 'secret'
  min: number
  max: number
  step: number
  unit: string
  placeholder: string
  default: string | number
}
export interface ToolConfig {
  url?: string; method?: string; headers?: Record<string, string>
  parameters?: ToolParameters; allowed_hosts?: string[]
  config_fields?: ToolConfigField[]
  [key: string]: unknown
}
// 鉴权（docs/04 4.7，2026-09-29 起）：凭据加密托管、任何接口不回传，只告诉你配没配（has_secret）
export type ToolAuthType = 'none' | 'api_key' | 'bearer' | 'basic'
export interface ToolAuth { type: ToolAuthType; location?: 'header' | 'query' | null; name?: string | null }
export interface ToolRow {
  id: number
  name: string
  description: string
  // mcp（docs/17 §5）：从外部 MCP server 同步来的工具，地址与凭据在 mcp_servers 那一行上
  type: 'builtin' | 'http' | 'mcp'
  /** 仅 type='mcp'：所属服务器、远端工具原名、服务器显示名（服务器已删时为 null） */
  mcp_server_id: number | null
  remote_name: string | null
  mcp_server_name: string | null
  config: ToolConfig
  timeout: number
  is_enabled: boolean
  agents_count: number
  auth: ToolAuth & { has_secret: boolean }
  created_by: number | null
  created_by_username: string | null
  updated_at: string | null
}
// secret 不传 = 沿用已有凭据；clear_secret 为真清除
export type ToolInput = Pick<ToolRow, 'name' | 'description' | 'type' | 'config' | 'timeout'> & { auth: ToolAuth; secret?: string; clear_secret?: boolean }
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
