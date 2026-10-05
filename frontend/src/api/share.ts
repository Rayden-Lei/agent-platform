import { RequestError, responseErrorText, streamSse, type ChatPayload, type ChatStreamHandlers } from './chat'
import { get, post, put, type OkResponse, type Page } from './core'

// ===== 分享体验链接：管理侧（docs/04 4.x「分享链接」，admin / developer；走 axios 实例）=====
export type ShareAccessMode = 'public' | 'login'
export interface AgentShareConfig {
  is_enabled: boolean
  access_mode: ShareAccessMode
  expires_at: string | null // ISO 8601 带时区；null 不过期
  rate_limit_per_minute: number // 整条链接每分钟 1～600
  daily_message_limit: number // 整条链接每天 1～100000（成本的硬上限）
  visitor_daily_limit: number // 每位访客每天 1～1000
  allow_http_tools: boolean
  show_citations: boolean
}
export interface AgentShare extends AgentShareConfig {
  agent_id: number
  code: string | null // 从未保存过为 null
  share_url: string | null // 按 PUBLIC_BASE_URL 拼；没配置为 null，前端用当前域名拼
  password_set: boolean
  published: boolean
  agent_status: string
  updated_at: string | null
  warnings: string[] // 预检：访客检索不到的库、HTTP 工具、模型停用、未发布或已下线
}
// password：不带 = 不改；null = 清除；字符串 = 设置（改密码或访问方式会让已打开页面的访客重新进入）
export type AgentShareInput = AgentShareConfig & { password?: string | null }

export const getAgentShare = (agentId: number) => get<AgentShare>(`/agents/${agentId}/share`)
export const updateAgentShare = (agentId: number, data: AgentShareInput) => put<AgentShare>(`/agents/${agentId}/share`, data)
export const resetAgentShare = (agentId: number) => post<AgentShare>(`/agents/${agentId}/share/reset`)

// ===== 分享访客（/public/shares/{code}，docs/15 3.6）=====
// 用 fetch 而不是 axios 实例：实例会注入平台 token、401 时清登录态跳登录，访客页两样都不要。
// 访客令牌按链接存 localStorage 的 share_token:<code>，响应头 X-Share-Token 有值时替换（公开模式快到期时换发）
export interface ShareInfo {
  agent_name: string
  description: string | null
  opening_statement: string | null
  starter_questions: string[]
  access_mode: ShareAccessMode
  password_required: boolean
  show_citations: boolean
}
export interface GuestConversation { id: number; title: string | null; message_count: number; created_at: string; updated_at: string }
export interface GuestMessage {
  id: number
  role: 'user' | 'assistant' | string
  content: string
  created_at: string
  citations: { doc_name?: string; content?: string }[]
  tool_names: string[]
}

const TIMEOUT_MS = 30000 // 与 axios 实例一致
const tokenKey = (code: string) => `share_token:${code}`
export const getShareToken = (code: string) => localStorage.getItem(tokenKey(code))
export const clearShareToken = (code: string) => localStorage.removeItem(tokenKey(code))
const keepRenewed = (code: string, res: Response) => {
  const renewed = res.headers.get('X-Share-Token')
  if (renewed) localStorage.setItem(tokenKey(code), renewed)
}

// as：none 不带凭据（资料、公开模式建会话）、guest 带访客令牌、platform 带平台 JWT（只有"仅登录"模式建会话那一次）
async function shareFetch<T>(code: string, path: string, as: 'none' | 'guest' | 'platform', method = 'GET', body?: unknown): Promise<T> {
  const token = as === 'guest' ? getShareToken(code) : as === 'platform' ? localStorage.getItem('token') : null
  const res = await fetch(`/api/v1/public/shares/${encodeURIComponent(code)}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(TIMEOUT_MS),
  })
  if (as === 'guest') keepRenewed(code, res)
  if (!res.ok) throw new RequestError(await responseErrorText(res), res.status)
  return res.json() as Promise<T>
}

export const getShareInfo = (code: string) => shareFetch<ShareInfo>(code, '', 'none')
// 领访客令牌并存好；withLogin 为真时带平台 JWT（"仅登录"模式），密码错 / 没登录 401
export async function createShareSession(code: string, password: string | undefined, withLogin: boolean) {
  const s = await shareFetch<{ guest_token: string; visitor_id: string; expires_at: string }>(code, '/sessions', withLogin ? 'platform' : 'none', 'POST', { password: password || null })
  localStorage.setItem(tokenKey(code), s.guest_token)
  return s
}
export const listShareConversations = (code: string, page: number, pageSize: number, q?: string) =>
  shareFetch<Page<GuestConversation>>(code, `/conversations?${new URLSearchParams({ page: String(page), page_size: String(pageSize), ...(q ? { q } : {}) })}`, 'guest')
export const listShareMessages = (code: string, conversationId: number) => shareFetch<GuestMessage[]>(code, `/conversations/${conversationId}/messages`, 'guest')
export const deleteShareConversation = (code: string, conversationId: number) => shareFetch<OkResponse>(code, `/conversations/${conversationId}`, 'guest', 'DELETE')
// 访客对话流：与登录对话同一个 SSE 解析；401（令牌失效）交给页面回到进入流程，不碰平台登录态
export const chatShareStream = (code: string, payload: ChatPayload, handlers: ChatStreamHandlers, signal: AbortSignal, onUnauthorized: (detail?: string) => void) =>
  streamSse(`/public/shares/${encodeURIComponent(code)}/chat`, payload, handlers, signal,
    { token: () => getShareToken(code), onUnauthorized, onResponse: (res) => keepRenewed(code, res) })
