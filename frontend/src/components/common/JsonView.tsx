import { useState } from 'react'
import { toast } from 'sonner'
import { Copy } from 'lucide-react'
import Button from '../ui/Button'

// JSON / 长文本展示：缩进、复制、超高折叠；取代散落的 <pre>{JSON.stringify(...)}</pre>。
interface Props {
  value: unknown
  maxHeight?: number
  title?: string
}

function toText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') {
    // 字符串本身可能是 JSON（节点日志的输入输出快照），能解析就格式化
    try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
  }
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}

export default function JsonView({ value, maxHeight = 240, title }: Props) {
  const [expanded, setExpanded] = useState(false)
  const text = toText(value)
  if (!text) return <span className="text-[13px] text-muted-foreground">（空）</span>
  const long = text.split('\n').length > 12 || text.length > 800
  const copy = () => navigator.clipboard?.writeText(text).then(() => toast.success('已复制'))
  return (
    <div className="json-view">
      <div className="json-view-bar">
        <span className="text-[12px] text-muted-foreground">{title}</span>
        <div className="flex items-center gap-1">
          {long && <Button size="sm" variant="ghost" onClick={() => setExpanded(!expanded)}>{expanded ? '收起' : '展开'}</Button>}
          <Button size="sm" variant="ghost" aria-label="复制" onClick={copy}><Copy className="size-3.5" /></Button>
        </div>
      </div>
      <pre style={{ maxHeight: expanded ? undefined : maxHeight }}>{text}</pre>
    </div>
  )
}
