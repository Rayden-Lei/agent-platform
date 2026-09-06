import { get } from './core'

// ===== 系统运行状态（docs/04 4.14，降级可见）=====
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
export interface DegradedItem { item: 'embedding' | 'login_guard' | 'rate_limit' | 'model_breaker' | 'database' | 'scheduler' | string; message: string }
export interface SchedulerStatus { running: boolean; registered_jobs: number; enabled_jobs: number; reason?: string | null }
export interface RerankStatus { mode: 'model' | 'lexical'; configured: boolean; provider: string | null; model: string | null; reason: string | null; last_error: { at: string; error: string } | null }
export interface SystemStatus {
  app: string
  database: { ok: boolean; reason: string | null }
  embedding: EmbeddingStatus
  rerank: RerankStatus
  login_guard: { enabled: boolean; reason: string | null; max_fail: number; lock_seconds: number }
  // 入口限流：configured=false 是配置关闭（不算降级），configured=true 且 enabled=false 是 Redis 故障
  rate_limit: { enabled: boolean; configured: boolean; reason: string | null; api_key_per_minute: number; user_per_minute: number; ip_per_minute: number }
  // 只列非 closed 的模型熔断器；open 的同时会出现在 degraded
  model_breakers: ModelBreakerStatus[]
  scheduler: SchedulerStatus
  degraded: DegradedItem[]
}
export const getSystemStatus = () => get<SystemStatus>('/system/status')
