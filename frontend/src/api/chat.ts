import type { AgentInput } from './agents'
import { clearLoginAndRedirect } from './client'
import { del, get, type Page, type PageQuery } from './core'

// ===== 会话与消息（docs/04 4.6）=====
export interface ConversationRow {
  id: number
  agent_id: number | null
  agent_name: string | null
  title: string | null
  summary: string | null // 更早消息的持久化摘要，用于排查模型"记错上下文"
  message_count: number
  created_at: string
  updated_at: string
}
export interface ChatTokenUsage { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
export interface MessageRow {
  id: number
  role: 'user' | 'assistant' | string
  content: string
  tool_calls: unknown[]
  citations: unknown[]
  token_usage: ChatTokenUsage | null
  created_at: string
}

export const listConversations = (params?: PageQuery) => get<Page<ConversationRow>>('/conversations', params)
export const getConversation = (id: number) => get<ConversationRow>(`/conversations/${id}`)
export const listMessages = (id: number) => get<MessageRow[]>(`/conversations/${id}/messages`)
export const deleteConversation = (id: number) => del(`/conversations/${id}`)

// ===== 对话流式接口（SSE，docs/04 第 5 节）=====
// axios 不支持浏览器端 SSE 流式读取，此处用 fetch 直连；凭据读取、401 与错误文案的口径与 client 拦截器、utils/errors 一致。
// 协议约定：响应为 SSE 事件流，每个事件以 \n\n 分隔，事件体是 JSON，形如 {"type": "<事件类型>", ...}，事件类型见 streamSse 内的 switch。
// 调用链的一步（docs/04 第 5 节 trace 事件；后端 services/chat_trace.py 定义，全平台共用）
export type TraceStepType = 'rewrite' | 'retrieve' | 'llm' | 'tool'
export interface TraceStep {
  id: string
  type: TraceStepType | string
  name: string
  status: 'success' | 'error' | 'denied' | string
  started_at: string
  duration_ms: number
  input: any
  output: any
  meta: Record<string, any>
}
// 检索步骤 output 里的一条命中：只有定位与各项分数，正文在 citations 里（按 chunk_id 对上）
export interface TraceHit {
  chunk_id: number
  doc_id: number | null
  doc_name: string | null
  score: number
  vector_score: number | null
  keyword_score: number | null
  rerank_score: number | null
  location: { type?: string; page?: number; row?: number; heading?: string }
}
// 调试专有：实际发给模型的系统提示词，以及 done 里的耗时与成本
export interface PromptInfo { system_prompt: string; history_count: number }
export interface DebugMetrics {
  first_token_ms: number | null
  latency_ms: number
  retrieval_ms: number
  cost: number | null
  model_id: number
  model_name: string
  config_source: 'inline' | 'draft' | 'live'
}

export interface ChatStreamHandlers {
  onCitations?: (citations: any[]) => void
  onDelta?: (content: string) => void
  onToolCall?: (tc: { id?: string; name?: string; arguments?: any }) => void
  onToolResult?: (tr: { tool_call_id?: string; content?: string }) => void
  onError?: (message: string) => void
  onPrompt?: (prompt: PromptInfo) => void // 仅调试
  onTrace?: (step: TraceStep) => void // 仅调试
  // 流结束：回传会话 id、本轮运行记录 id（可跳到运行详情）、消息 id 与用量；调试不带会话与消息 id，多带 metrics
  onDone?: (evt: { conversation_id?: number; run_id?: number; message_id?: number; usage?: ChatTokenUsage; metrics?: DebugMetrics }) => void
}

export interface ChatPayload { message: string; conversation_id: number | null }
// 发送函数：对话组件与 useChatStream 不绑定具体接口，由页面注入（登录对话、装配页调试、分享访客各一个）
export type ChatTransport = (payload: ChatPayload, handlers: ChatStreamHandlers, signal: AbortSignal) => Promise<number | null>

// 非 2xx 的错误文案：422 是 FastAPI 的逐字段数组，取首条 msg（此前直接显示成 [object Object]）；5xx 拼上追踪 ID
async function streamErrorText(res: Response): Promise<string> {
  const body = await res.json().catch(() => ({})) as { detail?: unknown; trace_id?: string }
  const detail = body.detail
  let text = ''
  if (Array.isArray(detail)) text = String((detail[0] as { msg?: string } | undefined)?.msg || '').replace(/^Value error, /, '')
  else if (typeof detail === 'string') text = detail
  text = text || '请求失败'
  const traceId = body.trace_id || res.headers.get('x-request-id')
  return res.status >= 500 && traceId ? `${text}（trace: ${traceId}）` : text
}

// 通用 SSE 流：POST JSON，逐个事件回调，返回流结束时最新的 conversation_id（首条消息时新会话的 id 在 done 事件里首次出现）。
// 登录对话、装配页调试、分享访客都是它的薄封装，新增事件类型在下面的 switch 里加分支。
// 401 与 axios 拦截器同样处理：清登录态回登录页（此前这里只弹一句提示，停在原页面）
export async function streamSse(url: string, body: ChatPayload | DebugChatPayload, handlers: ChatStreamHandlers, signal?: AbortSignal): Promise<number | null> {
  const token = localStorage.getItem('token')
  const res = await fetch('/api/v1' + url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: JSON.stringify(body),
    signal, // 传入 AbortSignal 即可由调用方（"停止"按钮）中断整个流
  })
  if (res.status === 401) {
    clearLoginAndRedirect()
    throw new Error('登录已失效，请重新登录')
  }
  if (!res.ok) throw new Error(await streamErrorText(res))
  if (!res.body) throw new Error('响应无内容')

  // SSE 解析：按 \n\n 切分事件块；buffer 保留未成块的残片，
  // 防止一次 read 只返回半个事件（网络分包），下轮继续拼接
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let newCid: number | null = 'conversation_id' in body ? body.conversation_id : null

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
        case 'prompt':
          handlers.onPrompt?.({ system_prompt: evt.system_prompt || '', history_count: evt.history_count ?? 0 })
          break
        case 'trace':
          if (evt.step) handlers.onTrace?.(evt.step)
          break
        case 'done':
          // 流结束：回传会话 id、运行 id 与 usage，新会话的 id 在此首次出现
          handlers.onDone?.({ conversation_id: evt.conversation_id, run_id: evt.run_id, message_id: evt.message_id, usage: evt.usage, metrics: evt.metrics })
          if (evt.conversation_id) newCid = evt.conversation_id
          break
      }
    }
  }
  // 返回最新 conversation_id：首条消息时为新建会话的 id（null→数字），供页面刷新会话列表
  return newCid
}

// 登录用户与已发布智能体对话
export const chatAgentStream = (agentId: number, payload: ChatPayload, handlers: ChatStreamHandlers, signal?: AbortSignal) =>
  streamSse(`/agents/${agentId}/chat`, payload, handlers, signal)

// 装配页当场调试（docs/04 4.5）：调试历史由前端带上；inline 时 config 是编辑器当前内容（含未保存修改）
export interface DebugHistoryItem { role: 'user' | 'assistant'; content: string }
export interface DebugChatPayload {
  message: string
  history: DebugHistoryItem[]
  config_source: 'inline' | 'draft' | 'live'
  config?: AgentInput
}
export const chatDebugStream = (agentId: number, payload: DebugChatPayload, handlers: ChatStreamHandlers, signal?: AbortSignal) =>
  streamSse(`/agents/${agentId}/debug-chat`, payload, handlers, signal)
