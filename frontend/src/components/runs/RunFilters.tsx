import { useEffect, useState } from 'react'
import { Select } from 'antd'
import { listAgents, listWorkflows, OPTIONS_PAGE } from '../../api'
import { statusOptions } from '../../constants/status'
import DateRangeFilter from '../common/DateRangeFilter'
import FilterBar from '../../components/layout/FilterBar'

// 运行记录筛选条：类型 / 状态 / 来源 / 智能体 / 工作流 / 发起时间区间；值由页面用 useQueryState 放进 URL。
// 用 type 而不是 interface：useQueryState 要求隐式索引签名（interface 没有）
export type RunFilterValues = {
  run_type?: string
  status?: string
  source?: string
  agent_id?: string
  workflow_id?: string
  started_from?: string
  started_to?: string
}
interface Props {
  values: RunFilterValues
  onChange: (patch: Partial<RunFilterValues>) => void
  onReset: () => void
  onRefresh: () => void
  onExport: () => void
  loading?: boolean
  lockOwner?: boolean // 详情页里已固定归属，不显示智能体 / 工作流下拉
}

interface Option { value: string; label: string }

export default function RunFilters({ values, onChange, onReset, onRefresh, onExport, loading, lockOwner = false }: Props) {
  const [agents, setAgents] = useState<Option[]>([])
  const [workflows, setWorkflows] = useState<Option[]>([])
  useEffect(() => {
    if (lockOwner) return
    // 下拉选项各取前 100 条（docs/07 第 7 节）；失败不阻塞筛选，只是没有选项
    listAgents(OPTIONS_PAGE).then((p) => setAgents(p.items.map((a) => ({ value: String(a.id), label: a.name })))).catch(() => setAgents([]))
    listWorkflows(OPTIONS_PAGE).then((p) => setWorkflows(p.items.map((w) => ({ value: String(w.id), label: w.name })))).catch(() => setWorkflows([]))
  }, [lockOwner])

  return (
    <FilterBar onReset={onReset} onRefresh={onRefresh} onExport={onExport} loading={loading}>
      <Select allowClear placeholder="类型" style={{ width: 110 }} value={values.run_type} onChange={(v) => onChange({ run_type: v })} options={statusOptions('runType')} />
      <Select allowClear placeholder="状态" style={{ width: 120 }} value={values.status} onChange={(v) => onChange({ status: v })} options={statusOptions('run')} />
      <Select allowClear placeholder="触发来源" style={{ width: 120 }} value={values.source} onChange={(v) => onChange({ source: v })} options={statusOptions('runSource')} />
      {!lockOwner && <Select allowClear showSearch optionFilterProp="label" placeholder="智能体" style={{ width: 160 }} value={values.agent_id} onChange={(v) => onChange({ agent_id: v })} options={agents} />}
      {!lockOwner && <Select allowClear showSearch optionFilterProp="label" placeholder="工作流" style={{ width: 160 }} value={values.workflow_id} onChange={(v) => onChange({ workflow_id: v })} options={workflows} />}
      <DateRangeFilter
        value={values.started_from && values.started_to ? [values.started_from, values.started_to] : null}
        onChange={(range) => onChange({ started_from: range?.[0], started_to: range?.[1] })}
      />
    </FilterBar>
  )
}
