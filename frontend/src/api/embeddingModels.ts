import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 向量模型（docs/04 4.3b）=====
// 与 /models（对话模型）分开：调用协议不同（embeddings vs chat/completions），字段也不同（维度、单请求条数）。
// 知识库建库时从这里选一个绑定，入库与检索都按它走（2026-11-08 起，之前知识库那个字段只是记录不生效）。
export interface EmbeddingModelRow {
  id: number
  name: string
  provider: string
  api_base: string
  model_name: string
  dim: number
  request_size: number
  is_enabled: boolean
  // 密钥只回"有没有"，明文与密文都不下发（与对话模型同一口径）
  has_key: boolean
  kbs_count: number
  created_by: number | null
  created_by_username: string | null
  created_at: string | null
  updated_at: string | null
}
export interface EmbeddingModelInput {
  name: string
  provider: string
  api_base: string
  api_key?: string // 编辑时留空表示沿用已有密钥
  model_name: string
  // 必须与切片表向量列宽一致（服务端校验，不一致 422）：pgvector 是定长列
  dim: number
  request_size: number
  is_enabled: boolean
}
export interface EmbeddingModelDetail extends EmbeddingModelRow {
  knowledge_bases: { id: number; name: string }[]
}
// 建库下拉的候选项：只列启用的
export interface EmbeddingModelOption {
  id: number
  name: string
  provider: string
  model_name: string
  dim: number
}

export const listEmbeddingModels = (params?: PageQuery) => get<Page<EmbeddingModelRow>>('/embedding-models', params)
export const getEmbeddingModel = (id: number) => get<EmbeddingModelDetail>(`/embedding-models/${id}`)
export const createEmbeddingModel = (data: EmbeddingModelInput) => post<EmbeddingModelRow>('/embedding-models', data)
export const updateEmbeddingModel = (id: number, data: EmbeddingModelInput) => put<EmbeddingModelRow>(`/embedding-models/${id}`, data)
export const deleteEmbeddingModel = (id: number) => del(`/embedding-models/${id}`)
export const toggleEmbeddingModel = (id: number) => post<{ id: number; is_enabled: boolean }>(`/embedding-models/${id}/toggle`)
export const batchEmbeddingModels = (ids: number[], action: 'enable' | 'disable' | 'delete') => batchAction('/embedding-models', ids, action)
// 建库下拉用：只取启用中的候选，一次拿全（数量很少，不分页）
export const listEmbeddingModelOptions = () => get<{ items: EmbeddingModelOption[] }>('/embedding-models/options')
// 连通测试：成功返回 ok=true 与返回维度；失败 ok=false 带 error，不抛错（要能显示原因）
export const testEmbeddingModel = (id: number) =>
  post<{ ok: boolean; dim?: number | null; reply?: string; error?: string }>(`/embedding-models/${id}/test`)
