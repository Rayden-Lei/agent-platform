import { get, type PageQuery } from './core'
import type { RunRow } from './runs'
import type { DegradedItem, SchedulerStatus } from './system'

// ===== 运营统计（docs/04 4.17）：数据库侧聚合，按 REPORT_TIMEZONE 切天 =====
// 各聚合接口共用的指标块；avg_latency_ms 只算已结束的运行，success_rate 分母为 0 时 null
export interface RunMetrics {
  total: number
  success: number
  failed: number
  cancelled: number
  awaiting_review: number
  running: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: number
  avg_latency_ms: number | null
  success_rate: number | null
}
export interface DailyRunStat extends RunMetrics { date: string }
export interface StatsOverview {
  resources: Record<'agents' | 'published_agents' | 'models' | 'enabled_models' | 'workflows' | 'knowledge_bases' | 'documents' | 'tools' | 'prompt_templates' | 'users' | 'api_keys' | 'schedules', number>
  today: RunMetrics
  last_7d: RunMetrics
  pending: Record<'awaiting_review' | 'running' | 'stuck_running' | 'failed_today' | 'failed_documents' | 'processing_documents' | 'open_breakers' | 'unregistered_schedules', number>
  degraded: DegradedItem[]
  scheduler: SchedulerStatus
  recent_runs: RunRow[]
}
export interface ModelUsageRow extends RunMetrics {
  model_id: number
  name: string
  provider: string
  model_name: string
  is_enabled: boolean
  agents_count: number
  breaker: { state: string; consecutive_failures: number; retry_after_seconds: number } | null
}
export interface AgentUsageRow extends RunMetrics {
  agent_id: number
  name: string
  status: string
  model_id: number | null
  model_name: string | null
  conversations: number
  messages: number
  last_run_at: string | null
}
export interface WorkflowUsageRow extends RunMetrics {
  workflow_id: number
  name: string
  status: string
  last_run_at: string | null
}

export const getStatsOverview = () => get<StatsOverview>('/stats/overview')
export const getDailyRunStats = (params?: PageQuery) => get<{ days: number; timezone: string; items: DailyRunStat[] }>('/stats/runs/daily', params)
export const getPeriodSummary = (params?: PageQuery) => get<RunMetrics & { days: number }>('/stats/runs/summary', params)
export const getModelUsage = (params?: PageQuery) => get<{ days: number; items: ModelUsageRow[] }>('/stats/models', params)
export const getAgentUsage = (params?: PageQuery) => get<{ days: number; items: AgentUsageRow[] }>('/stats/agents', params)
export const getWorkflowUsage = (params?: PageQuery) => get<{ days: number; items: WorkflowUsageRow[] }>('/stats/workflows', params)
