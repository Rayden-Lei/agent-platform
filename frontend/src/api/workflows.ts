import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'
import type { RunRow } from './runs'

// ===== 工作流（docs/04 4.9，含测试运行、人工审核恢复、发布版本 FR-075）=====
export interface WorkflowGraph { nodes: Array<{ id: string; type: string; config: Record<string, unknown>; position?: { x: number; y: number } }>; edges: Array<{ from: string; to: string; when?: string }> }
export interface WorkflowRow {
  id: number
  name: string
  description: string | null
  status: string
  version: number // 草稿修订号：每保存一次 +1，与线上版本无关
  node_count: number
  node_types: Record<string, number>
  schedules_count: number
  created_by: number | null
  created_by_username: string | null
  created_at: string | null
  updated_at: string | null
  runs_7d: number
  last_run_at: string | null
  // 发布语义（FR-075）：线上版本号与时间；草稿与线上快照是否不同（计算值，不入库）
  published_version: number | null
  published_at: string | null
  has_unpublished_changes: boolean
}
export interface WorkflowDetail extends WorkflowRow {
  graph: WorkflowGraph

  schedules: { id: number; name: string; cron: string; is_enabled: boolean; last_run_at: string | null }[]
}
export interface WorkflowInput { name: string; description?: string; graph: WorkflowGraph }
// 开始 / 结束节点的输入输出声明（docs/15 WF-04）：运行弹窗、定时任务表单按它生成表单项，
// 变量没有默认值即必填；引用写法 {{start.变量名}} 在变量列表里统一提示
export interface WorkflowVariableDecl { name: string; type: 'text' | 'number' | 'integer' | 'boolean'; description: string; default: unknown; required: boolean }
// 声明读的是线上版本（FR-075）：外部调用方按它填参，必须与实际执行的图一致
export interface WorkflowParameters { workflow_id: number; version: number; variables: WorkflowVariableDecl[]; outputs: { name: string; ref: string }[] }
// 运行 / 试运行 / 续跑的响应：status 为 success / awaiting_review / failed
export interface WorkflowRunResult {
  run_id?: number
  status: 'success' | 'awaiting_review' | 'failed' | string
  output?: unknown
  interrupt?: unknown
  error?: string
  steps: string[]
}
// 发布版本（不可变快照）：回滚上线用 id，展示用 version 与 snapshot
export interface WorkflowVersionRow {
  id: number
  version: number
  snapshot: { name: string | null; description: string | null; graph: WorkflowGraph }
  created_at: string
  created_by: number | null
  created_by_username: string | null
  note: string | null
  is_live: boolean
  node_count: number
}
export interface WorkflowPublishResult extends WorkflowRow {
  publish_result: 'published' | 'unchanged'
}

export const listWorkflows = (params?: PageQuery) => get<Page<WorkflowRow>>('/workflows', params)
export const getWorkflow = (id: number) => get<WorkflowDetail>(`/workflows/${id}`)
export const createWorkflow = (data: WorkflowInput) => post<WorkflowRow>('/workflows', data)
// 保存只改草稿；要让改动对外生效（运行 / 对话 / 定时任务 / API Key）必须再调 publishWorkflow
export const updateWorkflow = (id: number, data: WorkflowInput) => put<WorkflowRow>(`/workflows/${id}`, data)
export const deleteWorkflow = (id: number) => del(`/workflows/${id}`)
export const duplicateWorkflow = (id: number) => post<WorkflowRow>(`/workflows/${id}/duplicate`)
export const batchWorkflows = (ids: number[]) => batchAction('/workflows', ids, 'delete')
export const runWorkflow = (id: number, data: { inputs: Record<string, unknown> }) => post<WorkflowRunResult>(`/workflows/${id}/run`, data)
export const testRunWorkflow = (data: { graph: WorkflowGraph; inputs: Record<string, unknown> }) => post<WorkflowRunResult>('/workflows/test-run', data)
export const getWorkflowParameters = (id: number) => get<WorkflowParameters>(`/workflows/${id}/parameters`)
// 保留未调用：后端这个接口就是 run_service.list_runs(workflow_id=...) 的转发，字段与过滤完全一致。
// 工作流详情页的"运行记录"页签用 RunsTable + filters={{ workflow_id }} 走 /runs 就够了，
// 而且 /runs 还多支持 source、user_id、model_id 等筛选；再接这条只会多一条等价路径。
export const listWorkflowRuns = (id: number, params?: PageQuery) => get<Page<RunRow>>(`/workflows/${id}/runs`, params)
export const resumeWorkflow = (workflowId: number, runId: number, decision: Record<string, unknown>) => post<WorkflowRunResult>(`/workflows/${workflowId}/runs/${runId}/resume`, { decision })
// 发布草稿成为线上版本（可带说明）；与线上一致时 publish_result=unchanged，不生成新版本
export const publishWorkflow = (id: number, note?: string) => post<WorkflowPublishResult>(`/workflows/${id}/publish`, note ? { note } : undefined)
export const getWorkflowVersions = (id: number, params?: PageQuery) => get<Page<WorkflowVersionRow>>(`/workflows/${id}/versions`, params)
// 回滚上线：用该版本快照生成新版本并立即上线，草稿不动（线上出事一键止血）
export const rollbackWorkflow = (id: number, versionId: number) => post<WorkflowPublishResult>(`/workflows/${id}/rollback/${versionId}`)
// 恢复到草稿：草稿 = 该版本快照，线上不变（日常改版用）
export const restoreWorkflowVersion = (id: number, versionId: number) => post<WorkflowRow>(`/workflows/${id}/versions/${versionId}/restore`)
