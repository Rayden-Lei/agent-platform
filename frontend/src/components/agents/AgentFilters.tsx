import { Select } from 'antd'
import type { ModelRow } from '../../api'
import { statusOptions } from '../../constants/status'
import FilterBar from '../layout/FilterBar'
import SearchInput from '../common/SearchInput'

// 智能体筛选条：名称搜索、状态、模型。
export type AgentFilterValues = { q?: string; status?: string; model_id?: string }
interface Props {
  values: AgentFilterValues
  onChange: (patch: Partial<AgentFilterValues>) => void
  onReset: () => void
  onRefresh: () => void
  models: ModelRow[]
  loading?: boolean
}

export default function AgentFilters({ values, onChange, onReset, onRefresh, models, loading }: Props) {
  return (
    <FilterBar onReset={onReset} onRefresh={onRefresh} loading={loading}>
      <SearchInput value={values.q} onChange={(q) => onChange({ q })} placeholder="搜索智能体名称" />
      <Select allowClear placeholder="状态" style={{ width: 110 }} value={values.status} onChange={(v) => onChange({ status: v })} options={statusOptions('agent')} />
      <Select allowClear showSearch optionFilterProp="label" placeholder="模型" style={{ width: 180 }} value={values.model_id} onChange={(v) => onChange({ model_id: v })} options={models.map((m) => ({ value: String(m.id), label: m.name }))} />
    </FilterBar>
  )
}
