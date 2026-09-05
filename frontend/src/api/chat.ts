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
export const listMessages = (id: number) => get<MessageRow[]>(`/conversations/${id}/messages`)
export const deleteConversation = (id: number) => del(`/conversations/${id}`)

// ===== 对话流式接口（SSE，docs/04 第 5 节）=====
// axios 不支持浏览器端 SSE 流式读取，此处用 fetch 直连；凭据读取方式与 client 拦截器保持一致。
// 协议约定（与后端 /agents/{id}/chat 对应）：响应为 SSE 事件流，每个事件以 \n\n 分隔，
// 事件体是 JSON，形如 {"type": "<事件类型>", ...}。事件类型见 chatAgentStream 内的 switch。
export interface ChatStreamHandlers {
  onCitations?: (citations: any[]) => void
  onDelta?: (content: string) => void
  onToolCall?: (tc: { id?: string; name?: string; arguments?: any }) => void
  onToolResult?: (tr: { tool_call_id?: string; content?: string }) => void
  onError?: (message: string) => void
  // 流结束：回传会话 id、本轮运行记录 id（可跳到运行详情）、消息 id 与用量
  onDone?: (evt: { conversation_id?: number; run_id?: number; message_id?: number; usage?: ChatTokenUsage }) => void
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
          // 流结束：回传会话 id、运行 id 与 usage，新会话的 id 在此首次出现
          handlers.onDone?.({ conversation_id: evt.conversation_id, run_id: evt.run_id, message_id: evt.message_id, usage: evt.usage })
          if (evt.conversation_id) newCid = evt.conversation_id
          break
      }
    }
  }
  // 返回最新 conversation_id：首条消息时为新建会话的 id（null→数字），供页面刷新会话列表
  return newCid
}
