import { X } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import type { ModelRow } from '../../api'
import { statusOptions } from '../../constants/status'
import FilterBar from '../layout/FilterBar'
import SearchInput from '../common/SearchInput'

// 智能体筛选条：名称搜索、状态、模型；工具 / 知识库 / 模板只从其他页面的链接带入（URL 参数），显示为可关闭的标签。
export type AgentFilterValues = { q?: string; status?: string; model_id?: string; tool_id?: string; kb_id?: string; prompt_template_id?: string }
const LINKED: { key: 'tool_id' | 'kb_id' | 'prompt_template_id'; label: string }[] = [
  { key: 'tool_id', label: '工具' },
  { key: 'kb_id', label: '知识库' },
  { key: 'prompt_template_id', label: '模板' },
]

// 下拉里的"全部"用哨兵值表示：Radix Select 没有 allowClear，清空要靠显式选项
const ALL = 'all'
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
      <Select value={values.status ?? ALL} onValueChange={(v) => onChange({ status: v === ALL ? undefined : v })}>
        <SelectTrigger size="sm" className="h-8 w-[110px] text-[13px]" aria-label="状态">
          <SelectValue placeholder="状态" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>全部状态</SelectItem>
          {statusOptions('agent').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={values.model_id ?? ALL} onValueChange={(v) => onChange({ model_id: v === ALL ? undefined : v })}>
        <SelectTrigger size="sm" className="h-8 w-[180px] text-[13px]" aria-label="模型">
          <SelectValue placeholder="模型" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>全部模型</SelectItem>
          {models.map((m) => <SelectItem key={m.id} value={String(m.id)}>{m.name}</SelectItem>)}
        </SelectContent>
      </Select>
      {LINKED.filter((l) => values[l.key]).map((l) => (
        <span key={l.key} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-[3px] text-[12.5px] text-foreground">
          {l.label} #{values[l.key]}
          <button
            type="button"
            aria-label={`取消${l.label}筛选`}
            className="rounded-full p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            onClick={() => onChange({ [l.key]: undefined })}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
    </FilterBar>
  )
}
