import { get, put } from './core'

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

// ===== 运行时可调参数（docs/04 4.14）：页面上改、立刻生效，不用改 .env 重启 =====
export interface SystemSettingGroup { key: string; label: string; description: string }
export interface SystemSettingItem {
  key: string
  label: string
  description: string
  group: string
  unit: string
  kind: 'int' | 'float'
  step: number
  min: number
  max: number
  default: number      // .env / 后端默认值
  value: number        // 当前生效值
  source: 'default' | 'db'  // db = 页面改过，default = 用的还是 .env 默认
  updated_at: string | null
  updated_by: string | null
}
export interface SystemSettings { groups: SystemSettingGroup[]; items: SystemSettingItem[] }
export const getSystemSettings = () => get<SystemSettings>('/system/settings')
// 值传 null 表示恢复默认（删掉库里的覆盖）；越界或未知键整批 400，不会只改一半
export const updateSystemSettings = (values: Record<string, number | null>) => put<SystemSettings>('/system/settings', { values })
