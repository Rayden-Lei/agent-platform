import { useMemo, useState } from 'react'
import { TriangleAlert, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useSystemStatus } from '../../hooks/useSystemStatus'

// 全局降级横幅：/system/status.degraded 非空时显示在顶栏下方，每项给出对应入口；关闭后本会话内不再出现（按内容签名）。
const ENTRY: Record<string, { to: string; label: string }> = {
  embedding: { to: '/knowledge-bases', label: '知识库' },
  rerank: { to: '/knowledge-bases', label: '知识库' },
  model_breaker: { to: '/models', label: '模型' },
  scheduler: { to: '/schedules', label: '定时任务' },
}

export default function DegradedBanner() {
  const { status } = useSystemStatus()
  const items = status?.degraded ?? []
  const signature = useMemo(() => items.map((i) => i.item + ':' + i.message).join('|'), [items])
  const [dismissed, setDismissed] = useState<string | null>(() => sessionStorage.getItem('degraded-dismissed'))
  if (!items.length || dismissed === signature) return null

  const close = () => {
    sessionStorage.setItem('degraded-dismissed', signature)
    setDismissed(signature)
  }

  return (
    <div className="flex shrink-0 items-start gap-2 border-b border-[rgba(217,119,6,.28)] bg-[rgba(217,119,6,.10)] px-4 py-1.5 text-[12.5px] sm:px-5">
      <TriangleAlert className="mt-[3px] size-3.5 shrink-0 text-[#B45309]" />
      <div className="min-w-0 flex-1 text-foreground">
        系统有 {items.length} 项能力在降级运行：
        {items.map((i, idx) => (
          <span key={idx} className="ml-2">
            {i.message}
            {ENTRY[i.item] && <Link to={ENTRY[i.item].to} className="ml-1 text-primary hover:underline">去{ENTRY[i.item].label}</Link>}
            {idx < items.length - 1 && '；'}
          </span>
        ))}
      </div>
      <button type="button" aria-label="关闭提示" onClick={close} className="relative rounded p-1 text-muted-foreground hover:bg-black/5 after:absolute after:-inset-2 after:content-['']">
        <X className="size-3.5" />
      </button>
    </div>
  )
}
