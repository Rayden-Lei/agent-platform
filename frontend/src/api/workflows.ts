import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'
import type { RunRow } from './runs'

// ===== 工作流（docs/04 4.9，含测试运行、人工审核恢复）=====
export interface WorkflowGraph { nodes: Array<{ id: string; type: string; config: Record<string, unknown>; position?: { x: number; y: number } }>; edges: Array<{ from: string; to: string; when?: string }> }
export interface WorkflowRow {
  id: number
  name: string
  description: string | null
  status: string
  version: number
  node_count: number
  node_types: Record<string, number>
  schedules_count: number
  created_by: number | null
  created_by_username: string | null
  created_at: string | null
  updated_at: string | null
  runs_7d: number
  last_run_at: string | null
}
export interface WorkflowDetail extends WorkflowRow {
  graph: WorkflowGraph
  agents: { id: number; name: string; status: string }[]
  schedules: { id: number; name: string; cron: string; is_enabled: boolean; last_run_at: string | null }[]
}
export interface WorkflowInput { name: string; description?: string; graph: WorkflowGraph }
// 开始 / 结束节点的输入输出声明（docs/15 WF-04）：运行弹窗、定时任务表单按它生成表单项，
// 变量没有默认值即必填；引用写法 {{start.变量名}} 在变量列表里统一提示
export interface WorkflowVariableDecl { name: string; type: 'text' | 'number' | 'integer' | 'boolean'; description: string; default: unknown; required: boolean }
export interface WorkflowParameters { workflow_id: number; variables: WorkflowVariableDecl[]; outputs: { name: string; ref: string }[] }
// 运行 / 试运行 / 续跑的响应：status 为 success / awaiting_review / failed
export interface WorkflowRunResult {
  run_id?: number
  status: 'success' | 'awaiting_review' | 'failed' | string
  output?: unknown
  interrupt?: unknown
  error?: string
  steps: string[]
}

export const listWorkflows = (params?: PageQuery) => get<Page<WorkflowRow>>('/workflows', params)
export const getWorkflow = (id: number) => get<WorkflowDetail>(`/workflows/${id}`)
export const createWorkflow = (data: WorkflowInput) => post<WorkflowRow>('/workflows', data)
export const updateWorkflow = (id: number, data: WorkflowInput) => put<{ id: number; name: string; version: number }>(`/workflows/${id}`, data)
export const deleteWorkflow = (id: number) => del(`/workflows/${id}`)
export const duplicateWorkflow = (id: number) => post<WorkflowRow>(`/workflows/${id}/duplicate`)
export const batchWorkflows = (ids: number[]) => batchAction('/workflows', ids, 'delete')
export const runWorkflow = (id: number, data: { inputs: Record<string, unknown> }) => post<WorkflowRunResult>(`/workflows/${id}/run`, data)
export const testRunWorkflow = (data: { graph: WorkflowGraph; inputs: Record<string, unknown> }) => post<WorkflowRunResult>('/workflows/test-run', data)
export const getWorkflowParameters = (id: number) => get<WorkflowParameters>(`/workflows/${id}/parameters`)
export const listWorkflowRuns = (id: number, params?: PageQuery) => get<Page<RunRow>>(`/workflows/${id}/runs`, params)
export const resumeWorkflow = (workflowId: number, runId: number, decision: Record<string, unknown>) => post<WorkflowRunResult>(`/workflows/${workflowId}/runs/${runId}/resume`, { decision })
