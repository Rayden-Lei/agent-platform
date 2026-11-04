import { useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'
import { Input } from '@/components/shadcn/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'

// 智能体选择器：shadcn Select 不带搜索，而这里有几十个智能体（>100 时还要远端搜），
// 所以用 Popover + 输入框自绘；remoteSearch 为真时把输入交给页面去请求。
interface Option { value: number; label: string }
interface Props {
  value: number | null
  options: Option[]
  remoteSearch?: boolean
  onSearch?: (q: string) => void
  onChange: (id: number) => void
  emptyText?: string
  placeholder?: string
}

export default function AgentPicker({ value, options, remoteSearch, onSearch, onChange, emptyText = '没有可选项', placeholder = '选择已发布的智能体' }: Props) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const selected = options.find((o) => o.value === value)
  // 本地模式自己过滤；远端模式已经把结果收窄了，不再二次过滤
  const shown = remoteSearch ? options : options.filter((o) => o.label.toLowerCase().includes(keyword.trim().toLowerCase()))

  const type = (v: string) => {
    setKeyword(v)
    if (remoteSearch) onSearch?.(v)
  }

  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (!next) { setKeyword(''); if (remoteSearch) onSearch?.('') } }}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={placeholder}
          className="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-border-strong bg-transparent px-3 text-[13.5px] text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <span className={`truncate ${selected ? '' : 'text-muted-foreground'}`}>{selected?.label ?? placeholder}</span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[260px] p-1.5">
        <div className="relative mb-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input autoFocus value={keyword} onChange={(e) => type(e.target.value)} placeholder="搜索智能体" className="h-8 pl-7 text-[13px]" />
        </div>
        <div className="max-h-[280px] overflow-auto">
          {shown.length === 0 && <p className="m-0 px-2 py-1.5 text-[12.5px] text-muted-foreground">{emptyText}</p>}
          {shown.map((o) => (
            <button
              key={o.value}
              type="button"
              onClick={() => { onChange(o.value); setOpen(false) }}
              className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-[13.5px] hover:bg-accent"
            >
              <span className="truncate">{o.label}</span>
              {o.value === value && <Check className="size-3.5 shrink-0 text-primary" />}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
