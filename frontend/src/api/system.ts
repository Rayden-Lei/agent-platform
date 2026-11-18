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
export interface DegradedItem { item: 'embedding' | 'login_guard' | 'rate_limit' | 'model_breaker' | 'database' | 'scheduler' | 'kb_unsearchable' | string; message: string }
// 当前检索不了的知识库（绑定的向量模型被停用/删除，2026-11-18 起）：结构化清单，前端不必解析 degraded 的文案
export interface KbUnsearchableStatus { id: number; name: string; embedding_model_id: number | null; reason: string }
// is_leader（2026-11-18 起）：本实例是否持有调度锁；false = 从实例（定时任务由持锁实例执行，registered_jobs=0 属正常）；null = 调度器未启动
export interface SchedulerStatus { running: boolean; registered_jobs: number; enabled_jobs: number; is_leader: boolean | null; reason?: string | null }
export interface RerankStatus { mode: 'model' | 'lexical'; configured: boolean; provider: string | null; model: string | null; reason: string | null; last_error: { at: string; error: string } | null }
export interface SystemStatus {
  app: string
  database: { ok: boolean; reason: string | null }
  embedding: EmbeddingStatus
  rerank: RerankStatus
  login_guard: { enabled: boolean; reason: string | null; max_fail: number; lock_seconds: number }
  // 入口限流：configured=false 是配置关闭（不算降级），configured=true 且 enabled=false 是 Redis 故障
  // degraded / public_fail_closed / fail_closed_scopes（2026-11-18 起）：Redis 故障时的降级方向。
  // public_fail_closed=true 表示公开入口已被拒绝（不是"没保护"而是"主动拒绝"），false 表示全部放行
  rate_limit: { enabled: boolean; configured: boolean; degraded: boolean; public_fail_closed: boolean; fail_closed_scopes: string[]; reason: string | null; api_key_per_minute: number; user_per_minute: number; ip_per_minute: number }
  // 只列非 closed 的模型熔断器；open 的同时会出现在 degraded
  model_breakers: ModelBreakerStatus[]
  scheduler: SchedulerStatus
  // 来源 IP 自检（docs/15 PB-07）：开了 TRUSTED_PROXY_ENABLED 却没收到合法 X-Real-IP 时 ok=false，同时出现在 degraded；resolved 是本次请求解析出的来源
  client_ip: { trusted_proxy: boolean; real_ip_header: boolean; resolved: string | null; ok: boolean }
  // 有界：items 最多 20 条，total 是实际总数，truncated 是被截掉的条数
  unsearchable_kbs: { items: KbUnsearchableStatus[]; total: number; truncated: number }
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
  kind: 'int' | 'float' | 'str' | 'secret'
  step: number
  min: number
  max: number
  placeholder: string
  default: number | string | null  // .env / 后端默认值；secret 类恒为 null（不回显）
  value: number | string | null    // 当前生效值；secret 类恒为 null（只给 masked / configured）
  source: 'default' | 'db'  // db = 页面改过，default = 用的还是 .env 默认
  updated_at: string | null
  updated_by: string | null
  // 仅 secret 类型：是否已配置、掩码后的样子（明文永远不下发）
  configured?: boolean
  masked?: string
}
export interface SystemSettings { groups: SystemSettingGroup[]; items: SystemSettingItem[] }
export const getSystemSettings = () => get<SystemSettings>('/system/settings')
// 值传 null 表示恢复默认（删掉库里的覆盖）；文本类传字符串，空串同 null。
// 越界或未知键整批 400，不会只改一半
export const updateSystemSettings = (values: Record<string, number | string | null>) =>
  put<SystemSettings>('/system/settings', { values })
