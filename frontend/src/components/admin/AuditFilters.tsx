import { Input, InputNumber, Select } from 'antd'
import { statusOptions } from '../../constants/status'
import DateRangeFilter from '../common/DateRangeFilter'
import FilterBar from '../layout/FilterBar'
import SearchInput from '../common/SearchInput'

// 审计日志筛选条：用户名 / 操作 / 资源 / 资源 ID / IP / 时间区间；值由页面用 useQueryState 放进 URL。
export type AuditFilterValues = {
  username?: string
  action?: string
  resource?: string
  resource_id?: string
  ip?: string
  created_from?: string
  created_to?: string
}
interface Props {
  values: AuditFilterValues
  onChange: (patch: Partial<AuditFilterValues>) => void
  onReset: () => void
  onRefresh: () => void
  onExport: () => void
  loading?: boolean
}

export default function AuditFilters({ values, onChange, onReset, onRefresh, onExport, loading }: Props) {
  return (
    <FilterBar onReset={onReset} onRefresh={onRefresh} onExport={onExport} loading={loading}>
      <SearchInput value={values.username} onChange={(username) => onChange({ username })} placeholder="用户名" width={140} />
      <Select allowClear placeholder="操作" style={{ width: 120 }} value={values.action} onChange={(v) => onChange({ action: v })} options={statusOptions('auditAction')} />
      <Select allowClear placeholder="资源" style={{ width: 120 }} value={values.resource} onChange={(v) => onChange({ resource: v })} options={statusOptions('auditResource')} />
      <InputNumber placeholder="资源 ID" style={{ width: 110 }} min={1} value={values.resource_id ? Number(values.resource_id) : undefined} onChange={(v) => onChange({ resource_id: v ? String(v) : undefined })} />
      <Input allowClear placeholder="IP" style={{ width: 140 }} value={values.ip} onChange={(e) => onChange({ ip: e.target.value || undefined })} />
      <DateRangeFilter value={values.created_from && values.created_to ? [values.created_from, values.created_to] : null} onChange={(range) => onChange({ created_from: range?.[0], created_to: range?.[1] })} />
    </FilterBar>
  )
}
