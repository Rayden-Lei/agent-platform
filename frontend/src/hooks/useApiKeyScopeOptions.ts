import { listAgents, listKBs, listWorkflows, OPTIONS_PAGE } from '../api'
import { useAsyncData } from './useAsyncData'

// API Key 表单的作用域下拉（docs/15 3.7.1）：智能体、工作流、知识库各取第一页（100 个），只在表单打开时取。
// 智能体带上它草稿绑定的知识库、知识库带上是否公开，表单据此提示"这些库对该 Key 检索不到"。
// 知识库列表只含当前登录人看得到的（KB-01），与服务端"知识库须对归属人可见"的校验一致；admin 代改他人 Key 时以服务端为准。
export interface ScopeOptions {
  agents: { id: number; name: string; kb_ids: number[] }[]
  workflows: { id: number; name: string }[]
  kbs: { id: number; name: string; is_public: boolean }[]
  loading: boolean
  error: string | null
}

export function useApiKeyScopeOptions(enabled: boolean): ScopeOptions {
  const { data, loading, error } = useAsyncData(
    () => Promise.all([listAgents(OPTIONS_PAGE), listWorkflows(OPTIONS_PAGE), listKBs(OPTIONS_PAGE)]),
    [enabled], { auto: enabled, errorText: '加载可授权的资源失败' },
  )
  const [agents, workflows, kbs] = data ?? []
  return {
    agents: (agents?.items ?? []).map((a) => ({ id: a.id, name: a.name, kb_ids: a.kb_ids ?? [] })),
    workflows: (workflows?.items ?? []).map((w) => ({ id: w.id, name: w.name })),
    kbs: (kbs?.items ?? []).map((k) => ({ id: k.id, name: k.name, is_public: k.is_public })),
    loading, error,
  }
}
