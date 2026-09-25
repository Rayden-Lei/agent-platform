import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 模型（docs/04 4.3）=====
// 模型调用参数：模型的 default_params 与智能体的 params 同一结构（后端 schemas.ModelParams，只认这四个键，未知键 422）。
// 运行时按"模型默认 ← 智能体覆盖"合并，留空的键继承上一层
export interface ModelParams {
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  thinking?: 'disabled' | 'enabled' | null
}
// 提交前去掉留空的键：留空表示继承 / 不设置，不能把 null 当显式值发给后端
export const compactParams = (params?: ModelParams | null): ModelParams =>
  Object.fromEntries(Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '')) as ModelParams

export interface ModelRow {
  id: number
  name: string
  provider: string
  api_base: string
  model_name: string
  default_params: ModelParams
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
  default_params?: ModelParams
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
