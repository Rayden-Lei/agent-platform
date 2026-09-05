import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 模型（docs/04 4.3）=====
export interface ModelRow {
  id: number
  name: string
  provider: string
  api_base: string
  model_name: string
  default_params: Record<string, unknown>
  is_enabled: boolean
  price_input: number | null
  price_output: number | null
  agents_count: number
  created_by: number | null
  created_by_username: string | null
  created_at: string | null
  updated_at: string | null
}
export interface ModelInput {
  name: string
  provider: string
  api_base: string
  api_key?: string // 编辑时留空表示沿用已有密钥
  model_name: string
  default_params?: Record<string, unknown>
  price_input?: number | null
  price_output?: number | null
}
export interface ModelDetail extends ModelRow { agents: { id: number; name: string; status: string }[] }

export const listModels = (params?: PageQuery) => get<Page<ModelRow>>('/models', params)
export const getModel = (id: number) => get<ModelDetail>(`/models/${id}`)
export const createModel = (data: ModelInput) => post<ModelRow>('/models', data)
export const updateModel = (id: number, data: ModelInput) => put<ModelRow>(`/models/${id}`, data)
export const deleteModel = (id: number) => del(`/models/${id}`)
export const toggleModel = (id: number) => post<{ id: number; is_enabled: boolean }>(`/models/${id}/toggle`)
export const batchModels = (ids: number[], action: 'enable' | 'disable' | 'delete') => batchAction('/models', ids, action)
// 连通测试：成功会关闭该模型的熔断（人工恢复手段）；失败不抛错，data.ok=false 带 error
export const testModel = (id: number) => post<{ code: number; message: string; data: { ok: boolean; reply?: string; error?: string } }>(`/models/${id}/test`)
