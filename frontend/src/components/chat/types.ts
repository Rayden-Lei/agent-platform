import type { DebugMetrics, PromptInfo, TraceStep } from '../../api'

// Chat 对话页共享类型定义：描述一条聊天消息除正文外的附加信息（引用、工具步骤、Token 用量、所属运行）

// 与后端 CHAT_MESSAGE_MAX_CHARS 的默认值一致；输入框限长只是体验，超长的权威拒绝在后端（422）
export const CHAT_MESSAGE_MAX_CHARS = 8000

// 知识库检索命中的引用片段：kb_id 来源知识库、doc_name 文档名、content 片段内容、score 相关度得分
export interface Citation {
  kb_id?: number
  chunk_id?: number
  doc_name?: string
  content?: string
  score?: number
}

// 工具调用步骤的实时状态：running 执行中 / done 已完成 / error 出错
export type ToolStepStatus = 'running' | 'done' | 'error'

// 一次工具调用记录：name 工具名、args 入参（结构因工具而异）、status 当前状态、result 返回结果文本
export interface ToolStep {
  id?: string
  name: string
  args: any
  status: ToolStepStatus
  result?: string
}

// 模型 token 用量统计（对应后端返回的 usage 字段）
export interface ChatUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

// 对话面板能看到哪些过程信息（docs/15 D-19）：登录对话页按角色给，分享页按链接配置给，装配页调试全开。
// 组件默认取"最少暴露"，调用方显式放开
export interface ChatCapabilities {
  showRunLink: boolean // 回答脚注的"运行记录"链接（运行记录只对 admin / developer 开放）
  showToolDetails: boolean // 工具的入参与结果（入参可能含内部地址）；关掉时只显示工具名
  showCitations: boolean // 引用来源卡片与正文里的 [n] 悬浮出处
  showUsage: boolean // Token 用量
  allowRegenerate: boolean
  showDebugMeta: boolean // 调试专有：脚注的首字 / 总耗时 / 成本与"详情"（调用链、实际提示词）
}
export const MINIMAL_CAPABILITIES: ChatCapabilities = { showRunLink: false, showToolDetails: false, showCitations: false, showUsage: false, allowRegenerate: false, showDebugMeta: false }
export const FULL_CAPABILITIES: ChatCapabilities = { showRunLink: true, showToolDetails: true, showCitations: true, showUsage: true, allowRegenerate: true, showDebugMeta: false }
export const DEBUG_CAPABILITIES: ChatCapabilities = { ...FULL_CAPABILITIES, showDebugMeta: true }

// 聊天消息统一结构：user 消息通常只有 content，assistant 消息可携带 citations / tools / usage / runId（本轮运行记录，可跳详情）
export interface Msg {
  id?: number
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  tools?: ToolStep[]
  usage?: ChatUsage
  runId?: number
  createdAt?: string
  failed?: boolean // 以错误结束：调试把历史带给下一轮时跳过这一问一答
  // 仅调试：实际系统提示词、调用链步骤、耗时与成本
  prompt?: PromptInfo
  trace?: TraceStep[]
  metrics?: DebugMetrics
}
