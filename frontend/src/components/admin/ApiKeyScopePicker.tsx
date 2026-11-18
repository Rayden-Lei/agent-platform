import { useState } from 'react'
import { ChevronsUpDown, X } from 'lucide-react'
import { Checkbox } from '@/components/shadcn/checkbox'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import type { ApiKeyScopeItem } from '../../api'

// 授权范围的多选（docs/15 3.7.1）：shadcn 没有多选下拉，用 Popover + 搜索框 + 复选框列表，
// 已选项在下方以可移除的标签展示。已删除 / 不在候选第一页的资源也要能显示名字（否则只剩一个数字），
// 统一显示为"已删除 #id"。
// 从 ApiKeyForm 拆出来：表单加上有效期后超过 docs/07 第 9 节的 300 行，这个区块是独立交互、可单独复用。
interface Props {
  label: string; hint: string; placeholder: string
  options: { id: number; name: string }[]
  /** 编辑时已有的授权项，名字为 null 表示资源已删除 */
  current?: ApiKeyScopeItem[]
  value: number[]; loading: boolean; onChange: (ids: number[]) => void
}

export default function ApiKeyScopePicker({ label, hint, placeholder, options, current, value, loading, onChange }: Props) {
  const [keyword, setKeyword] = useState('')
  const known = new Set(options.map((o) => o.id))
  const extras = (current ?? []).filter((c) => !known.has(c.id) && value.includes(c.id))
    .map((c) => ({ id: c.id, name: c.name ?? `已删除 #${c.id}` }))
  const all = [...options, ...extras]
  const keywordText = keyword.trim()
  const shown = keywordText ? all.filter((o) => o.name.includes(keywordText)) : all
  const toggle = (id: number) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])

  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-3 text-left text-[13px] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <span className={value.length ? 'truncate text-foreground' : 'truncate text-muted-foreground'}>
              {value.length ? `已选 ${value.length} 项` : placeholder}
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[360px] p-0">
          <div className="border-b border-border p-2">
            <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索名称" className="h-8 text-[13px]" />
          </div>
          <div className="max-h-56 overflow-y-auto p-1">
            {loading && <p className="m-0 px-2 py-3 text-[12.5px] text-muted-foreground">加载中…</p>}
            {!loading && shown.length === 0 && <p className="m-0 px-2 py-3 text-[12.5px] text-muted-foreground">没有匹配的资源</p>}
            {!loading && shown.map((o) => (
              <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent">
                <Checkbox checked={value.includes(o.id)} onCheckedChange={() => toggle(o.id)} />
                <span className="min-w-0 truncate text-[13px] text-foreground">{o.name}</span>
              </label>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-border px-2 py-1.5">
            <span className="text-[12px] text-muted-foreground">已选 {value.length} 项</span>
            {value.length > 0 && (
              <button type="button" className="text-[12px] text-muted-foreground hover:text-foreground" onClick={() => onChange([])}>清空</button>
            )}
          </div>
        </PopoverContent>
      </Popover>

      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {all.filter((o) => value.includes(o.id)).map((o) => (
            <span key={o.id} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-[1px] text-[11.5px] text-foreground">
              {o.name}
              <button type="button" aria-label={`移除 ${o.name}`} className="text-muted-foreground hover:text-destructive" onClick={() => toggle(o.id)}>
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <p className="m-0 text-[12px] text-muted-foreground">{hint}</p>
    </div>
  )
}
