import type { AgentSnapshot } from '../../api'
import { FieldDiff } from '../common/DiffView'

// 智能体快照的字段级差异（发布弹窗、版本对比共用）。比较哪些字段由后端快照决定（snapshot_of），这里只给中文名，
// 并把模型 / 知识库 / 工具 ID 换成"名称（#ID）"便于辨认；查不到名称的（已删除或不在下拉前 100 条）保留 ID。
export const SNAPSHOT_LABELS: Record<string, string> = {
  name: '名称', description: '描述', system_prompt: '系统提示词', model_id: '模型', params: '模型参数', kb_ids: '知识库', tool_ids: '工具',
  workflow_id: '工作流（预留）', prompt_template_id: '提示词模板', prompt_template_version: '模板版本', prompt_variables: '模板变量',
}

export interface RefNames { model?: Record<number, string>; kb?: Record<number, string>; tool?: Record<number, string> }

const named = (id: unknown, names?: Record<number, string>) => (typeof id === 'number' && names?.[id] ? `${names[id]}（#${id}）` : id)
const namedList = (ids: unknown, names?: Record<number, string>) => (Array.isArray(ids) ? ids.map((i) => named(i, names)) : ids)

function readable(snap: AgentSnapshot, names: RefNames): AgentSnapshot {
  return { ...snap, model_id: named(snap.model_id, names.model), kb_ids: namedList(snap.kb_ids, names.kb), tool_ids: namedList(snap.tool_ids, names.tool) }
}

export default function SnapshotDiff({ before, after, names = {} }: { before: AgentSnapshot; after: AgentSnapshot; names?: RefNames }) {
  return <FieldDiff before={readable(before, names)} after={readable(after, names)} labels={SNAPSHOT_LABELS} />
}
