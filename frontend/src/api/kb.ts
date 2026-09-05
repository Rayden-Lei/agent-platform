import client from './client'
import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 知识库（docs/04 4.8，含文档上传、检索、切片查看）=====
export interface KnowledgeBaseRow {
  id: number
  name: string
  description: string | null
  embedding_model: string
  chunk_size: number
  chunk_overlap: number
  is_public: boolean
  visible_roles: string[]
  policy_version: number
  document_count: number
  ready_count: number
  failed_count: number
  processing_count: number
  chunk_count: number
  token_count: number
  created_by: number | null
  created_by_username: string | null
  created_at: string | null
  updated_at: string | null
}
export interface KnowledgeBaseInput {
  name: string
  description?: string
  embedding_model?: string
  chunk_size?: number
  chunk_overlap?: number
  is_public?: boolean
  visible_roles?: string[]
}
export interface KnowledgeBaseDetail extends KnowledgeBaseRow { agents: { id: number; name: string; status: string }[] }
export type DocumentStatus = 'uploading' | 'parsing' | 'chunking' | 'ready' | 'failed'
export interface DocumentRow {
  id: number
  kb_id: number
  name: string
  file_type: string
  status: DocumentStatus | string
  chunk_count: number
  error: string | null
  created_at: string | null
}
export interface ChunkRow { id: number; content: string; meta: Record<string, unknown>; token_count: number }
export interface SearchHit {
  content: string
  score: number
  chunk_id: number
  doc_id: number
  doc_name: string
  meta: Record<string, unknown>
  vector_score?: number
  keyword_score?: number
  matched_keywords?: string[]
}
export interface SearchStats {
  query: string
  keywords: string[]
  candidate_count: number
  acl_rejected: number
  returned: number
  top_score: number
  mean_score: number
  lexical_hit_count: number
}

export const listKBs = (params?: PageQuery) => get<Page<KnowledgeBaseRow>>('/knowledge-bases', params)
export const getKB = (id: number) => get<KnowledgeBaseDetail>(`/knowledge-bases/${id}`)
export const createKB = (data: KnowledgeBaseInput) => post<KnowledgeBaseRow>('/knowledge-bases', data)
export const updateKB = (id: number, data: KnowledgeBaseInput) => put<KnowledgeBaseRow>(`/knowledge-bases/${id}`, data)
export const deleteKB = (id: number) => del(`/knowledge-bases/${id}`)
export const batchKBs = (ids: number[]) => batchAction('/knowledge-bases', ids, 'delete')
export const listDocs = (kbId: number, params?: PageQuery) => get<Page<DocumentRow>>(`/knowledge-bases/${kbId}/documents`, params)
// 文档上传走 FormData，axios 会自动带 multipart/form-data 请求头
export const uploadDoc = (kbId: number, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return client.post(`/knowledge-bases/${kbId}/documents`, fd) as unknown as Promise<{ id: number; kb_id: number; name: string; file_type: string; status: string }>
}
export const deleteDoc = (kbId: number, docId: number) => del(`/knowledge-bases/${kbId}/documents/${docId}`)
// 重新解析：失败的文档重试，或切片参数改了之后重建；处理中的文档 400
export const reprocessDoc = (kbId: number, docId: number) => post<{ id: number; status: string }>(`/knowledge-bases/${kbId}/documents/${docId}/reprocess`)
export const batchDocs = (kbId: number, ids: number[], action: 'delete' | 'reprocess') => batchAction(`/knowledge-bases/${kbId}/documents`, ids, action)
export const searchKB = (kbId: number, data: { query: string; top_k?: number; debug?: boolean }) => post<{ items: SearchHit[]; stats?: SearchStats }>(`/knowledge-bases/${kbId}/search`, data)
// 切片列表：在分页结构上额外带文档维度信息，方便页面直接展示所属文档
export const listDocChunks = (kbId: number, docId: number, params?: PageQuery) =>
  get<Page<ChunkRow> & { doc_id: number; doc_name: string }>(`/knowledge-bases/${kbId}/documents/${docId}/chunks`, params)
