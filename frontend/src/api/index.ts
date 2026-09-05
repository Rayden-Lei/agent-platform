import client from './client'

// ===== 接口封装层 =====
// 所有接口的唯一下游：页面只从这里 import，不直接碰 axios。
// 约定一：响应已被 client 拦截器解包成 res.data，下面直接按业务类型收窄。
// 约定二：列表接口统一返回 Page<T> 分页结构（见下），page/page_size 由 usePagedList 传递。

// ===== 分页契约（docs/04-接口设计.md 2.3）=====
export interface Page<T = any> {
  items: T[]
  total: number
  page: number
  page_size: number
}
// 分页查询参数：page/page_size 可选，其余字段（如 status、run_type）透传给后端做筛选
export type PageQuery = { page?: number; page_size?: number } & Record<string, string | number | boolean | undefined>

// 拦截器已把响应解包成 res.data，这里只是把类型收窄，避免每个页面各写一遍 as any
const get = <T = any>(url: string, params?: object) => client.get(url, { params }) as unknown as Promise<T>

export const login = (data: { username: string; password: string }) => client.post('/auth/login', data)
export const me = () => client.get('/auth/me')

// ===== 模型 =====
export const listModels = (params?: PageQuery) => get<Page>('/models', params)
export const createModel = (data: any) => client.post('/models', data)
export const updateModel = (id: number, data: any) => client.put(`/models/${id}`, data)
export const deleteModel = (id: number) => client.delete(`/models/${id}`)
// 连通测试：成功会关闭该模型的熔断（人工恢复手段）；失败不抛错，data.ok=false 带 error
export const testModel = (id: number) => client.post(`/models/${id}/test`) as unknown as Promise<{ code: number; message: string; data: { ok: boolean; reply?: string; error?: string } }>

// ===== 智能体（含发布、版本历史与回滚）=====
export const listAgents = (params?: PageQuery) => get<Page>('/agents', params)
export const createAgent = (data: any) => client.post('/agents', data)
export const updateAgent = (id: number, data: any) => client.put(`/agents/${id}`, data)
export const deleteAgent = (id: number) => client.delete(`/agents/${id}`)
export const publishAgent = (id: number) => client.post(`/agents/${id}/publish`)
export const getAgentVersions = (id: number, params?: PageQuery) => get<Page>(`/agents/${id}/versions`, params)
export const rollbackAgent = (id: number, versionId: number) => client.post(`/agents/${id}/rollback/${versionId}`)

// ===== 会话与消息 =====
export const listConversations = (params?: PageQuery) => get<Page>('/conversations', params)
export const listMessages = (id: number) => client.get(`/conversations/${id}/messages`)
export const deleteConversation = (id: number) => client.delete(`/conversations/${id}`)

// ===== 工具（含在线测试）=====
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
}
export type ToolInput = Pick<ToolRow, 'name' | 'description' | 'type' | 'config' | 'timeout'>
export const listTools = (params?: PageQuery) => get<Page<ToolRow>>('/tools', params)
export const createTool = (data: ToolInput) => client.post('/tools', data)
export const updateTool = (id: number, data: ToolInput) => client.put(`/tools/${id}`, data)
export const deleteTool = (id: number) => client.delete(`/tools/${id}`)
// HTTP 工具的 args 先按参数声明校验，不合法 400 "参数校验失败：..." 且不发起调用
export const testTool = (id: number, data: { args: Record<string, unknown> }) => client.post(`/tools/${id}/test`, data)

// ===== 知识库（含文档上传、检索、切片查看）=====
export const listKBs = (params?: PageQuery) => get<Page>('/knowledge-bases', params)
export const createKB = (data: any) => client.post('/knowledge-bases', data)
export const updateKB = (id: number, data: any) => client.put(`/knowledge-bases/${id}`, data)
export const deleteKB = (id: number) => client.delete(`/knowledge-bases/${id}`)
export const listDocs = (kbId: number, params?: PageQuery) => get<Page>(`/knowledge-bases/${kbId}/documents`, params)
// 文档上传走 FormData，axios 会自动带 multipart/form-data 请求头
export const uploadDoc = (kbId: number, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return client.post(`/knowledge-bases/${kbId}/documents`, fd)
}
export const searchKB = (kbId: number, data: any) => client.post(`/knowledge-bases/${kbId}/search`, data)
// 切片列表：在分页结构上额外带文档维度信息，方便页面直接展示所属文档
export const listDocChunks = (kbId: number, docId: number, params?: PageQuery) =>
  get<Page & { doc_id: number; doc_name: string }>(`/knowledge-bases/${kbId}/documents/${docId}/chunks`, params)

// ===== 工作流（含测试运行、人工审核恢复）=====
export const listWorkflows = (params?: PageQuery) => get<Page>('/workflows', params)
export const getWorkflow = (id: number) => client.get(`/workflows/${id}`)
export const createWorkflow = (data: any) => client.post('/workflows', data)
export const updateWorkflow = (id: number, data: any) => client.put(`/workflows/${id}`, data)
export const deleteWorkflow = (id: number) => client.delete(`/workflows/${id}`)
export const runWorkflow = (id: number, data: any) => client.post(`/workflows/${id}/run`, data)
export const testRunWorkflow = (data: any) => client.post('/workflows/test-run', data)
export const listWorkflowRuns = (id: number, params?: PageQuery) => get<Page>(`/workflows/${id}/runs`, params)
export const resumeWorkflow = (workflowId: number, runId: number, decision: any) => client.post(`/workflows/${workflowId}/runs/${runId}/resume`, { decision })

// ===== 运行记录（汇总统计与详情）=====
export const listRuns = (params?: PageQuery) => get<Page>('/runs', params)
export interface RunsSummary {
  total: number
  running: number
  success: number
  failed: number
  cancelled: number
  awaiting_review: number
  total_tokens: number
  total_cost: number
}
// 运行汇总统计：返回的不是分页结构，是各状态计数与 token/成本合计
export const getRunsSummary = () => get<RunsSummary>('/runs/summary')
export const getRun = (id: number) => client.get(`/runs/${id}`)

// ===== 用户 / 审计日志 / API Key / 定时任务 =====
export const listUsers = (params?: PageQuery) => get<Page>('/users', params)
export const createUser = (data: any) => client.post('/users', data)
export const updateUser = (id: number, data: any) => client.put(`/users/${id}`, data)
export const deleteUser = (id: number) => client.delete(`/users/${id}`)
export const listAuditLogs = (params?: PageQuery) => get<Page>('/audit-logs', params)
// API Key：developer 只能看到、操作本人创建的（服务端按归属过滤，他人的一律 404）
export interface ApiKeyRow {
  id: number
  name: string
  key_prefix: string
  quota: number
  used: number
  is_enabled: boolean
  allowed_ips: string[]          // 来源白名单（IP 或 CIDR），空 = 不限制
  rate_limit_per_minute: number  // 每分钟限速，0 = 用服务端全局默认
  last_used_at: string | null
  created_at: string | null
}
export interface ApiKeyInput {
  name: string
  quota: number
  allowed_ips: string[]
  rate_limit_per_minute: number
}
export const listApiKeys = (params?: PageQuery) => get<Page<ApiKeyRow>>('/api-keys', params)
// API Key 创建时服务端会返回一次明文 key，之后不再可查（见 ApiKeys 页）
export const createApiKey = (data: ApiKeyInput) => client.post('/api-keys', data) as unknown as Promise<ApiKeyRow & { key: string }>
export const updateApiKey = (id: number, data: Partial<ApiKeyInput>) => client.put(`/api-keys/${id}`, data) as unknown as Promise<ApiKeyRow>
export const toggleApiKey = (id: number) => client.post(`/api-keys/${id}/toggle`)
export const deleteApiKey = (id: number) => client.delete(`/api-keys/${id}`)
export const listSchedules = (params?: PageQuery) => get<Page>('/schedules', params)
export const createSchedule = (data: any) => client.post('/schedules', data)
export const toggleSchedule = (id: number) => client.post(`/schedules/${id}/toggle`)
export const deleteSchedule = (id: number) => client.delete(`/schedules/${id}`)

// ===== 系统运行状态（降级可见）=====
export interface EmbeddingStatus {
  mode: 'model' | 'hash'   // hash = 检索正在用本地兜底向量，语义召回能力有限
  model: string
  dim: number
  configured: boolean
  reason: string | null
  last_error: { at: string; error: string } | null
}
export interface ModelBreakerStatus {
  model_id: number
  name: string
  state: 'open' | 'half_open'
  consecutive_failures: number
  opened_at: string | null
  retry_after_seconds: number
}
export interface SystemStatus {
  app: string
  database: { ok: boolean; reason: string | null }
  embedding: EmbeddingStatus
  login_guard: { enabled: boolean; reason: string | null; max_fail: number; lock_seconds: number }
  // 入口限流：configured=false 是配置关闭（不算降级），configured=true 且 enabled=false 是 Redis 故障
  rate_limit: { enabled: boolean; configured: boolean; reason: string | null; api_key_per_minute: number; user_per_minute: number; ip_per_minute: number }
  // 只列非 closed 的模型熔断器；open 的同时会出现在 degraded
  model_breakers: ModelBreakerStatus[]
  scheduler: { running: boolean; registered_jobs: number; enabled_jobs: number }
  degraded: { item: string; message: string }[]
}
export const getSystemStatus = () => get<SystemStatus>('/system/status')

// 下拉选项用：取第一页最多 100 条。超过 100 条时应改为带 q 的服务端搜索，见 docs/09
export const OPTIONS_PAGE: PageQuery = { page: 1, page_size: 100 }

// 对话流式接口（SSE）
// axios 不支持浏览器端 SSE 流式读取，此处用 fetch 直连；凭据读取方式与 client 拦截器保持一致。
// 协议约定（与后端 /agents/{id}/chat 对应）：响应为 SSE 事件流，每个事件以 \n\n 分隔，
// 事件体是 JSON，形如 {"type": "<事件类型>", ...}。事件类型见 chatAgentStream 内的 switch。
export interface ChatStreamHandlers {
  onCitations?: (citations: any[]) => void
  onDelta?: (content: string) => void
  onToolCall?: (tc: { id?: string; name?: string; arguments?: any }) => void
  onToolResult?: (tr: { tool_call_id?: string; content?: string }) => void
  onError?: (message: string) => void
  onDone?: (evt: { conversation_id?: number; usage?: any }) => void
}

// 返回 Promise<number | null>：流结束后返回最新的 conversation_id。
// 首条消息时后端会新建会话并在此回传新 id；后续消息返回原 id。
export const chatAgentStream = async (
  agentId: number,
  payload: { message: string; conversation_id: number | null },
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<number | null> => {
  const token = localStorage.getItem('token')
  const res = await fetch('/api/v1/agents/' + agentId + '/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify(payload),
    signal, // 传入 AbortSignal 即可由调用方（Chat 页的"停止"按钮）中断整个流
  })
  // 非 2xx：尝试解析后端的 detail/message 作为错误信息抛出，供页面直接提示
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err && (err.detail || err.message)) || '请求失败')
  }
  if (!res.body) throw new Error('响应无内容')

  // SSE 解析：按 \n\n 切分事件块；buffer 保留未成块的残片，
  // 防止一次 read 只返回半个事件（网络分包），下轮继续拼接
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let newCid: number | null = payload.conversation_id

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      // 只处理 data: 行；SSE 的注释行/空行直接跳过
      if (!part.startsWith('data: ')) continue
      let evt: any
      // 单个事件体解析失败不影响整体流，跳过继续
      try { evt = JSON.parse(part.slice(6)) } catch { continue }
      switch (evt.type) {
        case 'citations':
          handlers.onCitations?.(evt.citations || [])
          break
        case 'delta':
          handlers.onDelta?.(evt.content || '')
          break
        case 'tool_call':
          handlers.onToolCall?.({ id: evt.id, name: evt.name, arguments: evt.arguments })
          break
        case 'tool_result':
          handlers.onToolResult?.({ tool_call_id: evt.tool_call_id, content: evt.content })
          break
        case 'error':
          handlers.onError?.(evt.message || '')
          break
        case 'done':
          // 流结束：回传会话 id 与 usage，新会话的 id 在此首次出现
          handlers.onDone?.({ conversation_id: evt.conversation_id, usage: evt.usage })
          if (evt.conversation_id) newCid = evt.conversation_id
          break
      }
    }
  }
  // 返回最新 conversation_id：首条消息时为新建会话的 id（null→数字），供页面刷新会话列表
  return newCid
}
