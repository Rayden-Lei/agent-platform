import { get, type Page, type PageQuery } from './core'

// ===== 模型调用日志（2026-11-08）=====
// 每次模型调用的完整记录：实际请求地址、请求体（messages 全文 + 工具定义 + 参数）、
// 响应原文（含流式 SSE 帧）、解析出的正文与思考过程、工具调用、用量、耗时、错误原文。
// 打码口径：**只有凭据打码**，地址、报文、错误原文全部原样保存 —— 排查全靠它们。
// 列表不返回报文大字段（上百条几 MB 会让页面卡死），点开详情才取。
export type LlmCallPurpose = 'chat' | 'workflow' | 'debug' | 'summary' | 'rewrite' | 'probe' | 'embedding'
export type LlmCallStatus = 'success' | 'error'

export interface LlmCallRow {
  id: number
  run_id: number | null
  model_id: number | null
  model_name: string
  purpose: LlmCallPurpose
  /** 实际请求地址（完整 URL，能看出打到了哪个上游） */
  url: string
  method: string
  status: LlmCallStatus
  http_status: number | null
  error: string | null
  prompt_tokens: number
  completion_tokens: number
  first_token_ms: number | null
  duration_ms: number
  /** 本次发给了模型哪些工具 */
  tool_names: string[]
  /** 模型实际调用了哪些工具 */
  called_tools: string[]
  started_at: string | null
  /** 报文是否被截断（超出上限）；截断时原文里注明了原长度 */
  truncated: boolean
}

export interface LlmToolDef {
  name: string
  description: string
  parameters: Record<string, unknown>
}

export interface LlmCallDetail extends LlmCallRow {
  /** 完整请求体：messages 全文、工具定义、温度等参数都在里面 */
  request_body: Record<string, unknown> | null
  /** 完整响应原文（流式时是 SSE 帧原文） */
  response_body: string | null
  /** 解析出的回答正文 */
  response_text: string | null
  /** 解析出的思考过程（推理模型才有） */
  reasoning_text: string | null
  tools_offered: LlmToolDef[]
  tool_calls: { name: string; arguments: unknown }[]
}

export interface LlmCallStats {
  total: number
  failed: number
  today: number
  /** 日志开关是否打开（LLM_LOG_ENABLED） */
  enabled: boolean
}

export const listLlmCalls = (params?: PageQuery) => get<Page<LlmCallRow>>('/llm-calls', params)
export const getLlmCall = (id: number) => get<LlmCallDetail>('/llm-calls/' + id)
export const getLlmCallStats = () => get<LlmCallStats>('/llm-calls/stats')
