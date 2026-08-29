// Chat 对话页共享类型定义

export interface Citation {
  kb_id?: number
  doc_name?: string
  content?: string
  score?: number
}

export type ToolStepStatus = 'running' | 'done' | 'error'

export interface ToolStep {
  id?: string
  name: string
  args: any
  status: ToolStepStatus
  result?: string
}

export interface ChatUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface Msg {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  tools?: ToolStep[]
  usage?: ChatUsage
}
