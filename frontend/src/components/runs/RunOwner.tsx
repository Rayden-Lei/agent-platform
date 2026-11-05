import ResourceLink from '../common/ResourceLink'
import type { RunRow } from '../../api'

// 运行记录的"归属"：按实际填了哪个归属列判断，而不是按 run_type。
// 模型对话的 run_type 也是 chat（它就是一次对话），但没有智能体，只看 run_type 会渲染出一个空链接（docs/17 §3.1）。
export default function RunOwner({ run, showIcon = false }: {
  run: Pick<RunRow, 'agent_id' | 'agent_name' | 'workflow_id' | 'workflow_name' | 'model_id' | 'model_name'>
  showIcon?: boolean
}) {
  if (run.agent_id) return <ResourceLink type="agent" id={run.agent_id} name={run.agent_name} showIcon={showIcon} />
  if (run.workflow_id) return <ResourceLink type="workflow" id={run.workflow_id} name={run.workflow_name} showIcon={showIcon} />
  if (run.model_id) return <ResourceLink type="model" id={run.model_id} name={run.model_name} showIcon={showIcon} />
  return <span style={{ color: 'var(--fg-subtle)' }}>-</span>
}
