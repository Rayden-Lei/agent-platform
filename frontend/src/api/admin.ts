import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 用户（docs/04 4.2）=====
export interface UserRow {
  id: number
  username: string
  role: string
  is_active: boolean
  created_at: string | null
  updated_at: string | null
}
export const listUsers = (params?: PageQuery) => get<Page<UserRow>>('/users', params)
export const createUser = (data: { username: string; password: string; role: string }) => post<UserRow>('/users', data)
export const updateUser = (id: number, data: { role?: string; is_active?: boolean }) => put<UserRow>(`/users/${id}`, data)
export const deleteUser = (id: number) => del(`/users/${id}`)
export const resetUserPassword = (id: number, password: string) => post(`/users/${id}/reset-password`, { password })
export const batchUsers = (ids: number[], action: 'enable' | 'disable' | 'delete') => batchAction('/users', ids, action)

// ===== 审计日志（docs/04 4.11）=====
export interface AuditLogRow {
  id: number
  user_id: number | null
  username: string
  action: string
  resource: string
  resource_id: number | null
  detail: Record<string, unknown>
  ip: string | null
  created_at: string | null
}
export const listAuditLogs = (params?: PageQuery) => get<Page<AuditLogRow>>('/audit-logs', params)

// ===== API Key（docs/04 4.12）：developer 只能看到、操作本人创建的（服务端按归属过滤，他人的一律 404）=====
export interface ApiKeyRow {
  id: number
  name: string
  key_prefix: string
  quota: number
  used: number
  is_enabled: boolean
  allowed_ips: string[]          // 来源白名单（IP 或 CIDR），空 = 不限制
  rate_limit_per_minute: number  // 每分钟限速，0 = 用服务端全局默认
  user_id: number
  username: string | null        // 创建人，admin 视角区分归属
  last_used_at: string | null
  created_at: string | null
}
export interface ApiKeyInput {
  name: string
  quota: number
  allowed_ips: string[]
  rate_limit_per_minute: number
}
export const listApiKeys = (params?: PageQuery) => get<Page<ApiKeyRow>>('/api-keys', params)
// API Key 创建时服务端会返回一次明文 key，之后不再可查（见 ApiKeys 页）
export const createApiKey = (data: ApiKeyInput) => post<ApiKeyRow & { key: string }>('/api-keys', data)
export const updateApiKey = (id: number, data: Partial<ApiKeyInput>) => put<ApiKeyRow>(`/api-keys/${id}`, data)
export const toggleApiKey = (id: number) => post<{ id: number; is_enabled: boolean }>(`/api-keys/${id}/toggle`)
export const deleteApiKey = (id: number) => del(`/api-keys/${id}`)
export const batchApiKeys = (ids: number[], action: 'enable' | 'disable' | 'delete') => batchAction('/api-keys', ids, action)

// ===== 定时任务（docs/04 4.13）=====
export interface ScheduleRow {
  id: number
  name: string
  workflow_id: number
  workflow_name: string | null
  cron: string
  cron_valid: boolean
  input: Record<string, unknown>
  is_enabled: boolean
  user_id: number | null
  username: string | null
  last_run_at: string | null
  last_run_id: number | null
  last_run_status: string | null
  next_run_at: string | null // 来自本进程调度器；停用或未注册为 null
  created_at: string | null
}
export interface ScheduleInput { name: string; workflow_id: number; cron: string; input: Record<string, unknown> }
export const listSchedules = (params?: PageQuery) => get<Page<ScheduleRow>>('/schedules', params)
export const getSchedule = (id: number) => get<ScheduleRow>(`/schedules/${id}`)
export const createSchedule = (data: ScheduleInput) => post<ScheduleRow>('/schedules', data)
export const updateSchedule = (id: number, data: ScheduleInput) => put<ScheduleRow>(`/schedules/${id}`, data)
export const toggleSchedule = (id: number) => post<{ id: number; is_enabled: boolean }>(`/schedules/${id}/toggle`)
export const runScheduleNow = (id: number) => post<{ id: number; triggered_at: string }>(`/schedules/${id}/run`)
export const deleteSchedule = (id: number) => del(`/schedules/${id}`)
export const batchSchedules = (ids: number[], action: 'enable' | 'disable' | 'delete') => batchAction('/schedules', ids, action)
