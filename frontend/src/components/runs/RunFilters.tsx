import { useEffect, useState } from 'react'
import { ChevronDown, X } from 'lucide-react'
import { Input } from '@/components/shadcn/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { listAgents, listWorkflows, OPTIONS_PAGE } from '../../api'
import { statusOptions } from '../../constants/status'
import DateRangeFilter from '../common/DateRangeFilter'
import FilterTrigger from '../common/FilterTrigger'
import FilterBar from '../../components/layout/FilterBar'

// 运行记录筛选条：类型 / 状态 / 来源 / 智能体 / 工作流 / 发起时间区间；值由页面用 useQueryState 放进 URL。
// model_id 只从模型页链接带入，显示为可关闭标签。用 type 而不是 interface：useQueryState 要求隐式索引签名（interface 没有）
export type RunFilterValues = {
  run_type?: string
  status?: string
  source?: string
  agent_id?: string
  workflow_id?: string
  model_id?: string
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

// 可搜索单选：智能体 / 工作流可能有上百条，shadcn Select 没有内置搜索，这里用 Popover + 输入框自己拼一个
function SearchSelect({ value, onChange, placeholder, options, width }: {
  value?: string
  onChange: (v?: string) => void
  placeholder: string
  options: Option[]
  width: number
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const current = options.find((o) => o.value === value)
  const keyword = q.trim().toLowerCase()
  const shown = keyword ? options.filter((o) => o.label.toLowerCase().includes(keyword)) : options
  const pick = (v?: string) => { onChange(v); setOpen(false); setQ('') }

  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (!next) setQ('') }}>
      <PopoverTrigger asChild>
        <FilterTrigger style={{ width }} muted={!current} aria-label={placeholder} suffix={<ChevronDown className="size-3.5 opacity-60" />}>
          {current?.label ?? placeholder}
        </FilterTrigger>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[240px] p-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索名称" className="h-8 text-[13px]" />
        {/* 限高 + flex-col 时子项默认 flex-shrink:1，会被压扁（15 项从 32px 压到 16px、文字被裁掉）；
            列表要么滚要么整项显示，所以子项一律 shrink-0 */}
        <div className="mt-1.5 flex max-h-[260px] flex-col gap-0.5 overflow-y-auto [&>*]:shrink-0">
          <button
            type="button"
            onClick={() => pick(undefined)}
            className="rounded-md px-2 py-1.5 text-left text-[13px] text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            全部{placeholder}
          </button>
          {shown.length === 0 && <span className="px-2 py-3 text-center text-[12.5px] text-muted-foreground">没有匹配项</span>}
          {shown.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => pick(o.value)}
              className={`truncate rounded-md px-2 py-1.5 text-left text-[13px] hover:bg-accent hover:text-foreground ${o.value === value ? 'bg-accent text-foreground' : 'text-foreground'}`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

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
      <Select value={values.run_type ?? 'all'} onValueChange={(v) => onChange({ run_type: v === 'all' ? undefined : v })}>
        <SelectTrigger size="sm" className="w-[110px] text-[13px]" aria-label="类型"><SelectValue placeholder="类型" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部类型</SelectItem>
          {statusOptions('runType').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>

      <Select value={values.status ?? 'all'} onValueChange={(v) => onChange({ status: v === 'all' ? undefined : v })}>
        <SelectTrigger size="sm" className="w-[120px] text-[13px]" aria-label="状态"><SelectValue placeholder="状态" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部状态</SelectItem>
          {statusOptions('run').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>

      <Select value={values.source ?? 'all'} onValueChange={(v) => onChange({ source: v === 'all' ? undefined : v })}>
        <SelectTrigger size="sm" className="w-[120px] text-[13px]" aria-label="触发来源"><SelectValue placeholder="触发来源" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">全部来源</SelectItem>
          {statusOptions('runSource').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
        </SelectContent>
      </Select>

      {!lockOwner && <SearchSelect value={values.agent_id} onChange={(v) => onChange({ agent_id: v })} placeholder="智能体" options={agents} width={160} />}
      {!lockOwner && <SearchSelect value={values.workflow_id} onChange={(v) => onChange({ workflow_id: v })} placeholder="工作流" options={workflows} width={160} />}

      {values.model_id && (
        <span className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-secondary px-2 text-[12.5px] text-foreground">
          模型 #{values.model_id}
          <button type="button" aria-label="移除模型筛选" onClick={() => onChange({ model_id: undefined })} className="rounded p-0.5 text-muted-foreground hover:text-foreground">
            <X className="size-3.5" />
          </button>
        </span>
      )}

      <DateRangeFilter
        value={values.started_from && values.started_to ? [values.started_from, values.started_to] : null}
        onChange={(range) => onChange({ started_from: range?.[0], started_to: range?.[1] })}
      />
    </FilterBar>
  )
}
