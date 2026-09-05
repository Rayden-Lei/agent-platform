// Chat 对话页共享类型定义：描述一条聊天消息除正文外的附加信息（引用、工具步骤、Token 用量、所属运行）

// 知识库检索命中的引用片段：kb_id 来源知识库、doc_name 文档名、content 片段内容、score 相关度得分
export interface Citation {
  kb_id?: number
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
}
