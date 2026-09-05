import { get, type Page, type PageQuery } from './core'

// ===== 运行记录（docs/04 4.10）=====
export type RunStatus = 'running' | 'success' | 'failed' | 'cancelled' | 'awaiting_review'
export type RunSource = 'chat' | 'ui' | 'api_key' | 'schedule'
export interface RunTokenUsage { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
export interface RunRow {
  id: number
  run_type: 'chat' | 'workflow' | string
  agent_id: number | null
  agent_name: string | null
  workflow_id: number | null
  workflow_name: string | null
  user_id: number | null
  username: string | null
  model_id: number | null
  model_name: string | null
  conversation_id: number | null
  source: RunSource | null
  schedule_id: number | null
  status: RunStatus | string
  error: string | null
  output: Record<string, unknown> | null
  latency_ms: number
  token_usage: RunTokenUsage
  cost: number | null // 收尾时的成本快照，改单价不追溯
  started_at: string | null
  finished_at: string | null
}
export interface RunNodeRow {
  id: number
  node_id: string
  node_type: string
  status: string
  error: string | null
  input: string | null // 引擎截断到 500 字符的文本快照
  output: string | null
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
}
export interface RunDetail extends RunRow { input: Record<string, unknown>; nodes: RunNodeRow[] }
export interface LatencyBucket { label: string; from_ms: number; to_ms: number | null; count: number }
// 运行汇总统计：随列表筛选联动；耗时指标只统计已结束的运行
export interface RunsSummary {
  total: number
  running: number
  success: number
  failed: number
  cancelled: number
  awaiting_review: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  total_cost: number
  avg_latency_ms: number | null
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  success_rate: number | null
  latency_buckets: LatencyBucket[]
}

export const listRuns = (params?: PageQuery) => get<Page<RunRow>>('/runs', params)
export const getRunsSummary = (params?: PageQuery) => get<RunsSummary>('/runs/summary', params)
export const getRun = (id: number) => get<RunDetail>(`/runs/${id}`)
