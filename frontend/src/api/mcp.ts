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
  /** 参数声明（从远端 inputSchema 转来的子集），抽屉里据此生成试用表单 */
  parameters: { type: 'object'; properties: Record<string, { type: string; description?: string; enum?: string[] }>; required?: string[] }
  /** 同步时记录的参数降级说明，抽屉里标黄提示 */
  schema_notes: string[]
  /** 远端已不再提供这个工具（同步时标上并停用） */
  source_missing: boolean
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

/** 粘贴识别的结果：识别不出的字段为 null，由使用者补；notes 是给使用者看的说明 */
export interface McpParsedConfig {
  name: string | null
  url: string
  transport: McpTransport
  headers: Record<string, string>
  secret: string | null
  allowed_hosts: string[]
  notes: string[]
}

// 把一段从别处抄来的配置识别成表单字段（不落库）。支持：地址 / mcpServers JSON / 地址+凭据两行。
// stdio 形式（npx、uvx）会 400 并说明"本平台不支持 stdio"——那不是配错了，是能力边界
export const parseMcpConfig = (text: string) => post<McpParsedConfig>('/mcp-servers/parse', { text })

/** 一键启用 / 停用全部工具的结果 */
export interface McpBulkToggleResult {
  total: number
  changed: number
  is_enabled: boolean
}

// 一键启用该服务器同步出的全部工具：信任一台服务器是一个整体决定，不该逐个点
export const enableAllMcpTools = (id: number) => post<McpBulkToggleResult>(`/mcp-servers/${id}/tools/enable-all`)
export const disableAllMcpTools = (id: number) => post<McpBulkToggleResult>(`/mcp-servers/${id}/tools/disable-all`)

/** 同步 + 一键启用（新建服务器后的标准动作，两步合成一步） */
export interface McpSyncEnableResult extends McpSyncResult {
  enabled_tools: number
  tools_total: number
}

export const syncAndEnableMcpServer = (id: number) =>
  post<McpSyncEnableResult>(`/mcp-servers/${id}/sync-and-enable`)
