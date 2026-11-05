import { Input } from '@/components/shadcn/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
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

const ALL = '__all__'

export default function AuditFilters({ values, onChange, onReset, onRefresh, onExport, loading }: Props) {
  return (
    <FilterBar onReset={onReset} onRefresh={onRefresh} onExport={onExport} loading={loading}
      activeCount={Object.values(values).filter(Boolean).length}>
      <SearchInput value={values.username} onChange={(username) => onChange({ username })} placeholder="用户名" width={140} />

      {/* 原来 antd 的 allowClear 改成一项"全部"：清空也走同一个 onChange 通道 */}
      <Select value={values.action ?? ALL} onValueChange={(v) => onChange({ action: v === ALL ? undefined : v })}>
        <SelectTrigger size="sm" className="h-8 w-[120px] text-[13px]" aria-label="操作">
          <SelectValue placeholder="操作" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>全部操作</SelectItem>
          {statusOptions('auditAction').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>

      <Select value={values.resource ?? ALL} onValueChange={(v) => onChange({ resource: v === ALL ? undefined : v })}>
        <SelectTrigger size="sm" className="h-8 w-[120px] text-[13px]" aria-label="资源">
          <SelectValue placeholder="资源" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>全部资源</SelectItem>
          {statusOptions('auditResource').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>

      <Input
        type="number"
        min={1}
        placeholder="资源 ID"
        aria-label="资源 ID"
        className="h-8 w-[110px] text-[13px]"
        value={values.resource_id ?? ''}
        onChange={(e) => onChange({ resource_id: e.target.value ? e.target.value : undefined })}
      />

      <Input
        placeholder="IP"
        aria-label="IP"
        className="h-8 w-[140px] text-[13px]"
        value={values.ip ?? ''}
        onChange={(e) => onChange({ ip: e.target.value || undefined })}
      />

      <DateRangeFilter value={values.created_from && values.created_to ? [values.created_from, values.created_to] : null} onChange={(range) => onChange({ created_from: range?.[0], created_to: range?.[1] })} />
    </FilterBar>
  )
}
