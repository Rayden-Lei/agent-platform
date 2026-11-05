import { useEffect, useState } from 'react'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/shadcn/input'

// 服务端搜索框：300ms 防抖后才把 q 交给筛选条件，避免每敲一个字发一次请求。
interface Props {
  value?: string
  onChange: (value?: string) => void
  placeholder?: string
  width?: number
}

export default function SearchInput({ value, onChange, placeholder = '搜索名称', width = 220 }: Props) {
  const [text, setText] = useState(value ?? '')
  useEffect(() => { setText(value ?? '') }, [value])
  useEffect(() => {
    const handle = setTimeout(() => { if ((text || undefined) !== (value || undefined)) onChange(text || undefined) }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])

  // 宽度用 maxWidth 而不是 width：窄屏的筛选条把它压成半宽两列时，固定 width 会溢出
  // （内联 width 的优先级高于任何 class，CSS 里的 flex-basis 压不住它）
  return (
    <div className="relative" style={{ maxWidth: width, flex: '1 1 auto', minWidth: 0 }}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        className="h-8 pr-7 pl-8 text-[13px]"
      />
      {text && (
        <button
          type="button"
          aria-label="清空"
          onClick={() => setText('')}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:bg-accent"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  )
}
