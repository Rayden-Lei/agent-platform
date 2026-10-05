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
// 编辑只改这四项（多带字段服务端 422）；权限走 updateKBAccess，向量模型建库后不可改（docs/15 KB-01）
export interface KnowledgeBaseUpdateInput {
  name: string
  description?: string
  chunk_size?: number
  chunk_overlap?: number
}
export interface KbAccessInput { is_public: boolean; visible_roles: string[] }
// 新建：另带向量模型与初始访问权限
export interface KnowledgeBaseInput extends KnowledgeBaseUpdateInput, Partial<KbAccessInput> { embedding_model?: string }
// 绑定本库的智能体：草稿绑定（in_draft）或在线智能体的线上版本绑定（in_live）
export interface KbBoundAgent { id: number; name: string; status: string; in_draft: boolean; in_live: boolean }
// 各身份能否检索本库：服务端用检索闸门同一函数算出，前端不另写规则；anonymous 是分享链接的匿名访客
export interface KbAccess { admin: boolean; developer: boolean; caller: boolean; anonymous: boolean }
export interface KnowledgeBaseDetail extends KnowledgeBaseRow { agents: KbBoundAgent[]; access: KbAccess }
// 访问权限的变更记录：create 是建库时的初始权限（before 为空），update_access 是之后的每次修改
export interface KbAccessChange { id: number; action: 'create' | 'update_access'; username: string | null; created_at: string | null; before: KbAccessInput | null; after: KbAccessInput }
export type DocumentStatus = 'uploading' | 'parsing' | 'chunking' | 'ready' | 'failed'
export interface DocumentRow {
  id: number
  kb_id: number
  name: string
  file_type: string
  status: DocumentStatus | string
  chunk_count: number // 已入库切片数，处理中逐批递增
  chunk_total: number | null // 分片后确定的计划切片总数；解析阶段为空
  error: string | null
  created_at: string | null
  processing_started_at: string | null // 开始向量化入库的时间
  finished_at: string | null // ready / failed 的时间
  heartbeat_at: string | null // 每批提交刷新；长时间不动即中断
  resume_offset: number // 本次处理从第几片接着做（续处理时非 0）
  processing_node: string | null // 负责处理的后端节点（主机名）
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
  rerank_mode?: 'model' | 'lexical' | null // 本条经过的重排后端；未配置重排模型时为 lexical
  rerank_score?: number | null // 模型重排分（0～1），词法重排时为空
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
  rerank_mode?: 'model' | 'lexical' | null
  timings?: Record<string, number> // 各阶段耗时（毫秒）：embed_ms / vector_ms / keyword_ms / rerank_ms，另有 keyword_count
  kb_denied: boolean // 当前角色无权检索这个库（按知识库当前权限判定），此时不召回、各项统计为 0
}

export const listKBs = (params?: PageQuery) => get<Page<KnowledgeBaseRow>>('/knowledge-bases', params)
export const getKB = (id: number) => get<KnowledgeBaseDetail>(`/knowledge-bases/${id}`)
export const createKB = (data: KnowledgeBaseInput) => post<KnowledgeBaseRow>('/knowledge-bases', data)
export const updateKB = (id: number, data: KnowledgeBaseUpdateInput) => put<KnowledgeBaseRow>(`/knowledge-bases/${id}`, data)
export const updateKBAccess = (id: number, data: KbAccessInput) => put<KnowledgeBaseDetail>(`/knowledge-bases/${id}/access`, data)
export const listKBAccessChanges = (id: number, params?: PageQuery) => get<Page<KbAccessChange>>(`/knowledge-bases/${id}/access-log`, params)
export const deleteKB = (id: number) => del(`/knowledge-bases/${id}`)
export const batchKBs = (ids: number[]) => batchAction('/knowledge-bases', ids, 'delete')
export const listDocs = (kbId: number, params?: PageQuery) => get<Page<DocumentRow>>(`/knowledge-bases/${kbId}/documents`, params)
// 上传策略：允许的扩展名与单个文件大小上限（MB），服务端是权威（不合规 400 / 413），前端只做上传前预检
export interface UploadPolicy { extensions: string[]; max_mb: number }
export const getUploadPolicy = () => get<UploadPolicy>('/knowledge-bases/upload-policy')
// 文档上传走 FormData，axios 会自动带 multipart/form-data 请求头；不设超时（默认 30 秒），几十 MB 的表格传到对象存储要一两分钟
export const uploadDoc = (kbId: number, file: File, onProgress?: (percent: number) => void) => {
  const fd = new FormData()
  fd.append('file', file)
  return client.post(`/knowledge-bases/${kbId}/documents`, fd, {
    timeout: 0,
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100)) },
  }) as unknown as Promise<{ id: number; kb_id: number; name: string; file_type: string; status: string }>
}
export const deleteDoc = (kbId: number, docId: number) => del(`/knowledge-bases/${kbId}/documents/${docId}`)
// 重新解析：失败的文档重试，或切片参数改了之后重建；处理中的文档 400
// 中断后继续：失败或已无心跳的处理中文档，从已入库的切片接着做；正常处理中 400
export const resumeDoc = (kbId: number, docId: number) => post<{ id: number; status: string; chunk_count: number; chunk_total: number | null }>(`/knowledge-bases/${kbId}/documents/${docId}/resume`)
export const reprocessDoc = (kbId: number, docId: number) => post<{ id: number; status: string }>(`/knowledge-bases/${kbId}/documents/${docId}/reprocess`)
export const batchDocs = (kbId: number, ids: number[], action: 'delete' | 'reprocess') => batchAction(`/knowledge-bases/${kbId}/documents`, ids, action)
export const searchKB = (kbId: number, data: { query: string; top_k?: number; debug?: boolean }) => post<{ items: SearchHit[]; stats?: SearchStats }>(`/knowledge-bases/${kbId}/search`, data)
// 切片列表：在分页结构上额外带文档维度信息，方便页面直接展示所属文档
export const listDocChunks = (kbId: number, docId: number, params?: PageQuery) =>
  get<Page<ChunkRow> & { doc_id: number; doc_name: string }>(`/knowledge-bases/${kbId}/documents/${docId}/chunks`, params)
