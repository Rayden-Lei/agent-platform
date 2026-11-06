import { batchAction, del, get, post, put, type BatchResult, type Page, type PageQuery } from './core'

// ===== MCP 连接器（docs/17 §5）=====
// 平台里登记外部 MCP server（只支持 HTTP / SSE），把它的 tools 同步进本地 tools 表（type='mcp'），
// 智能体/工作流像用普通工具一样用。不接 stdio：那等于在服务器上执行配置里写的任意命令。
//
// 同步语义（后端 mcp_service.sync_tools）：
//   远端有、库里没有 → 新建，**默认停用**（远端描述是外部输入，先由人看过再启用）
//   远端有、库里也有 → 更新描述与参数声明，**不动启用状态**
//   远端没有、库里有 → 停用并标 source_missing，**不物理删除**（删了会破坏智能体的 tool_ids）
export type McpTransport = 'http' | 'sse'

export interface McpServerRow {
  id: number
  name: string
  description: string | null
  transport: McpTransport
  url: string
  /** 非敏感请求头；凭据不在这里 */
  headers: Record<string, string>
  /** 凭据只告诉你配没配，明文任何接口都不回传（与 tools.auth 同一口径） */
  has_secret: boolean
  is_enabled: boolean
  /** 出站白名单，必填：MCP 地址是外部输入，空名单等于闸门不存在 */
  allowed_hosts: string[]
  last_synced_at: string | null
  last_error: string | null
  tools_count: number
  created_by: number | null
  created_by_username: string | null
  created_at: string
  updated_at: string
}

export interface McpToolRow {
  id: number
  name: string
  remote_name: string | null
  description: string
  is_enabled: boolean
  agents_count: number
}

export interface McpServerDetail extends McpServerRow {
  tools: McpToolRow[]
}

// secret 不传 = 沿用已有凭据；clear_secret 为真清除
export interface McpServerInput {
  name: string
  description?: string | null
  transport: McpTransport
  url: string
  headers: Record<string, string>
  secret?: string
  clear_secret?: boolean
  is_enabled: boolean
  allowed_hosts: string[]
}

export interface McpSyncResult {
  created: number
  updated: number
  disabled: number
  total: number
}

export interface McpTestResult {
  ok: boolean
  count: number
  tools: string[]
}

export const listMcpServers = (params?: PageQuery) => get<Page<McpServerRow>>('/mcp-servers', params)
export const getMcpServer = (id: number) => get<McpServerDetail>(`/mcp-servers/${id}`)
export const createMcpServer = (data: McpServerInput) => post<McpServerRow>('/mcp-servers', data)
export const updateMcpServer = (id: number, data: McpServerInput) => put<McpServerRow>(`/mcp-servers/${id}`, data)
export const deleteMcpServer = (id: number) => del(`/mcp-servers/${id}`)
export const toggleMcpServer = (id: number) => post<{ id: number; is_enabled: boolean }>(`/mcp-servers/${id}/toggle`)
export const syncMcpServer = (id: number) => post<McpSyncResult>(`/mcp-servers/${id}/sync`)
export const batchMcpServers = (ids: number[], action: 'enable' | 'disable' | 'delete'): Promise<BatchResult> =>
  batchAction('/mcp-servers', ids, action)
// 测试连接不落库：新建时还没保存也能测。编辑已有服务器且没重填凭据时传 server_id，后端找回已存凭据
export const testMcpServer = (data: McpServerInput & { server_id?: number }) => post<McpTestResult>('/mcp-servers/test', data)
